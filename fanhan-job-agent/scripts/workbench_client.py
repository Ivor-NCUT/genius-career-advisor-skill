#!/usr/bin/env python3
"""Preview, authorize and idempotently submit a PDF to Fanhan Workbench."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from profile_status import evaluate as profile_evaluate


SCHEMA = "fanhan-workbench-submission-v2"
CONSENT_VERSION = "fanhan-candidate-materials-v1"
AUTHORIZATION_TEXT = (
    "我同意将上述求职资料提交给泛函，用于候选人档案管理、岗位匹配和招聘团队人工审核。"
    "资料将保存于泛函招聘工作台，并可能通过泛函内部飞书招聘话题群通知招聘团队。"
    "我可以申请停止推荐或删除档案。"
)
MAX_PDF_BYTES = 10 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} 必须是 JSON 对象")
    return value


def save_private(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def resume_path(profile: dict, profile_path: Path) -> Path:
    value = str(profile.get("application_resume", {}).get("path") or "").strip()
    if not value:
        raise ValueError("profile.application_resume.path 不能为空；禁止上传原始简历")
    path = Path(value).expanduser()
    return (path if path.is_absolute() else profile_path.parent / path).resolve()


def validate_pdf(path: Path) -> tuple[str, int]:
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise ValueError("当前工作台只接受存在的 PDF 简历")
    if (path.parent.name != "outbox" or path.parent.parent.name != ".fanhan-job-agent"):
        raise ValueError("岗位专用 PDF 必须来自 .fanhan-job-agent/outbox/")
    html_path = path.with_suffix(".html")
    if not html_path.is_file():
        raise ValueError("缺少同名可编辑 HTML；禁止跳过 HTML 直接上传 PDF")
    page = html_path.read_text(encoding="utf-8")
    if ('contenteditable="true"' not in page
            or not any(f'data-fanhan-resume-editor="v{version}"' in page for version in (2, 3))
            or "html2pdf.bundle.min.js" not in page
            or "resume-editor.js" not in page
            or "window.print()" in page):
        raise ValueError("同名 HTML 不是可编辑、可导出的简历")
    size = path.stat().st_size
    pdf = path.read_bytes()
    if not 0 < size <= MAX_PDF_BYTES or not pdf.startswith(b"%PDF-"):
        raise ValueError("PDF 必须有效且不超过 10 MB")
    if b"jsPDF" not in pdf:
        raise ValueError("PDF 必须由内置 HTML 编辑器导出，禁止重新生成替代文件")
    if path.stat().st_mtime_ns < html_path.stat().st_mtime_ns:
        raise ValueError("PDF 必须由用户在检查 HTML 后导出")
    return sha256(path), size


def validate_state_path(path: Path) -> None:
    if ".fanhan-job-agent" not in path.resolve().parts:
        raise ValueError("提交状态必须保存在 .fanhan-job-agent/ 中")


def confirmed_identity(profile: dict) -> dict:
    name = str(profile.get("identity", {}).get("name") or "").strip()
    contact = profile.get("contact", {})
    email = str(contact.get("email") or "").strip().lower()
    phone = str(contact.get("phone_or_wechat") or "").strip()
    valid_email = bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email))
    valid_phone = phone.lower() not in {"", "unknown", "未知"} and len(phone) >= 5
    if not name or not (valid_email or valid_phone):
        raise ValueError("候选人确认身份必须包含姓名和有效邮箱或联系方式")
    return {
        "candidate_name": name,
        "candidate_email": email if valid_email else "",
        "candidate_phone_or_wechat": phone if valid_phone else "",
    }


def base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
        raise ValueError("工作台地址必须使用 HTTPS；本机测试地址除外")
    if parsed.username or parsed.password or not parsed.netloc:
        raise ValueError("工作台地址无效")
    return value


def prepare(
    profile_path: Path, job_path: Path, introduction_path: Path, state_path: Path,
    service_url: str, portfolio_url: str = "",
) -> dict:
    validate_state_path(state_path)
    profile = load(profile_path)
    if profile.get("schema_version") != "fanhan-career-profile-v1":
        raise ValueError("profile.schema_version 必须是 fanhan-career-profile-v1")
    identity = confirmed_identity(profile)
    job = load(job_path)
    job_id = str(job.get("id") or "").strip()
    job_title = str(job.get("title") or "").strip()
    if not job_id or not job_title:
        raise ValueError("岗位必须包含真实 id 和 title")
    resume = resume_path(profile, profile_path)
    digest, size = validate_pdf(resume)
    introduction = introduction_path.read_text(encoding="utf-8").strip()
    if not 0 < len(introduction) <= 3000:
        raise ValueError("自荐说明必须为 1–3000 个字符")
    if portfolio_url:
        parsed = urlparse(portfolio_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("作品集必须是 HTTP(S) 链接")
    service_url = base_url(service_url)
    signature = hashlib.sha256(json.dumps({
        "service_url": service_url, "job_id": job_id, "resume_sha256": digest,
        "self_introduction": introduction, "portfolio_url": portfolio_url,
        "confirmed_identity": identity,
    }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if state_path.exists():
        state = load(state_path)
        if state.get("schema_version") != SCHEMA or not re.fullmatch(
            r"[A-Za-z0-9._-]{16,120}", str(state.get("client_token") or ""),
        ):
            raise ValueError("已有提交状态无效")
        if state.get("signature") != signature:
            raise ValueError("已有提交状态与本次材料不一致，请使用新的状态文件")
    else:
        state = {
            "schema_version": SCHEMA,
            "signature": signature,
            "service_url": service_url,
            "job_id": job_id,
            "job_title": job_title,
            "resume_path": str(resume),
            "resume_name": resume.name,
            "resume_sha256": digest,
            "resume_size": size,
            "self_introduction": introduction,
            "portfolio_url": portfolio_url,
            **identity,
            "client_token": secrets.token_urlsafe(24),
            "consent_version": CONSENT_VERSION,
            "application": None,
        }
        save_private(state_path, state)
    return {
        "receiver": "泛函招聘工作台",
        "purpose": "候选人档案管理、岗位匹配和招聘团队人工审核",
        "job": {"id": job_id, "title": job_title},
        "resume": {"name": resume.name, "size": size, "sha256": digest},
        "portfolio_included": bool(portfolio_url),
        "self_introduction_characters": len(introduction),
        "confirmed_identity_included": True,
        "authorization_text": AUTHORIZATION_TEXT,
        "network_writes": 0,
    }


def record_consent(profile_path: Path, state_path: Path) -> None:
    validate_state_path(state_path)
    profile = load(profile_path)
    state = load(state_path)
    digest, _ = validate_pdf(resume_path(profile, profile_path))
    identity = confirmed_identity(profile)
    if (state.get("schema_version") != SCHEMA or digest != state.get("resume_sha256")
            or any(state.get(key) != value for key, value in identity.items())):
        raise ValueError("提交状态与当前简历版本不一致")
    profile["consent"] = {
        "confirmed": True,
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
        "material_version": f"sha256:{digest}",
        "idempotency_key": state["client_token"],
        "text_version": CONSENT_VERSION,
    }
    save_private(profile_path, profile)


def authorized(profile: dict, profile_path: Path, state: dict) -> Path:
    resume = resume_path(profile, profile_path)
    digest, _ = validate_pdf(resume)
    consent = profile.get("consent", {})
    expected = {
        "confirmed": True,
        "material_version": f"sha256:{digest}",
        "idempotency_key": state.get("client_token"),
        "text_version": CONSENT_VERSION,
    }
    if any(consent.get(key) != value for key, value in expected.items()) or not consent.get("confirmed_at"):
        raise PermissionError("没有与当前材料绑定的可审计授权；禁止上传")
    if digest != state.get("resume_sha256"):
        raise PermissionError("简历已变化；必须重新预览并授权")
    identity = confirmed_identity(profile)
    if any(state.get(key) != value for key, value in identity.items()):
        raise PermissionError("候选人身份已变化；必须重新预览并授权")
    status = profile_evaluate(profile, profile_path.parent)
    if not status["ingest_ready"]:
        raise ValueError(f"未达到最低入库条件：{status['missing_for_ingest']}")
    return resume


class ApiClient:
    def __init__(self, service_url: str, timeout: int = 30):
        self.service_url = base_url(service_url)
        self.timeout = timeout

    def request(self, path: str, method: str = "GET", body: bytes | None = None, headers: dict | None = None) -> dict:
        request = Request(self.service_url + path, data=body, method=method, headers=headers or {})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                message = json.loads(error.read().decode("utf-8")).get("error")
            except (json.JSONDecodeError, UnicodeDecodeError):
                message = None
            raise RuntimeError(message or f"工作台请求失败：HTTP {error.code}") from error
        except URLError as error:
            raise RuntimeError(f"无法连接工作台：{error.reason}") from error

    def health(self) -> dict:
        return self.request("/healthz")

    def upload(self, resume: Path) -> dict:
        return self.request(
            f"/api/public/candidate-files?name={quote(resume.name)}", "POST", resume.read_bytes(),
            {"Content-Type": "application/pdf"},
        )["file"]

    def create(self, state: dict, file_id: str) -> dict:
        body = json.dumps({
            "job_id": state["job_id"], "file_id": file_id,
            "client_token": state["client_token"],
            "portfolio_url": state["portfolio_url"],
            "self_introduction": state["self_introduction"],
            "candidate_name": state["candidate_name"],
            "candidate_email": state["candidate_email"],
            "candidate_phone_or_wechat": state["candidate_phone_or_wechat"],
            "consent_confirmed": True,
        }, ensure_ascii=False).encode()
        return self.request(
            "/api/public/candidate-applications", "POST", body,
            {"Content-Type": "application/json"},
        )["application"]

    def status(self, state: dict) -> dict:
        application_id = quote(state["application"]["id"], safe="")
        return self.request(
            f"/api/public/candidate-applications/{application_id}",
            headers={"X-Application-Client-Token": state["client_token"]},
        )["application"]


def submit(profile_path: Path, state_path: Path, client: ApiClient | None = None) -> dict:
    validate_state_path(state_path)
    profile = load(profile_path)
    state = load(state_path)
    if state.get("schema_version") != SCHEMA:
        raise ValueError("提交状态版本无效")
    resume = authorized(profile, profile_path, state)  # Must happen before any network request.
    client = client or ApiClient(state["service_url"])
    if state.get("application"):
        state["application"] = client.status(state)
        save_private(state_path, state)
        return state["application"]
    health = client.health()
    if health.get("ok") is not True or health.get("database") != "ready":
        raise RuntimeError("工作台尚未 ready，未上传材料")
    file = client.upload(resume)
    state["file_id"] = file["id"]
    save_private(state_path, state)
    state["application"] = client.create(state, file["id"])
    save_private(state_path, state)
    return state["application"]


def query_status(state_path: Path, client: ApiClient | None = None) -> dict:
    validate_state_path(state_path)
    state = load(state_path)
    if not state.get("application"):
        raise ValueError("尚无可查询的申请")
    client = client or ApiClient(state["service_url"])
    state["application"] = client.status(state)
    save_private(state_path, state)
    return state["application"]


class FakeClient:
    def __init__(self):
        self.reads = 0
        self.writes = 0
        self.created_identity = None

    def health(self):
        self.reads += 1
        return {"ok": True, "database": "ready"}

    def upload(self, resume):
        self.writes += 1
        return {"id": "file-" + sha256(resume)[:12]}

    def create(self, state, file_id):
        self.writes += 1
        self.created_identity = {
            key: state[key]
            for key in ["candidate_name", "candidate_email", "candidate_phone_or_wechat"]
        }
        return {"id": "application-test", "status": "processing", "repeated": False}

    def status(self, state):
        self.reads += 1
        return {"id": state["application"]["id"], "status": "processing", "repeated": True}


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        resume = root / "resume.pdf"
        resume.write_bytes(b"%PDF-test")
        profile_path = root / ".fanhan-job-agent" / "profile.json"
        career_document = root / ".fanhan-job-agent" / "职业经历.md"
        career_document.parent.mkdir(parents=True, exist_ok=True)
        career_document.write_text("# 职业经历\n", encoding="utf-8")
        tailored_resume = root / ".fanhan-job-agent" / "outbox" / "张三-Example-AI产品经理-20260818-v1.pdf"
        tailored_resume.parent.mkdir(parents=True, exist_ok=True)
        tailored_resume.with_suffix(".html").write_text(
            '<body data-fanhan-resume-editor="v2"><main contenteditable="true"></main>'
            '<script src="html2pdf.bundle.min.js"></script><script src="resume-editor.js"></script></body>',
            encoding="utf-8",
        )
        tailored_resume.write_bytes(b"%PDF-1.4 jsPDF tailored")
        job_path = root / "job.json"
        introduction_path = root / "intro.txt"
        state_path = root / ".fanhan-job-agent" / "submission.json"
        profile = {
            "schema_version": "fanhan-career-profile-v1",
            "resume": {"path": str(resume)},
            "application_resume": {"path": str(tailored_resume)},
            "identity": {"name": "张三"},
            "career_document": {"path": str(career_document)},
            "contact": {"email": "candidate@example.com", "phone_or_wechat": "unknown"},
            "intent": {
                "target_roles": ["AI 产品经理"], "employment_type": "full_time",
                "preferred_locations": ["上海"], "remote_preference": "conditional",
                "relocation_preference": "reject", "available_from": "2026-09-01",
            },
            "education": {"status": "known", "items": []},
            "core_experiences": {"status": "known", "items": []},
            "evidence": {
                "identity.name": ["简历第 1 页"],
                "contact.email": ["简历第 1 页"], "intent.target_roles": ["候选人明确回答"],
                "intent.employment_type": ["候选人明确回答"],
                "intent.preferred_locations": ["候选人明确回答"],
                "intent.remote_preference": ["候选人明确回答"],
                "intent.relocation_preference": ["候选人明确回答"],
                "intent.available_from": ["候选人明确回答"],
                "education": ["简历教育经历"], "core_experiences": ["简历项目经历"],
            },
            "consent": {"confirmed": False},
        }
        save_private(profile_path, profile)
        job_path.write_text(json.dumps({"id": "job-1", "title": "AI 产品经理"}), encoding="utf-8")
        introduction_path.write_text("我有真实 AI 产品交付经验。", encoding="utf-8")
        preview = prepare(profile_path, job_path, introduction_path, state_path, "https://workbench.example.com")
        assert preview["network_writes"] == 0
        assert preview["resume"]["name"] == tailored_resume.name
        assert preview["confirmed_identity_included"] is True
        tailored_resume.write_bytes(b"%PDF-1.4 HeadlessChrome Skia/PDF")
        try:
            prepare(profile_path, job_path, introduction_path, state_path, "https://workbench.example.com")
            raise AssertionError("重新生成的 PDF 不应进入工作台")
        except ValueError as error:
            assert "禁止重新生成" in str(error)
        tailored_resume.write_bytes(b"%PDF-1.4 jsPDF tailored")
        fake = FakeClient()
        try:
            submit(profile_path, state_path, fake)
            raise AssertionError("未授权不应上传")
        except PermissionError:
            pass
        assert fake.reads == fake.writes == 0

        record_consent(profile_path, state_path)
        first = submit(profile_path, state_path, fake)
        second = submit(profile_path, state_path, fake)
        assert first["id"] == second["id"] == "application-test"
        assert fake.writes == 2  # One PDF upload and one application creation.
        assert fake.created_identity == {
            "candidate_name": "张三",
            "candidate_email": "candidate@example.com",
            "candidate_phone_or_wechat": "",
        }
        assert second["repeated"] is True
        assert "client_token" not in preview
    print("workbench_client self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preview = subparsers.add_parser("preview")
    preview.add_argument("profile")
    preview.add_argument("job")
    preview.add_argument("introduction")
    preview.add_argument("state")
    preview.add_argument("--base-url", default=os.environ.get("FANHAN_WORKBENCH_URL", "https://fanhan-workbench.zeabur.app"))
    preview.add_argument("--portfolio-url", default="")
    consent = subparsers.add_parser("record-consent")
    consent.add_argument("profile")
    consent.add_argument("state")
    consent.add_argument("--confirmed", action="store_true", required=True)
    submit_parser = subparsers.add_parser("submit")
    submit_parser.add_argument("profile")
    submit_parser.add_argument("state")
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("state")
    subparsers.add_parser("self-test")
    args = parser.parse_args()

    if args.command == "preview":
        result = prepare(*map(lambda value: Path(value).expanduser().resolve(), [
            args.profile, args.job, args.introduction, args.state,
        ]), args.base_url, args.portfolio_url)
    elif args.command == "record-consent":
        record_consent(Path(args.profile).expanduser().resolve(), Path(args.state).expanduser().resolve())
        result = {"consent_recorded": True, "consent_version": CONSENT_VERSION}
    elif args.command == "submit":
        result = submit(Path(args.profile).expanduser().resolve(), Path(args.state).expanduser().resolve())
    elif args.command == "status":
        result = query_status(Path(args.state).expanduser().resolve())
    else:
        self_test()
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
