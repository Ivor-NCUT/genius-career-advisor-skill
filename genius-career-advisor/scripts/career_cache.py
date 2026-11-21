#!/usr/bin/env python3
"""Remember official-site reads so a later search can reuse them.

A fresh successful read is returned without using a browser slot. Slots go
first to a company the user named, then to the official sites that have gone
longest without a check. JobRadar and 出海聘 are never stored or read here.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path


TTL = timedelta(hours=24)
RETRY_AFTER = timedelta(hours=2)
TERMINAL_REASONS = {"dead_url", "no_public_jobs", "login_or_restricted"}
SLOW_RETRY_REASONS = {"network_error", "page_not_ready", "parser_gap"}
REASONS = TERMINAL_REASONS | SLOW_RETRY_REASONS | {
    "not_browser_checked",
    "collected_no_match",
}


def cache_path(catalog_path: Path | None = None) -> Path:
    if catalog_path:
        return catalog_path.parent / "career-read-cache.json"
    return Path(__file__).resolve().parents[1] / "data" / "career-read-cache.json"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime | None = None) -> str:
    return (moment or now_utc()).replace(microsecond=0).isoformat()


def _parse(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def load(path: Path | None = None) -> dict:
    file_path = path or cache_path()
    if not file_path.exists():
        return {"entries": {}}
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"entries": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), dict):
        return {"entries": {}}
    return payload


def save(payload: dict, path: Path | None = None) -> None:
    file_path = path or cache_path()
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def entry_for(payload: dict, name: str) -> dict | None:
    found = (payload.get("entries") or {}).get(name)
    return found if isinstance(found, dict) else None


def fresh(entry: dict | None, moment: datetime | None = None, ttl: timedelta = TTL) -> bool:
    if not entry:
        return False
    fetched = _parse(str(entry.get("fetched_at") or ""))
    if not fetched:
        return False
    return (moment or now_utc()) - fetched < ttl


def remember(payload: dict, name: str, **fields) -> dict:
    entries = payload.setdefault("entries", {})
    current = dict(entries.get(name) or {})
    current.update(fields)
    current["name"] = name
    current["fetched_at"] = fields.get("fetched_at") or _stamp()
    entries[name] = current
    return current


def classify_failure(error: object) -> str:
    text = str(error or "").casefold()
    if "browser_time_budget" in text or "page_not_ready" in text:
        return "page_not_ready"
    if any(token in text for token in ("timeout", "timed out", "ssl", "handshake", "name or service", "errno", "connection reset", "temporarily", "err_name_not_resolved", "err_connection", "err_cert", "err_ssl", "err_timed_out")):
        return "network_error"
    if any(token in text for token in ("http 404", "http 410", "404", "not found", "dead_url")):
        return "dead_url"
    if any(token in text for token in ("403", "login", "sign in", "验证码", "访问受限", "membership", "登录")):
        return "login_or_restricted"
    if any(token in text for token in ("暂无职位", "暂无招聘", "no open position", "no_public_jobs")):
        return "no_public_jobs"
    if any(token in text for token in ("parser_gap", "no_readable_rendered")):
        return "parser_gap"
    if any(token in text for token in ("unreadable_page", "no_public_job_list")):
        return "not_browser_checked"
    if "not_browser_checked" in text:
        return "not_browser_checked"
    return "not_browser_checked"


def company_named(record: dict, query: str) -> bool:
    folded = str(query or "").casefold()
    if not folded:
        return False
    for part in re.split(r"[\s/·|]+", str(record.get("name") or "")):
        if len(part) >= 2 and part.casefold() in folded:
            return True
    return False


def _eligible(entry: dict | None, moment: datetime, named: bool) -> bool:
    if named:
        return True
    if not entry or not fresh(entry, moment):
        return True
    if entry.get("jobs"):
        return False
    reason = str(entry.get("failure_reason") or "")
    fetched = _parse(str(entry.get("fetched_at") or ""))
    if not fetched:
        return True
    age = moment - fetched
    if reason in TERMINAL_REASONS and age < TTL:
        return False
    if reason in SLOW_RETRY_REASONS and age < RETRY_AFTER:
        return False
    return True


def pick_browser_targets(records: list[dict], cache: dict, query: str, limit: int, moment: datetime | None = None) -> list[dict]:
    """Choose official sites for the bounded browser fallback."""
    moment = moment or now_utc()
    ranked = []
    for record in records:
        name = str(record.get("name") or "")
        entry = entry_for(cache, name)
        named = company_named(record, query)
        if not _eligible(entry, moment, named):
            continue
        fetched = str((entry or {}).get("fetched_at") or "")
        ranked.append((0 if named else 1, fetched, name, record))
    ranked.sort()
    return [record for _named, _fetched, _name, record in ranked[: max(0, limit)]]
