"""Minimal JSONL audit logging for safe workflow metadata."""

import json
from pathlib import Path
from typing import Any


_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "access_token",
    "token",
    "secret",
    "password",
    "clinical_note",
    "clinicalnote",
    "note_text",
    "raw_text",
)


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _safe_value(value: Any, key: object | None = None) -> Any:
    if key is not None and _is_sensitive_key(key):
        return None
    if isinstance(value, dict):
        return {
            str(child_key): safe_value
            for child_key, child_value in value.items()
            if not _is_sensitive_key(child_key)
            for safe_value in [_safe_value(child_value, child_key)]
            if safe_value is not None
        }
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    return value


class AuditLogger:
    """Append and read safe, one-record-per-line audit metadata."""

    def __init__(self, path: str = "data/audit_log.jsonl") -> None:
        self.path = Path(path)

    def append(self, record: dict) -> None:
        """Append one redacted JSON record and flush it to disk."""

        safe_record = {
            key: _safe_value(value, key)
            for key, value in record.items()
            if key in {"ts", "case_id", "event", "details"}
            and not _is_sensitive_key(key)
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as audit_file:
            audit_file.write(json.dumps(safe_record, ensure_ascii=False) + "\n")
            audit_file.flush()

    def read(self, limit: int | None = None) -> list[dict]:
        """Read audit records in order, optionally returning only the last ones."""

        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as audit_file:
            records = [json.loads(line) for line in audit_file if line.strip()]
        if limit is None:
            return records
        if limit <= 0:
            return []
        return records[-limit:]
