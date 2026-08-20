"""Durable, redacted receipts for profile-settings write runs.

This module deliberately owns no device I/O.  Its only responsibility is to
persist a constrained audit/recovery record *before* the caller performs a
device effect, and to append bounded state transitions afterwards.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_PROFILE_RUN_RECEIPT_ROOT = Path("/var/lib/magewell-profile-run-receipts")
MAX_RECEIPT_BYTES = 64 * 1024
MAX_RECEIPT_STORAGE_BYTES = 10 * 1024 * 1024
MAX_RECEIPT_RECORDS = 10_000
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RECEIPT_ID_RE = re.compile(r"^[a-f0-9]{32}$")
FORBIDDEN_RECEIPT_KEYS = {
    "settings",
    "password",
    "passwd",
    "credential",
    "credentials",
    "cookie",
    "cookies",
    "header",
    "headers",
    "url",
    "urls",
    "response",
    "responses",
    "query",
    "error",
    "errors",
}


class ReceiptSafetyError(RuntimeError):
    """Raised when a receipt cannot be safely reserved or persisted."""


def canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def receipt_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _assert_redacted(value: Any) -> None:
    """Reject raw device data even if a future caller bypasses the app builder."""
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in FORBIDDEN_RECEIPT_KEYS or (
                "settings" in normalized and not normalized.endswith("sha256")
            ):
                raise ReceiptSafetyError("Profile-run receipt contains forbidden sensitive data.")
            _assert_redacted(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_redacted(nested)


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    _fsync_directory(path)


def get_profile_run_receipt_root() -> Path:
    configured = os.getenv("PROFILE_RUN_RECEIPT_ROOT")
    return Path(configured) if configured else DEFAULT_PROFILE_RUN_RECEIPT_ROOT


def _validated_root(root: Path) -> Path:
    resolved = root.resolve()
    if (
        not resolved.is_absolute()
        or resolved == REPOSITORY_ROOT
        or REPOSITORY_ROOT in resolved.parents
    ):
        raise ReceiptSafetyError("Profile-run receipts must use an absolute non-repository path.")
    return resolved


def _safe_receipt_id(receipt_id: str) -> str:
    if not RECEIPT_ID_RE.fullmatch(receipt_id):
        raise ReceiptSafetyError("Profile-run receipt identity is invalid.")
    return receipt_id


def _utc_month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ProfileRunReceiptStore:
    """Append-only monthly receipt journal and atomic latest-state summaries."""

    # Stores are constructed per request; this lock serializes every local writer in the
    # backend process so capacity reservations cannot race terminal event recording.
    _writer_lock = threading.RLock()

    def __init__(self, root: Path | None = None) -> None:
        self.root = _validated_root(root or get_profile_run_receipt_root())

    @property
    def journal_dir(self) -> Path:
        return self.root / "journal"

    @property
    def current_dir(self) -> Path:
        return self.root / "current"

    @property
    def reservation_dir(self) -> Path:
        return self.root / "reservations"

    def _prepare(self) -> None:
        _private_directory(self.root)
        _private_directory(self.journal_dir)
        _private_directory(self.current_dir)
        _private_directory(self.reservation_dir)

    def _journal_path(self, month: str) -> Path:
        if not re.fullmatch(r"\d{4}-\d{2}", month):
            raise ReceiptSafetyError("Profile-run receipt month is invalid.")
        return self.journal_dir / f"receipts-{month}.jsonl"

    def _summary_path(self, receipt_id: str) -> Path:
        return self.current_dir / f"{_safe_receipt_id(receipt_id)}.json"

    def _reservation_path(self, receipt_id: str) -> Path:
        return self.reservation_dir / f"{_safe_receipt_id(receipt_id)}.json"

    def _storage_usage(self) -> tuple[int, int]:
        if not self.root.exists():
            return 0, 0
        total_bytes = 0
        journal_records = 0
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            total_bytes += path.stat().st_size
            if path.parent == self.journal_dir and path.suffix == ".jsonl":
                with path.open("rb") as entries:
                    journal_records += sum(1 for line in entries if line.strip())
        return total_bytes, journal_records

    def _pending_reservation_totals(self) -> tuple[int, int]:
        if not self.reservation_dir.exists():
            return 0, 0
        bytes_reserved = 0
        records_reserved = 0
        for path in self.reservation_dir.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                receipt_id = _safe_receipt_id(str(payload["receipt_id"]))
                if path != self._reservation_path(receipt_id):
                    raise ValueError("reservation identity mismatch")
                reserved_bytes = int(payload["reserved_bytes"])
                reserved_records = int(payload["reserved_records"])
                if reserved_bytes < 1 or reserved_records < 1:
                    raise ValueError("reservation bounds")
            except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
                raise ReceiptSafetyError(
                    "Profile-run receipt reservations are unreadable; no device write was started."
                ) from exc
            bytes_reserved += reserved_bytes
            records_reserved += reserved_records
        return bytes_reserved, records_reserved

    def _ensure_reservation(self, *, bytes_required: int, records_required: int) -> None:
        current_bytes, current_records = self._storage_usage()
        pending_bytes, pending_records = self._pending_reservation_totals()
        if current_bytes + pending_bytes + bytes_required > MAX_RECEIPT_STORAGE_BYTES:
            raise ReceiptSafetyError(
                "Profile-run receipt storage is full; no device write was started."
            )
        if current_records + pending_records + records_required > MAX_RECEIPT_RECORDS:
            raise ReceiptSafetyError(
                "Profile-run receipt journal is full; no device write was started."
            )

    @staticmethod
    def _event(payload: dict[str, Any], event: str) -> dict[str, Any]:
        _assert_redacted(payload)
        event_payload = {**payload, "event": event, "recorded_at": _utc_timestamp()}
        event_payload["receipt_sha256"] = receipt_sha256(event_payload)
        encoded = canonical_json(event_payload)
        if len(encoded) > MAX_RECEIPT_BYTES:
            raise ReceiptSafetyError("Profile-run receipt exceeds the 64 KiB safety limit.")
        return event_payload

    def _append_event(self, payload: dict[str, Any], event: str) -> dict[str, Any]:
        event_payload = self._event(payload, event)
        journal_path = self._journal_path(_utc_month())
        fd = os.open(journal_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "wb") as journal:
            journal.write(canonical_json(event_payload) + b"\n")
            journal.flush()
            os.fsync(journal.fileno())
        os.chmod(journal_path, 0o600)
        _fsync_directory(self.journal_dir)
        return event_payload

    def _write_current(self, payload: dict[str, Any]) -> None:
        path = self._summary_path(str(payload["receipt_id"]))
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(canonical_json(payload) + b"\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            os.chmod(path, 0o600)
            _fsync_directory(self.current_dir)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _write_reservation(self, receipt_id: str) -> None:
        path = self._reservation_path(receipt_id)
        payload = {
            "receipt_id": receipt_id,
            "reserved_bytes": MAX_RECEIPT_BYTES * 2,
            "reserved_records": 1,
        }
        encoded = canonical_json(payload) + b"\n"
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            os.chmod(path, 0o600)
            _fsync_directory(self.reservation_dir)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _require_reservation(self, receipt_id: str) -> None:
        path = self._reservation_path(receipt_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                payload.get("receipt_id") != receipt_id
                or payload.get("reserved_bytes") != MAX_RECEIPT_BYTES * 2
                or payload.get("reserved_records") != 1
            ):
                raise ValueError("invalid reservation")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ReceiptSafetyError(
                "Profile-run receipt terminal capacity is not reserved; stop and inspect devices."
            ) from exc

    def _consume_reservation(self, receipt_id: str) -> None:
        path = self._reservation_path(receipt_id)
        try:
            path.unlink()
            _fsync_directory(self.reservation_dir)
        except OSError:
            # A leaked reservation is conservative: it can only reduce future capacity.
            pass

    def reserve_and_record_intent(self, receipt: dict[str, Any]) -> dict[str, Any]:
        """Reserve two journal slots before the caller may send a device mutation."""
        receipt_id = _safe_receipt_id(str(receipt.get("receipt_id", "")))
        with self._writer_lock:
            self._prepare()
            # Reserve intent/current-summary plus terminal/current-summary before any effect.
            self._ensure_reservation(bytes_required=MAX_RECEIPT_BYTES * 4, records_required=2)
            intent = {**receipt, "run_state": "intent-recorded"}
            self._append_event(intent, "pre-effect-intent")
            self._write_current(intent)
            self._write_reservation(receipt_id)
            return intent

    def record_mutation_outcomes(
        self, receipt: dict[str, Any], targets: list[dict[str, Any]]
    ) -> dict[str, Any]:
        receipt_id = _safe_receipt_id(str(receipt.get("receipt_id", "")))
        with self._writer_lock:
            self._prepare()
            self._require_reservation(receipt_id)
            updated = {**receipt, "run_state": "mutation-finished", "targets": targets}
            self._append_event(updated, "mutation-outcomes")
            self._write_current(updated)
            self._consume_reservation(receipt_id)
            return updated

    def record_verification_outcome(
        self,
        receipt_id: str,
        *,
        ip: str,
        magewell_id: str,
        verification: dict[str, Any],
    ) -> dict[str, Any]:
        with self._writer_lock:
            current = self.get_receipt(receipt_id)
            self._ensure_reservation(bytes_required=MAX_RECEIPT_BYTES * 2, records_required=1)
            targets = list(current["targets"])
            for target in targets:
                if target.get("ip") == ip and target.get("magewell_id") == magewell_id:
                    target["verification"] = verification
                    target["risk_state"] = (
                        "verified"
                        if verification["status"] == "verified"
                        else "uncertain-high-risk"
                    )
                    break
            else:
                raise ReceiptSafetyError(
                    "Verification target does not match the durable profile-run receipt."
                )
            updated = {**current, "run_state": "verification-recorded", "targets": targets}
            self._append_event(updated, "verification-outcome")
            self._write_current(updated)
            return updated

    def get_receipt(self, receipt_id: str) -> dict[str, Any]:
        path = self._summary_path(receipt_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ReceiptSafetyError("Profile-run receipt was not found.") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ReceiptSafetyError(
                "Profile-run receipt is unreadable; stop and inspect durable storage."
            ) from exc
        if not isinstance(payload, dict) or payload.get("receipt_id") != receipt_id:
            raise ReceiptSafetyError("Profile-run receipt identity is invalid.")
        _assert_redacted(payload)
        return payload

    def list_receipts(self) -> list[dict[str, Any]]:
        if not self.current_dir.exists():
            return []
        receipts = []
        for path in self.current_dir.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and RECEIPT_ID_RE.fullmatch(
                str(payload.get("receipt_id", ""))
            ):
                _assert_redacted(payload)
                receipts.append(payload)
        return sorted(receipts, key=lambda item: str(item.get("created_at", "")), reverse=True)

    def export_manifest(self) -> dict[str, Any]:
        if not self.journal_dir.exists():
            return {"media_type": "application/x-ndjson", "segments": [], "receipt_record_count": 0}
        segments = []
        total_records = 0
        for path in sorted(self.journal_dir.glob("receipts-*.jsonl")):
            data = path.read_bytes()
            count = sum(1 for line in data.splitlines() if line.strip())
            total_records += count
            segments.append(
                {
                    "name": path.name,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size_bytes": len(data),
                    "receipt_record_count": count,
                }
            )
        return {
            "media_type": "application/x-ndjson",
            "segments": segments,
            "receipt_record_count": total_records,
        }
