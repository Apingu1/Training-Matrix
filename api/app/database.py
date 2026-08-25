from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


class DatabaseRuntime:
    """Thread-safe database binding that supports validated dataset activation."""

    DATASET_PATTERN = re.compile(r"^training_[A-Za-z0-9_]+$")

    def __init__(self, url: str, runtime_root: Path):
        self._base_url = url
        self._runtime_file = runtime_root / "active_dataset.json"
        self._lock = threading.RLock()
        active = self._read_active_dataset()
        self._url = self.url_for_database(active) if active else url
        self._bind(self._url)

    def _connect_args(self, url: str) -> dict:
        return {"check_same_thread": False} if url.startswith("sqlite") else {}

    def _bind(self, url: str) -> None:
        self.engine = create_engine(
            url,
            pool_pre_ping=True,
            future=True,
            connect_args=self._connect_args(url),
        )
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=Session,
        )

    def _read_active_dataset(self) -> str | None:
        try:
            payload = json.loads(self._runtime_file.read_text(encoding="utf-8"))
            name = str(payload.get("db_name", ""))
            return name if self.DATASET_PATTERN.fullmatch(name) else None
        except (FileNotFoundError, ValueError, OSError):
            return None

    @property
    def url(self) -> str:
        return self._url

    @property
    def database_name(self) -> str:
        if self._url.startswith("sqlite"):
            return Path(urlparse(self._url).path).name
        return urlparse(self._url).path.lstrip("/")

    def url_for_database(self, name: str) -> str:
        if not self.DATASET_PATTERN.fullmatch(name):
            raise ValueError("Dataset names must start with training_ and use letters, numbers or underscores")
        parsed = urlparse(self._base_url)
        return urlunparse(parsed._replace(path=f"/{name}"))

    def session(self) -> Session:
        with self._lock:
            return self.session_factory()

    def refresh_from_runtime_file(self) -> None:
        """Follow a staged-restore activation performed by another process."""
        active = self._read_active_dataset()
        desired_url = self.url_for_database(active) if active else self._base_url
        with self._lock:
            if desired_url == self._url:
                return
            old_engine = self.engine
            self._url = desired_url
            self._bind(desired_url)
            old_engine.dispose()

    def activate(self, name: str, *, set_by: str) -> None:
        new_url = self.url_for_database(name)
        with self._lock:
            old_engine = self.engine
            self._url = new_url
            self._bind(new_url)
            self._runtime_file.write_text(
                json.dumps({"db_name": name, "set_by": set_by}, indent=2),
                encoding="utf-8",
            )
            old_engine.dispose()


runtime = DatabaseRuntime(settings.database_url, settings.runtime_root)


def get_db():
    db = runtime.session()
    try:
        yield db
    finally:
        db.close()
