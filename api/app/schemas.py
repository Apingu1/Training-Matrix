from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=500)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class ReauthRequest(BaseModel):
    password: str
    reason: str = Field(min_length=3, max_length=2000)


class SecurityRoleCreate(BaseModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,59}$")
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    permission_codes: list[str] = []
    reason: str = Field(min_length=3, max_length=2000)


class SecurityRoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    is_active: bool | None = None
    permission_codes: list[str] | None = None
    reason: str = Field(min_length=3, max_length=2000)


class UserCreate(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9._-]{3,80}$")
    display_name: str = Field(min_length=2, max_length=160)
    email: str | None = Field(default=None, max_length=254)
    security_role_id: int
    temporary_password: str
    job_role_ids: list[int] = []
    reason: str = Field(min_length=3, max_length=2000)


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=160)
    email: str | None = Field(default=None, max_length=254)
    security_role_id: int | None = None
    is_active: bool | None = None
    reason: str = Field(min_length=3, max_length=2000)


class PasswordResetRequest(BaseModel):
    temporary_password: str
    reason: str = Field(min_length=3, max_length=2000)


class JobRoleCreate(BaseModel):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,59}$")
    name: str = Field(min_length=2, max_length=140)
    department: str = Field(min_length=2, max_length=120)
    description: str | None = None
    reason: str = Field(min_length=3, max_length=2000)


class JobRoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=140)
    department: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    is_active: bool | None = None
    reason: str = Field(min_length=3, max_length=2000)


class UserJobRoleCreate(BaseModel):
    job_role_id: int
    effective_from: date = Field(default_factory=date.today)
    reason: str = Field(min_length=3, max_length=2000)


class UserJobRoleEnd(BaseModel):
    effective_to: date = Field(default_factory=date.today)
    reason: str = Field(min_length=3, max_length=2000)


class DocumentCreate(BaseModel):
    code: str = Field(min_length=2, max_length=100)
    title: str = Field(min_length=3, max_length=500)
    document_type: str = Field(min_length=2, max_length=60)
    owner_department: str = Field(min_length=2, max_length=120)
    description: str | None = None
    review_interval_months: int = Field(default=24, ge=1, le=120)
    reason: str = Field(min_length=3, max_length=2000)


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=500)
    document_type: str | None = Field(default=None, min_length=2, max_length=60)
    owner_department: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    review_interval_months: int | None = Field(default=None, ge=1, le=120)
    is_active: bool | None = None
    reason: str = Field(min_length=3, max_length=2000)


class DocumentVersionCreate(BaseModel):
    version_label: str = Field(min_length=1, max_length=60)
    relative_path: str = Field(min_length=1, max_length=1000)
    change_summary: str = Field(min_length=3, max_length=5000)
    training_impact: Literal["RETRAIN", "NO_RETRAIN"] = "RETRAIN"
    training_impact_reason: str | None = Field(default=None, max_length=5000)
    issue_date: date | None = None
    effective_at: datetime | None = None
    review_due_date: date | None = None
    reason: str = Field(min_length=3, max_length=2000)


class SourceScanRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class BaselineImportItem(BaseModel):
    relative_path: str = Field(min_length=1, max_length=1000)
    expected_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    code: str = Field(min_length=2, max_length=100)
    version_label: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=3, max_length=500)
    document_type: str = Field(min_length=2, max_length=60)
    owner_department: str = Field(min_length=2, max_length=120)
    issue_date: date | None = None
    review_due_date: date | None = None
    review_interval_months: int = Field(default=24, ge=1, le=120)


class BaselineImportRequest(BaseModel):
    items: list[BaselineImportItem] = Field(min_length=1, max_length=5000)
    password: str = Field(min_length=1, max_length=500)
    confirmation: str
    reason: str = Field(min_length=3, max_length=2000)


class DocumentTransition(BaseModel):
    action: Literal[
        "REFRESH_SOURCE",
        "SUBMIT",
        "RETURN_TO_DRAFT",
        "APPROVE",
        "RELEASE",
        "OBSOLETE",
    ]
    reason: str = Field(min_length=3, max_length=2000)
    password: str | None = None


class ControlledCopyCreate(BaseModel):
    copy_number: str = Field(min_length=1, max_length=80)
    department: str = Field(min_length=2, max_length=120)
    location: str = Field(min_length=2, max_length=300)
    issued_to: str | None = Field(default=None, max_length=160)
    reason: str = Field(min_length=3, max_length=2000)


class ControlledCopyClose(BaseModel):
    disposition: Literal["RETURNED", "DESTROYED"]
    reason: str = Field(min_length=3, max_length=2000)


class RequirementCreate(BaseModel):
    job_role_id: int
    document_family_id: int
    requirement_type: Literal[
        "READ_UNDERSTAND",
        "AWARENESS",
        "REFERENCE_ONLY",
        "CONTROLLED_COPY",
    ] = "READ_UNDERSTAND"
    due_days: int | None = Field(default=None, ge=0, le=3650)
    reason: str = Field(min_length=3, max_length=2000)


class RequirementUpdate(BaseModel):
    requirement_type: (
        Literal[
            "READ_UNDERSTAND",
            "AWARENESS",
            "REFERENCE_ONLY",
            "CONTROLLED_COPY",
        ]
        | None
    ) = None
    due_days: int | None = Field(default=None, ge=0, le=3650)
    is_active: bool | None = None
    reason: str = Field(min_length=3, max_length=2000)


class AcknowledgeRequest(BaseModel):
    password: str
    statement: str = "I confirm that I have read and understood this document and will comply with its requirements."


class IndividualAssignmentCreate(BaseModel):
    user_id: int
    document_version_id: int
    due_days: int | None = Field(default=None, ge=0, le=3650)
    requirement_type: Literal["READ_UNDERSTAND", "AWARENESS"] = "READ_UNDERSTAND"
    reason: str = Field(min_length=3, max_length=2000)


class AssignmentClosure(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class SettingsPatch(BaseModel):
    values: dict[str, str]
    reason: str = Field(min_length=3, max_length=2000)


class NotificationSettingsUpdate(BaseModel):
    enabled: bool
    smtp_host: str = Field(max_length=255)
    smtp_port: int = Field(ge=1, le=65535)
    smtp_security: Literal["STARTTLS", "SSL", "NONE"]
    smtp_username: str = Field(max_length=255)
    smtp_password: str | None = Field(default=None, max_length=500)
    clear_smtp_password: bool = False
    sender_name: str = Field(min_length=1, max_length=160)
    sender_email: str = Field(max_length=254)
    overdue_frequency_days: int = Field(ge=1, le=90)
    reason: str = Field(min_length=3, max_length=2000)


class NotificationTestRequest(BaseModel):
    recipient_email: str = Field(min_length=3, max_length=254)


class BackupCreateRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class RestoreRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=500)
    confirmation: str
    reason: str = Field(min_length=3, max_length=2000)


class PaginatedResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
