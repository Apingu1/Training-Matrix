from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_ROOT = Path(tempfile.mkdtemp(prefix="eaststone-training-matrix-tests-"))
DOCUMENT_ROOT = TEST_ROOT / "documents"
DOCUMENT_ROOT.mkdir(parents=True)

os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": f"sqlite:///{TEST_ROOT / 'training-matrix.db'}",
        "JWT_SECRET": "testing-secret-that-is-longer-than-thirty-two-characters",
        "INITIAL_ADMIN_USERNAME": "admin",
        "INITIAL_ADMIN_PASSWORD": "Initial-Admin-Password1!",
        "DOCUMENT_ROOT": str(DOCUMENT_ROOT),
        "BACKUP_ROOT": str(TEST_ROOT / "backups"),
        "DOCUMENT_CACHE_ROOT": str(TEST_ROOT / "cache"),
        "RUNTIME_ROOT": str(TEST_ROOT / "runtime"),
    }
)

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def helpers():
    def login(client: TestClient, username: str, password: str) -> str:
        response = client.post("/api/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200, response.text
        return response.json()["access_token"]

    def change_password(client: TestClient, token: str, current: str, new: str) -> None:
        response = client.post(
            "/api/auth/change-password",
            headers=auth_header(token),
            json={"current_password": current, "new_password": new},
        )
        assert response.status_code == 200, response.text

    return {"login": login, "change_password": change_password, "headers": auth_header}
