#!/usr/bin/env python3
"""Bind final confirmation to the selected job and approved career materials."""

import argparse
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


SELECTION_SCHEMA = "fanhan-job-selection-v1"
PROFILE_SCHEMA = "fanhan-career-profile-v1"
PROFILE_STATUS_SCHEMA = "fanhan-profile-status-v1"
PROPOSAL_SCHEMA = "fanhan-tailored-material-v1"


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_path(path, *, outbox=False):
    path = path.resolve()
    parts = path.parts
    if ".fanhan-job-agent" not in parts:
        raise ValueError("career_material_must_be_local")
    if outbox and "outbox" not in parts[parts.index(".fanhan-job-agent") + 1:]:
        raise ValueError("tailored_resume_must_be_in_outbox")
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("career_material_missing")
    return path


def load_json(path, schema):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise ValueError("career_material_missing") from error
    if value.get("schema_version") != schema:
        raise ValueError("career_material_schema_mismatch")
    return value


def load_selection(path, expected):
    path = local_path(path)
    value = load_json(path, SELECTION_SCHEMA)
    if value.get("user_confirmed") is not True:
        raise ValueError("job_selection_missing")
    fields = ("company", "job_title", "job_url", "application_url")
    if any(str(value.get(field) or "").strip() != expected[field] for field in fields):
        raise ValueError("job_selection_mismatch")
    if not str(value.get("selected_at") or "").strip():
        raise ValueError("job_selection_missing")
    return value


def save_selection(args):
    output = args.output.resolve()
    if ".fanhan-job-agent" not in output.parts:
        raise ValueError("selection_must_be_local")
    output.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "schema_version": SELECTION_SCHEMA,
        "company": args.company.strip(),
        "job_title": args.job_title.strip(),
        "job_url": args.job_url.strip(),
        "application_url": args.application_url.strip(),
        "user_confirmed": True,
        "selected_at": datetime.now(timezone.utc).isoformat(),
    }
    if not all(value[field] for field in ("company", "job_title", "job_url", "application_url")):
        raise ValueError("job_selection_incomplete")
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return value


def validate_materials(args, selection):
    profile_path = local_path(args.profile)
    status_path = local_path(args.profile_status)
    career_path = local_path(args.career_document)
    proposal_path = local_path(args.proposal)
    resume_path = local_path(args.resume, outbox=True)

    profile = load_json(profile_path, PROFILE_SCHEMA)
    status = load_json(status_path, PROFILE_STATUS_SCHEMA)
    proposal = load_json(proposal_path, PROPOSAL_SCHEMA)

    if status.get("profile_status") != "可匹配" or status.get("profile_sha256") != file_hash(profile_path):
        raise ValueError("career_profile_not_ready")
    configured_career = Path(str(profile.get("career_document", {}).get("path") or "")).expanduser()
    if not configured_career.is_absolute():
        configured_career = profile_path.parent / configured_career
    if configured_career.resolve() != career_path:
        raise ValueError("career_document_mismatch")
    job = proposal.get("job", {})
    if str(job.get("company") or "").strip() != selection["company"] or str(job.get("title") or "").strip() != selection["job_title"]:
        raise ValueError("tailored_resume_job_mismatch")
    artifact_stem = str(proposal.get("artifact_stem") or "").strip()
    if not artifact_stem or resume_path.stem != artifact_stem:
        raise ValueError("tailored_resume_name_mismatch")
    html_path = resume_path.with_suffix(".html")
    try:
        html_path = local_path(html_path, outbox=True)
    except ValueError as error:
        raise ValueError("editable_html_missing") from error
    page = html_path.read_text(encoding="utf-8")
    if ('contenteditable="true"' not in page
            or not any(f'data-fanhan-resume-editor="v{version}"' in page for version in (2, 3))
            or "html2pdf.bundle.min.js" not in page
            or "resume-editor.js" not in page
            or "window.print()" in page):
        raise ValueError("editable_html_invalid")
    pdf = resume_path.read_bytes()
    if resume_path.suffix.lower() != ".pdf" or not pdf.startswith(b"%PDF-"):
        raise ValueError("tailored_resume_must_be_pdf")
    if b"jsPDF" not in pdf:
        raise ValueError("tailored_resume_must_be_editor_export")
    if resume_path.stat().st_mtime_ns < html_path.stat().st_mtime_ns:
        raise ValueError("pdf_must_be_exported_after_html")
    return {
        "profile_sha256": file_hash(profile_path),
        "profile_status_sha256": file_hash(status_path),
        "career_document_sha256": file_hash(career_path),
        "proposal_sha256": file_hash(proposal_path),
        "html_sha256": file_hash(html_path),
        "html_name": html_path.name,
        "resume_sha256": file_hash(resume_path),
        "resume_name": resume_path.name,
    }


def payload(args):
    current = {
        "company": args.company.strip(),
        "job_title": args.job_title.strip(),
        "job_url": args.job_url.strip(),
        "application_url": args.application_url.strip(),
        "portfolio_sha256": file_hash(args.portfolio) if args.portfolio else "",
        "form_field_names": sorted(set(args.field_name)),
        "final_action": args.final_action.strip(),
    }
    selection = load_selection(args.selection, current)
    current.update(validate_materials(args, selection))
    current["selected_at"] = selection["selected_at"]
    return current


def fingerprint(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def self_test():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        local = root / ".fanhan-job-agent"
        outbox = local / "outbox"
        outbox.mkdir(parents=True)
        career = local / "职业经历.md"
        career.write_text("# 职业经历\n", encoding="utf-8")
        profile = local / "profile.json"
        profile.write_text(json.dumps({
            "schema_version": PROFILE_SCHEMA,
            "identity": {"name": "张三"},
            "career_document": {"path": "职业经历.md"},
        }, ensure_ascii=False), encoding="utf-8")
        status = local / "profile-status.json"
        status.write_text(json.dumps({
            "schema_version": PROFILE_STATUS_SCHEMA,
            "profile_status": "可匹配",
            "profile_sha256": file_hash(profile),
        }, ensure_ascii=False), encoding="utf-8")
        proposal = local / "tailored-proposal.json"
        proposal.write_text(json.dumps({
            "schema_version": PROPOSAL_SCHEMA,
            "job": {"id": "job-1", "company": "Example", "title": "Engineer"},
            "artifact_stem": "张三-Example-Engineer-20260818-v1",
        }, ensure_ascii=False), encoding="utf-8")
        resume = outbox / "张三-Example-Engineer-20260818-v1.pdf"
        resume.write_bytes(b"%PDF-1.4 jsPDF tailored")
        selection_path = local / "selected-external-job.json"
        selection_args = SimpleNamespace(
            company="Example", job_title="Engineer", job_url="https://jobradar.cc/jobs/1",
            application_url="https://example.com/apply/1", output=selection_path,
        )
        selection = save_selection(selection_args)
        args = SimpleNamespace(
            company="Example", job_title="Engineer", job_url="https://jobradar.cc/jobs/1",
            application_url="https://example.com/apply/1", selection=selection_path,
            profile=profile, profile_status=status, career_document=career, proposal=proposal,
            resume=resume, portfolio=None, field_name=["email"], final_action="Submit",
        )
        try:
            payload(args)
            raise AssertionError("只有 PDF、没有同名可编辑 HTML 时必须失败")
        except ValueError as error:
            assert str(error) == "editable_html_missing"
        editable_html = resume.with_suffix(".html")
        editable_html.write_text(
            '<body data-fanhan-resume-editor="v2"><main contenteditable="true"></main>'
            '<script src="html2pdf.bundle.min.js"></script><script src="resume-editor.js"></script></body>',
            encoding="utf-8",
        )
        resume.write_bytes(b"%PDF-1.4 jsPDF tailored")
        value = payload(args)
        first = fingerprint(value)
        assert value["resume_name"] == resume.name
        assert value["html_name"] == editable_html.name
        assert first == fingerprint(dict(value))
        resume.write_bytes(b"%PDF-1.4 jsPDF tailored-v2")
        assert first != fingerprint(payload(args))
        resume.write_bytes(b"%PDF-1.4 HeadlessChrome Skia/PDF")
        try:
            payload(args)
            raise AssertionError("regenerated PDF must fail")
        except ValueError as error:
            assert str(error) == "tailored_resume_must_be_editor_export"
        resume.write_bytes(b"%PDF-1.4 jsPDF tailored-v2")
        expected = {field: value[field] for field in ("company", "job_title", "job_url", "application_url")}
        assert load_selection(selection_path, expected)["user_confirmed"] is True
        try:
            load_selection(selection_path, dict(expected, job_title="Wrong role"))
            raise AssertionError("mismatched selected job must fail")
        except ValueError as error:
            assert str(error) == "job_selection_mismatch"
        old_resume = root / "Rokid旧简历.pdf"
        old_resume.write_bytes(b"%PDF-original")
        args.resume = old_resume
        try:
            payload(args)
            raise AssertionError("original resume must not pass the tailored resume gate")
        except ValueError as error:
            assert str(error) in {"career_material_must_be_local", "tailored_resume_must_be_in_outbox"}
    print("confirmation_gate self-test: ok")


def build_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    select = subparsers.add_parser("select")
    select.add_argument("--company", required=True)
    select.add_argument("--job-title", required=True)
    select.add_argument("--job-url", required=True)
    select.add_argument("--application-url", required=True)
    select.add_argument("--output", required=True, type=Path)
    select.add_argument("--confirmed", action="store_true", required=True)
    for command in ("build", "verify"):
        child = subparsers.add_parser(command)
        child.add_argument("--company", required=True)
        child.add_argument("--job-title", required=True)
        child.add_argument("--job-url", required=True)
        child.add_argument("--application-url", required=True)
        child.add_argument("--profile", required=True, type=Path)
        child.add_argument("--profile-status", required=True, type=Path)
        child.add_argument("--career-document", required=True, type=Path)
        child.add_argument("--proposal", required=True, type=Path)
        child.add_argument("--resume", required=True, type=Path)
        child.add_argument("--portfolio", type=Path)
        child.add_argument("--field-name", action="append", default=[])
        child.add_argument("--final-action", required=True)
        child.add_argument("--selection", required=True, type=Path)
        if command == "verify":
            child.add_argument("--expected", required=True)
    subparsers.add_parser("self-test")
    return parser


def main():
    args = build_parser().parse_args()
    if args.command == "self-test":
        self_test()
        return
    if args.command == "select":
        print(json.dumps(save_selection(args), ensure_ascii=False, indent=2))
        return
    current = payload(args)
    current_fingerprint = fingerprint(current)
    if args.command == "verify" and current_fingerprint != args.expected:
        print("confirmation_stale")
        raise SystemExit(2)
    print(json.dumps({"fingerprint": current_fingerprint, "summary": current}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
