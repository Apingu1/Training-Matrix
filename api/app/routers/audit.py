from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response, StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditEvent
from ..security import AuthContext, require_permission

router = APIRouter(prefix="/audit", tags=["Audit Trail"])


def build_query(
    *,
    event_type: str | None,
    entity_type: str | None,
    actor: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    success: bool | None,
):
    query = select(AuditEvent)
    if event_type:
        query = query.where(AuditEvent.event_type.ilike(f"%{event_type}%"))
    if entity_type:
        query = query.where(AuditEvent.entity_type == entity_type)
    if actor:
        query = query.where(AuditEvent.actor_username.ilike(f"%{actor}%"))
    if date_from:
        query = query.where(AuditEvent.created_at >= date_from)
    if date_to:
        query = query.where(AuditEvent.created_at <= date_to)
    if success is not None:
        query = query.where(AuditEvent.success == success)
    return query


def event_dict(event: AuditEvent) -> dict:
    return {
        "id": event.id,
        "created_at": event.created_at,
        "event_type": event.event_type,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "actor_user_id": event.actor_user_id,
        "actor_username": event.actor_username,
        "success": event.success,
        "reason": event.reason,
        "before": event.before_json,
        "after": event.after_json,
        "metadata": event.metadata_json,
        "ip_address": event.ip_address,
        "user_agent": event.user_agent,
        "request_id": event.request_id,
    }


def csv_safe(value):
    """Prevent spreadsheet formula execution when an exported CSV is opened."""
    if value is None:
        return ""
    rendered = str(value)
    if rendered.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + rendered
    return rendered


@router.get("/events")
def list_audit_events(
    event_type: str | None = None,
    entity_type: str | None = None,
    actor: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    success: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=250),
    _: AuthContext = Depends(require_permission("audit.view")),
    db: Session = Depends(get_db),
):
    query = build_query(
        event_type=event_type,
        entity_type=entity_type,
        actor=actor,
        date_from=date_from,
        date_to=date_to,
        success=success,
    )
    count_query = select(func.count()).select_from(query.subquery())
    total = db.scalar(count_query) or 0
    events = db.scalars(
        query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [event_dict(item) for item in events],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def export_events(db: Session, **filters) -> list[AuditEvent]:
    return db.scalars(
        build_query(**filters).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(10000)
    ).all()


@router.get("/events.csv")
def export_audit_csv(
    event_type: str | None = None,
    entity_type: str | None = None,
    actor: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    success: bool | None = None,
    _: AuthContext = Depends(require_permission("audit.view")),
    db: Session = Depends(get_db),
):
    events = export_events(
        db,
        event_type=event_type,
        entity_type=entity_type,
        actor=actor,
        date_from=date_from,
        date_to=date_to,
        success=success,
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "ID",
            "UTC timestamp",
            "Event",
            "Entity type",
            "Entity ID",
            "Actor",
            "Success",
            "Reason",
            "Before",
            "After",
            "Metadata",
            "IP address",
            "Request ID",
        ]
    )
    for event in events:
        writer.writerow(
            [
                csv_safe(value)
                for value in (
                    event.id,
                    event.created_at.isoformat(),
                    event.event_type,
                    event.entity_type,
                    event.entity_id,
                    event.actor_username,
                    event.success,
                    event.reason,
                    json.dumps(event.before_json, ensure_ascii=False),
                    json.dumps(event.after_json, ensure_ascii=False),
                    json.dumps(event.metadata_json, ensure_ascii=False),
                    event.ip_address,
                    event.request_id,
                )
            ]
        )
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=training-matrix-audit.csv"},
    )


@router.get("/events.pdf")
def export_audit_pdf(
    event_type: str | None = None,
    entity_type: str | None = None,
    actor: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    success: bool | None = None,
    _: AuthContext = Depends(require_permission("audit.view")),
    db: Session = Depends(get_db),
):
    events = export_events(
        db,
        event_type=event_type,
        entity_type=entity_type,
        actor=actor,
        date_from=date_from,
        date_to=date_to,
        success=success,
    )
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title="Eaststone Training Matrix Audit Trail",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Eaststone Training Matrix — Audit Trail", styles["Title"]),
        Spacer(1, 4 * mm),
    ]
    data = [["UTC timestamp", "Event", "Entity", "Actor", "Result", "Reason"]]
    for event in events[:2000]:
        data.append(
            [
                event.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                event.event_type,
                f"{event.entity_type or ''} {event.entity_id or ''}",
                event.actor_username or "SYSTEM",
                "Success" if event.success else "Failed",
                Paragraph(escape((event.reason or "")[:350]), styles["BodyText"]),
            ]
        )
    table = Table(
        data,
        repeatRows=1,
        colWidths=[35 * mm, 48 * mm, 43 * mm, 28 * mm, 18 * mm, 85 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#173b35")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5d1")),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#f3f7f5")],
                ),
            ]
        )
    )
    story.append(table)
    document.build(story)
    return Response(
        buffer.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=training-matrix-audit.pdf"},
    )
