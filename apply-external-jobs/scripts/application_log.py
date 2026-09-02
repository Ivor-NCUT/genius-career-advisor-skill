#!/usr/bin/env python3
"""Write and query the V1 non-sensitive external application log."""

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

FIELDS = (
    "timestamp", "source", "company", "job_title", "job_url",
    "application_url", "status", "user_confirmed", "success_evidence", "reason",
)
STATUSES = {"skipped", "awaiting_confirmation", "user_declined", "success", "failed"}
OUTCOME_FIELDS = ("timestamp", "company", "job_title", "job_url", "status", "evidence")
OUTCOME_STATUSES = {"applied", "interview", "rejected", "offer", "withdrawn", "follow_up_sent"}


def normalize_url(value):
    if not value:
        return ""
    parts = urlsplit(value.strip())
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_")))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


def parse_bool(value):
    lowered = value.lower()
    if lowered not in {"true", "false"}:
        raise ValueError("user_confirmed must be true or false")
    return lowered == "true"


def validate_record(record):
    if set(record) != set(FIELDS):
        raise ValueError("record fields do not match the V1 schema")
    if any(not isinstance(record[name], str) for name in FIELDS if name != "user_confirmed"):
        raise ValueError("all text fields must be strings")
    if not isinstance(record["user_confirmed"], bool):
        raise ValueError("user_confirmed must be boolean")
    if not record["source"].strip() or not record["company"].strip() or not record["job_title"].strip():
        raise ValueError("source, company, and job title are required")
    if not record["job_url"] and not record["application_url"]:
        raise ValueError("a job or application URL is required")
    if record["status"] not in STATUSES:
        raise ValueError("invalid status")
    if any("\n" in record[name] or len(record[name]) > 500 for name in FIELDS if name != "user_confirmed"):
        raise ValueError("text fields must be one line and at most 500 characters")
    if record["status"] == "success" and (not record["user_confirmed"] or not record["success_evidence"]):
        raise ValueError("success requires confirmation and explicit evidence")
    if record["status"] == "user_declined" and (record["user_confirmed"] or record["success_evidence"]):
        raise ValueError("user_declined cannot be confirmed or successful")
    if record["status"] == "awaiting_confirmation" and (record["user_confirmed"] or record["success_evidence"]):
        raise ValueError("awaiting_confirmation cannot be confirmed or successful")
    if record["status"] in {"skipped", "failed"} and not record["reason"]:
        raise ValueError("skipped and failed records require a reason")


def read_records(path):
    if not path.exists():
        return []
    # ponytail: linear scan is enough for a local V1 log; add an index only after measured slowdown.
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            validate_record(record)
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"invalid log line {number}: {error}") from error
        records.append(record)
    return records


def append_record(path, record):
    validate_record(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def append_outcome(path, outcome):
    if set(outcome) != set(OUTCOME_FIELDS) or outcome["status"] not in OUTCOME_STATUSES:
        raise ValueError("invalid outcome")
    if not all(isinstance(outcome[name], str) and outcome[name].strip() for name in OUTCOME_FIELDS):
        raise ValueError("outcome fields must be non-empty strings")
    if any("\n" in outcome[name] or len(outcome[name]) > 500 for name in OUTCOME_FIELDS):
        raise ValueError("outcome fields must be one line and at most 500 characters")
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    if outcome["status"] == "follow_up_sent":
        normalized = normalize_url(outcome["job_url"])
        follow_ups = sum(
            1 for line in existing
            if (item := json.loads(line)).get("status") == "follow_up_sent"
            and normalize_url(item.get("job_url", "")) == normalized
        )
        if follow_ups >= 2:
            raise ValueError("a job can have at most two recorded follow-ups")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(outcome, ensure_ascii=False, separators=(",", ":")) + "\n")


def is_duplicate(records, job_url, application_url):
    targets = {normalize_url(job_url), normalize_url(application_url)} - {""}
    return any(
        record["status"] == "success"
        and bool(targets & {normalize_url(record["job_url"]), normalize_url(record["application_url"])})
        for record in records
    )


def make_record(args):
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": args.source,
        "company": args.company,
        "job_title": args.job_title,
        "job_url": normalize_url(args.job_url),
        "application_url": normalize_url(args.application_url),
        "status": args.status,
        "user_confirmed": parse_bool(args.user_confirmed),
        "success_evidence": args.success_evidence,
        "reason": args.reason,
    }


def self_test():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "applications.jsonl"
        base = {
            "timestamp": "2026-08-16T00:00:00+00:00", "source": "JobRadar",
            "company": "Example", "job_title": "Engineer",
            "job_url": "https://jobradar.cc/jobs/1", "application_url": "https://example.com/apply/1",
            "status": "success", "user_confirmed": True,
            "success_evidence": "Application received", "reason": "",
        }
        append_record(path, base)
        records = read_records(path)
        assert is_duplicate(records, "https://jobradar.cc/jobs/1?utm_source=test", "")
        declined = dict(
            base, source="Bonjour", status="user_declined",
            user_confirmed=False, success_evidence="", reason="user_declined",
        )
        append_record(path, declined)
        assert read_records(path)[1]["source"] == "Bonjour"
        try:
            validate_record(dict(base, user_confirmed=False))
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe success record was accepted")
        outcomes = Path(directory) / "application-outcomes.jsonl"
        outcome = {
            "timestamp": "2026-08-16T00:00:00+00:00", "company": "Example",
            "job_title": "Engineer", "job_url": "https://example.com/jobs/1",
            "status": "follow_up_sent", "evidence": "candidate confirmed",
        }
        append_outcome(outcomes, outcome)
        append_outcome(outcomes, dict(outcome, timestamp="2026-08-17T00:00:00+00:00"))
        try:
            append_outcome(outcomes, dict(outcome, timestamp="2026-08-18T00:00:00+00:00"))
        except ValueError:
            pass
        else:
            raise AssertionError("third follow-up was accepted")
    print("application_log self-test: ok")


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=Path(".fanhan-job-agent/external-applications.jsonl"))
    parser.add_argument("--outcome-path", type=Path, default=Path(".fanhan-job-agent/application-outcomes.jsonl"))
    subparsers = parser.add_subparsers(dest="command", required=True)
    append = subparsers.add_parser("append")
    append.add_argument("--source", required=True)
    for flag in ("company", "job-title", "job-url", "application-url", "status", "user-confirmed"):
        append.add_argument(f"--{flag}", required=True)
    append.add_argument("--success-evidence", default="")
    append.add_argument("--reason", default="")
    duplicate = subparsers.add_parser("duplicate")
    duplicate.add_argument("--job-url", default="")
    duplicate.add_argument("--application-url", default="")
    outcome = subparsers.add_parser("outcome")
    for flag in ("company", "job-title", "job-url", "status", "evidence"):
        outcome.add_argument(f"--{flag}", required=True)
    subparsers.add_parser("validate")
    subparsers.add_parser("self-test")
    return parser


def main():
    args = build_parser().parse_args()
    if args.command == "self-test":
        self_test()
    elif args.command == "append":
        append_record(args.path, make_record(args))
        print("recorded")
    elif args.command == "duplicate":
        duplicate = is_duplicate(read_records(args.path), args.job_url, args.application_url)
        print("duplicate" if duplicate else "new")
        raise SystemExit(10 if duplicate else 0)
    elif args.command == "outcome":
        append_outcome(args.outcome_path, {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "company": args.company,
            "job_title": args.job_title,
            "job_url": normalize_url(args.job_url),
            "status": args.status,
            "evidence": args.evidence,
        })
        print("outcome recorded")
    else:
        records = read_records(args.path)
        print(f"valid: {len(records)} record(s)")


if __name__ == "__main__":
    main()
