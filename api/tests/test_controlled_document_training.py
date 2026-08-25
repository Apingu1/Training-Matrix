from __future__ import annotations

from datetime import date, timedelta

from reportlab.pdfgen.canvas import Canvas

from .conftest import DOCUMENT_ROOT

ADMIN_INITIAL = "Initial-Admin-Password1!"
ADMIN_PASSWORD = "Permanent-Admin-Password2!"
QA_INITIAL = "Temporary-QA-Password3!"
QA_PASSWORD = "Permanent-QA-Password4!"
OPERATOR_INITIAL = "Temporary-Operator-Password5!"
OPERATOR_PASSWORD = "Permanent-Operator-Password6!"


def assert_ok(response, expected: int = 200):
    assert response.status_code == expected, response.text
    return response.json()


def test_complete_document_release_and_training_flow(client, helpers):
    login = helpers["login"]
    change_password = helpers["change_password"]
    headers = helpers["headers"]

    admin_token = login(client, "admin", ADMIN_INITIAL)
    blocked = client.get("/api/documents", headers=headers(admin_token))
    assert blocked.status_code == 403
    assert "temporary password" in blocked.text
    change_password(client, admin_token, ADMIN_INITIAL, ADMIN_PASSWORD)
    admin_token = login(client, "admin", ADMIN_PASSWORD)
    admin_headers = headers(admin_token)

    security_roles = assert_ok(client.get("/api/admin/security-roles", headers=admin_headers))
    qa_role_id = next(role["id"] for role in security_roles if role["code"] == "QA_APPROVER")
    operator_role_id = next(role["id"] for role in security_roles if role["code"] == "OPERATOR")

    job_role = assert_ok(
        client.post(
            "/api/admin/job-roles",
            headers=admin_headers,
            json={
                "code": "PRODUCTION_OPERATOR",
                "name": "Production Operator",
                "department": "Production",
                "description": "Manufacturing operations",
                "reason": "Initial validated role configuration",
            },
        ),
        201,
    )

    assert_ok(
        client.post(
            "/api/admin/users",
            headers=admin_headers,
            json={
                "username": "qa.approver",
                "display_name": "QA Approver",
                "security_role_id": qa_role_id,
                "temporary_password": QA_INITIAL,
                "job_role_ids": [],
                "reason": "Independent approval account",
            },
        ),
        201,
    )
    operator = assert_ok(
        client.post(
            "/api/admin/users",
            headers=admin_headers,
            json={
                "username": "production.operator",
                "display_name": "Production Operator One",
                "security_role_id": operator_role_id,
                "temporary_password": OPERATOR_INITIAL,
                "job_role_ids": [job_role["id"]],
                "reason": "New production operator",
            },
        ),
        201,
    )

    source_dir = DOCUMENT_ROOT / "SOP"
    source_dir.mkdir()
    source_file = source_dir / "ES.SOP.001.V01.pdf"
    pdf = Canvas(str(source_file))
    pdf.drawString(72, 760, "ES.SOP.001.V01 - Production Operation")
    pdf.save()

    family = assert_ok(
        client.post(
            "/api/documents",
            headers=admin_headers,
            json={
                "code": "ES.SOP.001",
                "title": "Production Operation",
                "document_type": "SOP",
                "owner_department": "Production",
                "description": "Controlled production procedure",
                "review_interval_months": 24,
                "reason": "Initial controlled master-list record",
            },
        ),
        201,
    )
    version = assert_ok(
        client.post(
            f"/api/documents/{family['id']}/versions",
            headers=admin_headers,
            json={
                "version_label": "V01",
                "relative_path": "SOP/ES.SOP.001.V01.pdf",
                "change_summary": "Initial issue",
                "training_impact": "RETRAIN",
                "review_due_date": (date.today() + timedelta(days=730)).isoformat(),
                "reason": "Register initial controlled source",
            },
        ),
        201,
    )
    requirement = assert_ok(
        client.post(
            "/api/training/requirements",
            headers=admin_headers,
            json={
                "job_role_id": job_role["id"],
                "document_family_id": family["id"],
                "requirement_type": "READ_UNDERSTAND",
                "due_days": 14,
                "reason": "Production curriculum requirement",
            },
        ),
        201,
    )
    assert requirement["training_assignments_created"] == 0

    source_file.write_bytes(source_file.read_bytes() + b"controlled draft amendment")
    stale_submit = client.post(
        f"/api/document-versions/{version['id']}/transition",
        headers=admin_headers,
        json={"action": "SUBMIT", "reason": "Attempt before refreshing the draft fingerprint"},
    )
    assert stale_submit.status_code == 409
    refreshed = assert_ok(
        client.post(
            f"/api/document-versions/{version['id']}/transition",
            headers=admin_headers,
            json={
                "action": "REFRESH_SOURCE",
                "reason": "Register the final controlled draft amendment",
            },
        )
    )
    version = refreshed["version"]

    assert_ok(
        client.post(
            f"/api/document-versions/{version['id']}/transition",
            headers=admin_headers,
            json={"action": "SUBMIT", "reason": "Ready for independent QA review"},
        )
    )
    same_person_approval = client.post(
        f"/api/document-versions/{version['id']}/transition",
        headers=admin_headers,
        json={"action": "APPROVE", "reason": "Attempt", "password": ADMIN_PASSWORD},
    )
    assert same_person_approval.status_code == 409

    qa_token = login(client, "qa.approver", QA_INITIAL)
    change_password(client, qa_token, QA_INITIAL, QA_PASSWORD)
    qa_token = login(client, "qa.approver", QA_PASSWORD)
    qa_headers = headers(qa_token)
    assert_ok(client.get("/api/admin/users", headers=qa_headers))
    assert_ok(
        client.post(
            f"/api/document-versions/{version['id']}/transition",
            headers=qa_headers,
            json={
                "action": "APPROVE",
                "reason": "Content and metadata independently verified",
                "password": QA_PASSWORD,
            },
        )
    )
    release = assert_ok(
        client.post(
            f"/api/document-versions/{version['id']}/transition",
            headers=qa_headers,
            json={"action": "RELEASE", "reason": "Approved for effective use", "password": QA_PASSWORD},
        )
    )
    assert release["version"]["status"] == "RELEASED"
    assert release["assignments_created"] == 1

    controlled_copy = assert_ok(
        client.post(
            f"/api/document-versions/{version['id']}/controlled-copies",
            headers=qa_headers,
            json={
                "copy_number": "PROD-01",
                "department": "Production",
                "location": "Line 1 SOP station",
                "issued_to": "Production Supervisor",
                "reason": "Issue controlled point-of-use copy",
            },
        ),
        201,
    )
    assert controlled_copy["status"] == "ISSUED"
    closed_copy = assert_ok(
        client.post(
            f"/api/controlled-copies/{controlled_copy['id']}/close",
            headers=qa_headers,
            json={
                "disposition": "RETURNED",
                "reason": "Point-of-use copy returned to Document Control",
            },
        )
    )
    assert closed_copy["status"] == "RETURNED"

    operator_token = login(client, "production.operator", OPERATOR_INITIAL)
    change_password(client, operator_token, OPERATOR_INITIAL, OPERATOR_PASSWORD)
    operator_token = login(client, "production.operator", OPERATOR_PASSWORD)
    operator_headers = headers(operator_token)
    assignments = assert_ok(client.get("/api/training/my-assignments", headers=operator_headers))
    assert len(assignments) == 1
    assert assignments[0]["status"] == "ASSIGNED"

    disabled_requirement = assert_ok(
        client.patch(
            f"/api/training/requirements/{requirement['id']}",
            headers=admin_headers,
            json={
                "is_active": False,
                "reason": "Validate curriculum removal and reinstatement behaviour",
            },
        )
    )
    assert disabled_requirement["assignments_closed"] == 1
    cancelled = assert_ok(client.get("/api/training/my-assignments", headers=operator_headers))
    assert cancelled[0]["status"] == "CANCELLED"

    enabled_requirement = assert_ok(
        client.patch(
            f"/api/training/requirements/{requirement['id']}",
            headers=admin_headers,
            json={
                "is_active": True,
                "reason": "Validate cancelled assignments reopen when the curriculum returns",
            },
        )
    )
    assert enabled_requirement["assignments_created"] == 1
    assignments = assert_ok(client.get("/api/training/my-assignments", headers=operator_headers))
    assert assignments[0]["status"] == "ASSIGNED"

    premature_acknowledgement = client.post(
        f"/api/training/assignments/{assignments[0]['id']}/acknowledge",
        headers=operator_headers,
        json={"password": OPERATOR_PASSWORD},
    )
    assert premature_acknowledgement.status_code == 409
    source_download = client.get(
        f"/api/document-versions/{version['id']}/source",
        headers=operator_headers,
    )
    assert source_download.status_code == 403

    viewed = client.get(f"/api/document-versions/{version['id']}/view", headers=operator_headers)
    assert viewed.status_code == 200
    assert viewed.headers["content-type"].startswith("application/pdf")
    completed = assert_ok(
        client.post(
            f"/api/training/assignments/{assignments[0]['id']}/acknowledge",
            headers=operator_headers,
            json={"password": OPERATOR_PASSWORD},
        )
    )
    assert completed["status"] == "COMPLETED"
    assert completed["acknowledgement"]["source_sha256"] == version["source_sha256"]

    matrix = assert_ok(client.get(f"/api/training/matrix/{job_role['id']}", headers=qa_headers))
    operator_column = next(index for index, user in enumerate(matrix["users"]) if user["id"] == operator["id"])
    assert matrix["rows"][0]["cells"][operator_column]["status"] == "COMPLETED"

    source_file.write_bytes(source_file.read_bytes() + b"external uncontrolled change")
    blocked_view = client.get(f"/api/document-versions/{version['id']}/view", headers=operator_headers)
    assert blocked_view.status_code == 409
    assert "changed outside document control" in blocked_view.text

    audit = assert_ok(client.get("/api/audit/events?event_type=DOCUMENT_VIEW_BLOCKED", headers=qa_headers))
    assert audit["total"] == 1


def test_source_browser_rejects_path_traversal(client, helpers):
    admin_token = helpers["login"](client, "admin", ADMIN_PASSWORD)
    response = client.get("/api/documents/source/browse?path=../", headers=helpers["headers"](admin_token))
    assert response.status_code == 400
