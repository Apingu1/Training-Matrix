from __future__ import annotations

from reportlab.pdfgen.canvas import Canvas

from .conftest import DOCUMENT_ROOT
from .test_controlled_document_training import ADMIN_PASSWORD


def assert_ok(response, expected: int = 200):
    assert response.status_code == expected, response.text
    return response.json()


def test_recursive_discovery_baseline_import_and_change_detection(client, helpers):
    token = helpers["login"](client, "admin", ADMIN_PASSWORD)
    headers = helpers["headers"](token)

    nested = DOCUMENT_ROOT / "Approved Documents" / "Production" / "SOP 777"
    nested.mkdir(parents=True)
    approved = nested / "ES.SOP.777.V03 - Line Clearance.pdf"
    canvas = Canvas(str(approved))
    canvas.drawString(72, 760, "ES.SOP.777.V03 - Line Clearance")
    canvas.save()
    duplicate_folder = DOCUMENT_ROOT / "Approved Documents" / "Archive copy"
    duplicate_folder.mkdir(parents=True)
    duplicate = duplicate_folder / "ES.SOP.777.V03.pdf"
    duplicate.write_bytes(approved.read_bytes())
    unsupported = nested / "working-notes.xlsx"
    unsupported.write_bytes(b"not a controlled PDF or DOCX")
    word_lock = nested / "~$ Sop 010 F01 Internal Audit Checklist.docx"
    word_lock.write_bytes(b"temporary Microsoft Word owner file")
    form = nested / "Sop 010 F01 Internal Audit Checklist V01.docx"
    form.write_bytes(b"valid test form source")

    inventory = assert_ok(
        client.post(
            "/api/documents/source/scan",
            headers=headers,
            json={"reason": "Initial recursive controlled-source test scan"},
        )
    )
    by_path = {item["relative_path"]: item for item in inventory["items"]}
    approved_path = approved.relative_to(DOCUMENT_ROOT).as_posix()
    duplicate_path = duplicate.relative_to(DOCUMENT_ROOT).as_posix()
    unsupported_path = unsupported.relative_to(DOCUMENT_ROOT).as_posix()
    form_path = form.relative_to(DOCUMENT_ROOT).as_posix()
    word_lock_path = word_lock.relative_to(DOCUMENT_ROOT).as_posix()
    assert by_path[approved_path]["classification"] == "DUPLICATE"
    assert by_path[duplicate_path]["classification"] == "DUPLICATE"
    assert by_path[unsupported_path]["classification"] == "UNSUPPORTED"
    assert by_path[approved_path]["inferred"]["code"] == "ES.SOP.777"
    assert by_path[approved_path]["inferred"]["version_label"] == "V03"
    assert word_lock_path not in by_path
    assert by_path[form_path]["inferred"]["code"] == "ES.SOP.010.F01"
    assert by_path[form_path]["inferred"]["document_type"] == "FORM"
    assert by_path[form_path]["inferred"]["version_label"] == "V01"
    assert by_path[form_path]["inferred"]["title"] == "Internal Audit Checklist"

    import_item = {
        "relative_path": approved_path,
        "expected_sha256": by_path[approved_path]["source_sha256"],
        "code": "ES.SOP.777",
        "version_label": "V03",
        "title": "Line Clearance",
        "document_type": "SOP",
        "owner_department": "Production",
        "issue_date": by_path[approved_path]["inferred"]["issue_date"],
        "review_due_date": None,
        "review_interval_months": 24,
    }
    rejected = client.post(
        "/api/documents/source/baseline-import",
        headers=headers,
        json={
            "items": [import_item],
            "password": ADMIN_PASSWORD,
            "confirmation": "IMPORT",
            "reason": "Attempt without the controlled confirmation phrase",
        },
    )
    assert rejected.status_code == 400
    imported = assert_ok(
        client.post(
            "/api/documents/source/baseline-import",
            headers=headers,
            json={
                "items": [import_item],
                "password": ADMIN_PASSWORD,
                "confirmation": "IMPORT APPROVED DOCUMENT BASELINE",
                "reason": "Approved initial baseline from the existing external document system",
            },
        ),
        201,
    )
    assert imported["documents_imported"] == 1

    refreshed = assert_ok(client.get("/api/documents/source/inventory", headers=headers))
    refreshed_by_path = {item["relative_path"]: item for item in refreshed["items"]}
    assert refreshed_by_path[approved_path]["classification"] == "REGISTERED"
    assert refreshed_by_path[duplicate_path]["classification"] == "DUPLICATE"
    assert refreshed_by_path[duplicate_path]["registered_document"]["code"] == "ES.SOP.777"

    approved.write_bytes(approved.read_bytes() + b"external unregistered amendment")
    added = nested / "ES.SOP.778.V01.docx"
    added.write_bytes(b"test docx source")
    changed = assert_ok(
        client.post(
            "/api/documents/source/scan",
            headers=headers,
            json={"reason": "Detect subsequent additions and external changes"},
        )
    )
    changed_by_path = {item["relative_path"]: item for item in changed["items"]}
    assert changed_by_path[approved_path]["classification"] == "CHANGED"
    assert changed_by_path[added.relative_to(DOCUMENT_ROOT).as_posix()]["classification"] == "UNREGISTERED"

    approved.unlink()
    missing = assert_ok(
        client.post(
            "/api/documents/source/scan",
            headers=headers,
            json={"reason": "Detect a missing registered controlled source"},
        )
    )
    missing_by_path = {item["relative_path"]: item for item in missing["items"]}
    assert missing_by_path[approved_path]["classification"] == "MISSING"

    audit = assert_ok(
        client.get(
            "/api/audit/events?event_type=DOCUMENT_BASELINE_IMPORT_COMPLETED",
            headers=headers,
        )
    )
    assert audit["total"] == 1
