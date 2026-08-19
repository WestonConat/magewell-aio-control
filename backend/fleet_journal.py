"""Versioned immutable identity journal for the Magewell fleet."""

import csv
import hashlib
import re
from functools import lru_cache
from pathlib import Path

JOURNAL_PATH = Path(__file__).with_name("fleet_journal.csv")
FLEET_ID_RE = re.compile(r"AIO-(\d{2})$")
MAC_RE = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}$")


@lru_cache(maxsize=1)
def load_fleet_journal() -> dict[tuple[str, str], str]:
    records: dict[tuple[str, str], str] = {}
    with JOURNAL_PATH.open(newline="", encoding="utf-8") as journal_file:
        for line_number, row in enumerate(csv.DictReader(journal_file), start=2):
            fleet_id = (row.get("fleet_id") or "").strip()
            serial = (row.get("serial") or "").strip()
            mac = (row.get("eth_mac") or "").strip().lower()
            if not FLEET_ID_RE.fullmatch(fleet_id) or not serial or not MAC_RE.fullmatch(mac):
                raise RuntimeError(f"Invalid fleet journal row {line_number}.")
            key = (serial, mac)
            if key in records or fleet_id in records.values():
                raise RuntimeError(f"Duplicate fleet identity or ID on journal row {line_number}.")
            records[key] = fleet_id
    if not records:
        raise RuntimeError("Fleet journal has no records.")
    return records


def journal_sha256() -> str:
    return hashlib.sha256(JOURNAL_PATH.read_bytes()).hexdigest()


def find_fleet_id(serial: str, eth_mac: str) -> str | None:
    return load_fleet_journal().get((serial.strip(), eth_mac.strip().lower()))


def fleet_number(fleet_id: str) -> str:
    match = FLEET_ID_RE.fullmatch(fleet_id)
    if not match:
        raise ValueError("Fleet ID is invalid.")
    return match.group(1)


def required_name(prefix: str, fleet_id: str) -> str:
    clean_prefix = prefix.strip()
    if not clean_prefix:
        raise ValueError("Prefix cannot be empty.")
    return f"{clean_prefix}-{fleet_number(fleet_id)}"


def name_matches_fleet_id(name: str, fleet_id: str) -> bool:
    return name.endswith(f"-{fleet_number(fleet_id)}")


def current_name_matches_fleet_id(name: str, fleet_id: str) -> bool:
    """Recognize the authoritative AIO-NN token in a legacy device name."""
    token = re.escape(fleet_id)
    return re.search(rf"(?<![A-Za-z0-9]){token}(?!\d)", name, flags=re.IGNORECASE) is not None
