#!/usr/bin/env python3
"""Preview, record consent, and idempotently deliver a referral to the Grok Bot webhook.

The webhook URL and bearer key are operator secrets. Read them from the environment
or from a gitignored local file. Never print them or the idempotency key.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sys
import zlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

import workspace
from profile_status import evaluate as profile_evaluate


SCHEMA = "fanhan-grok-bot-referral-v1"
CONSENT_VERSION = "fanhan-candidate-materials-v2"
SOURCE = "genius-career-advisor-skill"
AUTHORIZATION_TEXT = (
    "我同意将上述求职资料发送给泛函，用于候选人档案管理、岗位匹配和招聘团队人工审核。"
    "资料将保存在泛函的 Twenty 招聘 CRM。我之后可以要求停止推荐或删除档案。"
)
RECEIVER = "泛函招聘团队"
STORAGE = "泛函 Twenty 招聘 CRM"
PURPOSE = "候选人档案管理、岗位匹配和招聘团队人工审核"
CONFIG_NAME = "grok-bot-referral.json"
ENV_URL = "FANHAN_GROK_BOT_WEBHOOK_URL"
ENV_KEY = "FANHAN_GROK_BOT_WEBHOOK_KEY"
MAX_PDF_BYTES = 10 * 1024 * 1024
INLINE_PDF_LIMIT = 1_500_000
MAX_RESUME_TEXT = 100_000
MISSING_CONFIG = (
    "缺少内推接收配置。请操作者在本机设置环境变量 "
    f"{ENV_URL} 和 {ENV_KEY}，或写入未被 Git 跟踪的 "
    f"{workspace.PUBLIC_WORKSPACE}/{CONFIG_NAME}。"
    "密钥从 Grok Bot 例程面板「天才职业顾问内推接收」复制，不要向候选人索取，也不要写入仓库。"
)
MISSING_PARTIAL = (
    f"{ENV_URL} 和 {ENV_KEY} 必须同时设置。"
    "不要只配置其中一项，也不要向候选人索取密钥。"
)
UNKNOWN = {"", "unknown", "未知", "none", "null"}
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,200}$")


class DeliveryError(RuntimeError):
    def __init__(self, message: str, http_status: int | None, attempts: int):
        super().__init__(message)
        self.http_status = http_status
        self.attempts = attempts


class _NoRedirect(HTTPRedirectHandler):
    """Refuse redirects so the bearer key is not sent to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
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


def clean(value: object) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    if text.lower() in UNKNOWN:
        return None
    return text


def known_strings(value: object) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        if isinstance(item, dict):
            item = item.get("url") or item.get("name") or item.get("value")
        text = clean(item)
        if text and text not in items:
            items.append(text)
    return items


def employment_type(value: object) -> str | None:
    raw = "" if value is None else str(value).strip()
    key = raw.lower().replace(" ", "").replace("_", "").replace("-", "")
    if raw in {"全职", "正式", "正职"} or key == "fulltime":
        return "full_time"
    if raw == "实习" or key in {"internship", "intern"}:
        return "internship"
    if raw in {"两者都可以", "实习或全职", "全职或实习"} or key in {"either", "both"}:
        return None
    if raw.lower() in UNKNOWN or raw == "":
        return "unknown"
    return None


def split_phone_wechat(value: object) -> tuple[str | None, str | None]:
    text = clean(value)
    if not text or len(text) < 5:
        return None, None
    if re.fullmatch(r"\+?\d[\d\s\-()]{4,}", text):
        return text, None
    return None, text


def http_links(value: object) -> list[str]:
    links: list[str] = []
    for item in known_strings(value):
        parsed = urlparse(item)
        if parsed.scheme in {"http", "https"} and parsed.netloc and item not in links:
            links.append(item)
    return links


def first_clean(profile: dict, paths: list[str]) -> str | None:
    for path in paths:
        current: object = profile
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current[part]
        text = clean(current)
        if text:
            return text
    return None


def candidate_snapshot(profile: dict, portfolio_url: str = "") -> dict:
    name = clean(profile.get("identity", {}).get("name") if isinstance(profile.get("identity"), dict) else None)
    contact = profile.get("contact") if isinstance(profile.get("contact"), dict) else {}
    email = clean(contact.get("email"))
    if email:
        email = email.lower()
        if not EMAIL.fullmatch(email):
            email = None
    phone, wechat = split_phone_wechat(contact.get("phone_or_wechat"))
    if not name or not (email or phone or wechat):
        raise ValueError("候选人确认身份必须包含姓名，以及有效邮箱或电话／微信中的至少一项")

    candidate: dict = {"name": name}
    if email:
        candidate["email"] = email
    if phone:
        candidate["phone"] = phone
    if wechat:
        candidate["wechat"] = wechat

    city = first_clean(profile, ["identity.city", "contact.city", "city"])
    if city:
        candidate["city"] = city

    intent = profile.get("intent") if isinstance(profile.get("intent"), dict) else {}
    mapped = employment_type(intent.get("employment_type"))
    if mapped:
        candidate["employment_type"] = mapped

    locations = known_strings(intent.get("preferred_locations"))
    if locations:
        candidate["desired_locations"] = locations

    work_mode = first_clean(profile, ["intent.work_mode", "work_mode"])
    if work_mode:
        candidate["work_mode"] = work_mode

    direction = first_clean(profile, ["intent.direction", "direction"])
    roles = known_strings(intent.get("target_roles"))
    if not direction and roles:
        direction = "、".join(roles)
    if direction:
        candidate["direction"] = direction

    skills = known_strings(profile.get("skills"))
    if skills:
        candidate["skills"] = skills

    portfolio = http_links(profile.get("optional_links"))
    extra = http_links([portfolio_url] if portfolio_url else [])
    for link in extra:
        if link not in portfolio:
            portfolio.append(link)
    if portfolio:
        candidate["portfolio"] = portfolio

    for key, paths in {
        "current_title": ["identity.current_title", "current_title"],
        "current_company": ["identity.current_company", "current_company"],
        "years_experience": ["identity.years_experience", "years_experience"],
    }.items():
        text = first_clean(profile, paths)
        if text:
            candidate[key] = text
    return candidate


def target_role(job: dict | None) -> dict:
    if not job:
        return {}
    role: dict[str, str] = {}
    company = clean(job.get("company"))
    title = clean(job.get("title"))
    source = clean(job.get("source"))
    job_id = clean(job.get("job_id") if job.get("job_id") is not None else job.get("id"))
    if job_id and job_id.lower().startswith(("http://", "https://")):
        source = source or job_id
        job_id = None
    if company:
        role["company"] = company
    if title:
        role["title"] = title
    if job_id:
        role["job_id"] = job_id
    if source:
        role["source"] = source
    return role


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def signature(packet: dict) -> str:
    return hashlib.sha256(canonical(packet)).hexdigest()


def validate_state_path(path: Path) -> None:
    if workspace.workspace_index(path.resolve().parts) is None:
        raise ValueError("提交状态必须保存在本地工作区 .天才职业顾问/ 中")


def resume_path(profile: dict, profile_path: Path) -> Path:
    application = profile.get("application_resume") if isinstance(profile.get("application_resume"), dict) else {}
    value = str(application.get("path") or "").strip()
    if not value:
        raise ValueError("profile.application_resume.path 不能为空；禁止上传原始简历")
    path = Path(value).expanduser()
    return (path if path.is_absolute() else profile_path.parent / path).resolve()


def validate_pdf(path: Path) -> tuple[str, int, bytes]:
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise ValueError("内推只接受存在的当前岗位专用 PDF")
    if path.parent.name != "outbox" or not workspace.is_workspace_name(path.parent.parent.name):
        raise ValueError("岗位专用 PDF 必须来自本地工作区 .天才职业顾问/outbox/")
    html_path = path.with_suffix(".html")
    if not html_path.is_file():
        raise ValueError("缺少同名可编辑 HTML；禁止跳过 HTML 直接上传 PDF")
    page = html_path.read_text(encoding="utf-8")
    if (
        'contenteditable="true"' not in page
        or not any(f'data-fanhan-resume-editor="v{version}"' in page for version in (2, 3))
        or "html2pdf.bundle.min.js" not in page
        or "resume-editor.js" not in page
        or "window.print()" in page
    ):
        raise ValueError("同名 HTML 不是可编辑、可导出的简历")
    pdf = path.read_bytes()
    size = len(pdf)
    if not 0 < size <= MAX_PDF_BYTES or not pdf.startswith(b"%PDF-"):
        raise ValueError("PDF 必须有效且不超过 10 MB")
    if b"jsPDF" not in pdf:
        raise ValueError("PDF 必须由内置 HTML 编辑器导出，禁止重新生成替代文件")
    if path.stat().st_mtime_ns < html_path.stat().st_mtime_ns:
        raise ValueError("PDF 必须由用户在检查 HTML 后导出")
    return sha256_bytes(pdf), size, pdf


def decode_pdf_literal(raw: bytes) -> str:
    out = bytearray()
    index = 0
    mapping = {
        ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12,
        ord("("): 40, ord(")"): 41, ord("\\"): 92,
    }
    while index < len(raw):
        char = raw[index]
        if char != 0x5C or index + 1 >= len(raw):
            out.append(char)
            index += 1
            continue
        nxt = raw[index + 1]
        if nxt in mapping:
            out.append(mapping[nxt])
            index += 2
            continue
        if nxt in b"01234567":
            octal = bytearray([nxt])
            index += 2
            for _ in range(2):
                if index < len(raw) and raw[index] in b"01234567":
                    octal.append(raw[index])
                    index += 1
                else:
                    break
            out.append(int(octal, 8) & 0xFF)
            continue
        index += 2
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        return out.decode("latin-1", errors="ignore")


def extract_resume_text(pdf: bytes) -> str:
    blobs = [pdf]
    for stream in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf, flags=re.S):
        blobs.append(stream)
        try:
            blobs.append(zlib.decompress(stream))
        except zlib.error:
            pass
    parts: list[str] = []
    for blob in blobs:
        for match in re.finditer(rb"\((?:\\.|[^\\)])*\)", blob):
            parts.append(decode_pdf_literal(match.group(0)[1:-1]))
    text = "".join(parts).replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 8 or text in {"jsPDF", "jsPDF tailored"}:
        return ""
    return text[:MAX_RESUME_TEXT]


def maybe_pdf_base64(pdf: bytes) -> str | None:
    if len(pdf) > INLINE_PDF_LIMIT:
        return None
    return base64.b64encode(pdf).decode("ascii")


def load_optional_job(path: Path | None) -> dict | None:
    if path is None:
        return None
    if not path.is_file():
        raise ValueError("目标岗位文件不存在；没有岗位时请省略 --job，不要伪造岗位 ID")
    job = load(path)
    return job


def build_packet(
    profile: dict, resume_name: str, resume_sha: str, resume_size: int, resume_file: Path,
    introduction: str, portfolio_url: str, job: dict | None, notes: str,
) -> dict:
    packet = {
        "candidate": candidate_snapshot(profile, portfolio_url),
        "self_introduction": introduction,
        "resume_name": resume_name,
        "resume_sha256": resume_sha,
        "resume_size": resume_size,
        "resume_path": str(resume_file),
    }
    role = target_role(job)
    if role:
        packet["target_role"] = role
    note = clean(notes)
    if note:
        packet["notes"] = note
    return packet


def new_idempotency_key() -> str:
    token = secrets.token_urlsafe(24)
    if not KEY_PATTERN.fullmatch(token):
        raise RuntimeError("无法生成本地提交标识")
    return token


def prepare(
    profile_path: Path, introduction_path: Path, state_path: Path,
    job_path: Path | None = None, portfolio_url: str = "", notes: str = "",
) -> dict:
    validate_state_path(state_path)
    profile = load(profile_path)
    if profile.get("schema_version") != "fanhan-career-profile-v1":
        raise ValueError("profile.schema_version 必须是 fanhan-career-profile-v1")
    resume = resume_path(profile, profile_path)
    digest, size, pdf = validate_pdf(resume)
    introduction = introduction_path.read_text(encoding="utf-8").strip()
    if not 0 < len(introduction) <= 3000:
        raise ValueError("自荐说明必须为 1–3000 个字符")
    if portfolio_url:
        parsed = urlparse(portfolio_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("作品集必须是 HTTP(S) 链接")
    job = load_optional_job(job_path)
    packet = build_packet(
        profile, resume.name, digest, size, resume, introduction, portfolio_url, job, notes,
    )
    signed = signature(packet)
    if state_path.exists():
        state = load(state_path)
        if state.get("schema_version") != SCHEMA or not KEY_PATTERN.fullmatch(str(state.get("idempotency_key") or "")):
            raise ValueError("已有提交状态无效。请使用新的状态文件重新 preview，不要沿用旧的工作台提交状态。")
        if state.get("signature") != signed:
            raise ValueError("已有提交状态与本次材料不一致，请使用新的状态文件。不要在原文件里更换提交标识。")
    else:
        state = {
            "schema_version": SCHEMA,
            "signature": signed,
            "consent_version": CONSENT_VERSION,
            "idempotency_key": new_idempotency_key(),
            "packet": packet,
            "delivery": None,
        }
        save_private(state_path, state)
    status = profile_evaluate(profile, profile_path.parent)
    text = extract_resume_text(pdf)
    preview = {
        "receiver": RECEIVER,
        "storage": STORAGE,
        "purpose": PURPOSE,
        "authorization_text": AUTHORIZATION_TEXT,
        "candidate_fields": sorted(packet["candidate"].keys()),
        "resume": {
            "name": resume.name,
            "size": size,
            "sha256": digest,
            "text_available": bool(text),
            "pdf_will_be_attached": size <= INLINE_PDF_LIMIT,
        },
        "self_introduction_characters": len(introduction),
        "portfolio_count": len(packet["candidate"].get("portfolio", [])),
        "profile_status": status["profile_status"],
        "ingest_ready": status["ingest_ready"],
        "missing_for_ingest": status["missing_for_ingest"],
        "network_writes": 0,
    }
    if packet.get("target_role"):
        preview["target_role"] = packet["target_role"]
    return preview


def record_consent(profile_path: Path, state_path: Path, confirmed: bool) -> None:
    if not confirmed:
        raise PermissionError("没有清晰同意，禁止记录授权")
    validate_state_path(state_path)
    profile = load(profile_path)
    state = load(state_path)
    if state.get("schema_version") != SCHEMA:
        raise ValueError("提交状态版本无效")
    digest, _, _ = validate_pdf(resume_path(profile, profile_path))
    candidate = candidate_snapshot(profile)
    packet = state.get("packet") if isinstance(state.get("packet"), dict) else {}
    if digest != packet.get("resume_sha256") or packet.get("candidate", {}).get("name") != candidate["name"]:
        raise ValueError("提交状态与当前简历或姓名不一致")
    for field in ("email", "phone", "wechat"):
        if packet.get("candidate", {}).get(field, "") != candidate.get(field, ""):
            raise ValueError("提交状态与当前联系方式不一致")
    profile["consent"] = {
        "confirmed": True,
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
        "material_version": f"sha256:{digest}",
        "idempotency_key": state["idempotency_key"],
        "text_version": CONSENT_VERSION,
    }
    save_private(profile_path, profile)


def authorized(profile: dict, profile_path: Path, state: dict) -> tuple[Path, bytes, str]:
    if state.get("schema_version") != SCHEMA or state.get("consent_version") != CONSENT_VERSION:
        raise PermissionError("提交状态不是当前内推授权，禁止发送")
    resume = resume_path(profile, profile_path)
    digest, _, pdf = validate_pdf(resume)
    packet = state.get("packet") if isinstance(state.get("packet"), dict) else {}
    consent = profile.get("consent") if isinstance(profile.get("consent"), dict) else {}
    expected = {
        "confirmed": True,
        "material_version": f"sha256:{digest}",
        "idempotency_key": state.get("idempotency_key"),
        "text_version": CONSENT_VERSION,
    }
    if any(consent.get(key) != value for key, value in expected.items()) or not clean(consent.get("confirmed_at")):
        raise PermissionError("没有与当前材料绑定的可审计授权；禁止发送")
    if digest != packet.get("resume_sha256") or signature(packet) != state.get("signature"):
        raise PermissionError("材料已变化；必须重新预览并授权")
    current = candidate_snapshot(profile)
    stored = packet.get("candidate") if isinstance(packet.get("candidate"), dict) else {}
    if any(stored.get(field, "") != current.get(field, "") for field in ("name", "email", "phone", "wechat")):
        raise PermissionError("候选人身份已变化；必须重新预览并授权")
    status = profile_evaluate(profile, profile_path.parent)
    if not status["ingest_ready"]:
        raise ValueError(f"未达到最低发送条件：{status['missing_for_ingest']}")
    confirmed_at = str(consent["confirmed_at"])
    return resume, pdf, confirmed_at


def build_payload(state: dict, confirmed_at: str, pdf: bytes) -> dict:
    if state.get("consent_version") != CONSENT_VERSION:
        raise PermissionError("授权版本不匹配，禁止发送")
    packet = state["packet"]
    payload = {
        "type": "skill_referral",
        "source": SOURCE,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "idempotency_key": state["idempotency_key"],
        "consent": {
            "confirmed": True,
            "text": AUTHORIZATION_TEXT,
            "confirmed_at": confirmed_at,
        },
        "candidate": packet["candidate"],
        "resume_filename": packet["resume_name"],
    }
    introduction = clean(packet.get("self_introduction"))
    if introduction:
        payload["self_introduction"] = introduction
    if packet.get("target_role"):
        payload["target_role"] = packet["target_role"]
    text = extract_resume_text(pdf)
    if text:
        payload["resume_text"] = text
    encoded = maybe_pdf_base64(pdf)
    if encoded:
        payload["resume_pdf_base64"] = encoded
    note = clean(packet.get("notes"))
    if note:
        payload["notes"] = note
    if payload["consent"]["confirmed"] is not True:
        raise PermissionError("授权未确认，禁止发送")
    return payload


def validate_webhook_url(value: str) -> str:
    text = value.strip()
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    local = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise ValueError("内推接收地址必须使用 HTTPS；本机测试地址除外")
    if parsed.username or parsed.password or not parsed.netloc:
        raise ValueError("内推接收地址无效")
    if "\n" in text or "\r" in text:
        raise ValueError("内推接收地址无效")
    return text


def load_webhook_config(state_path: Path) -> tuple[str, str]:
    env_url = os.environ.get(ENV_URL, "").strip()
    env_key = os.environ.get(ENV_KEY, "").strip()
    if env_url or env_key:
        if not env_url or not env_key:
            raise RuntimeError(MISSING_PARTIAL)
        return validate_webhook_url(env_url), validate_key(env_key)
    config_path = state_path.parent / CONFIG_NAME
    if not workspace.is_workspace_name(state_path.parent.name) or not config_path.is_file():
        raise RuntimeError(MISSING_CONFIG)
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise RuntimeError(
            "本机内推配置无法读取。请操作者检查工作区里的 "
            f"{CONFIG_NAME}，不要向候选人索取密钥。"
        ) from None
    if not isinstance(data, dict):
        raise RuntimeError(MISSING_CONFIG)
    url = str(data.get("webhook_url") or "").strip()
    key = str(data.get("webhook_key") or "").strip()
    if not url or not key:
        raise RuntimeError(MISSING_CONFIG)
    return validate_webhook_url(url), validate_key(key)


def validate_key(value: str) -> str:
    if not value or any(char.isspace() for char in value):
        raise ValueError("内推接收密钥无效。请操作者在本机重新设置，不要向候选人索取。")
    return value


def post_once(url: str, key: str, body: bytes, timeout: int = 30) -> int:
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    opener = build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            response.read(4096)
            return int(response.status)
    except HTTPError as error:
        try:
            error.read(4096)
        except OSError:
            pass
        return int(error.code)


def deliver(url: str, key: str, body: bytes, transport=post_once) -> int:
    status: int | None = None
    for attempt in (1, 2):
        try:
            status = int(transport(url, key, body))
        except (URLError, TimeoutError, OSError):
            status = None
            if attempt == 2:
                raise DeliveryError(
                    "内推材料未能送达泛函招聘团队：无法连接接收端。"
                    "已用同一份授权重试一次。请稍后对同一状态文件再次运行 submit，不要新建第二次内推。",
                    None,
                    2,
                ) from None
            continue
        if status == 200:
            return attempt
        if attempt == 2:
            raise DeliveryError(
                f"内推材料未能送达泛函招聘团队：HTTP {status}。"
                "已用同一份授权重试一次。请稍后对同一状态文件再次运行 submit，不要新建第二次内推。",
                status,
                2,
            )
    raise DeliveryError("内推材料未能送达泛函招聘团队。", status, 2)


def public_result(repeated: bool) -> dict:
    return {
        "delivered": True,
        "http_status": 200,
        "receiver": RECEIVER,
        "storage": STORAGE,
        "repeated": repeated,
    }


def submit(profile_path: Path, state_path: Path, transport=post_once) -> dict:
    validate_state_path(state_path)
    profile = load(profile_path)
    state = load(state_path)
    _, pdf, confirmed_at = authorized(profile, profile_path, state)
    delivery = state.get("delivery") if isinstance(state.get("delivery"), dict) else {}
    if delivery.get("status") == "delivered":
        return public_result(True)
    url, key = load_webhook_config(state_path)
    payload = build_payload(state, confirmed_at, pdf)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    try:
        attempts = deliver(url, key, body, transport)
    except DeliveryError as error:
        state["delivery"] = {
            "status": "failed",
            "http_status": error.http_status,
            "attempts": error.attempts,
        }
        save_private(state_path, state)
        raise
    state["delivery"] = {
        "status": "delivered",
        "http_status": 200,
        "delivered_at": payload["submitted_at"],
        "attempts": attempts,
    }
    save_private(state_path, state)
    return public_result(False)


def redact(message: str) -> str:
    secrets_found = [
        os.environ.get(ENV_URL, "").strip(),
        os.environ.get(ENV_KEY, "").strip(),
    ]
    for secret in secrets_found:
        if len(secret) >= 4:
            message = message.replace(secret, "[redacted]")
    return re.sub(r"Bearer\s+\S+", "Bearer [redacted]", message)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preview = subparsers.add_parser("preview")
    preview.add_argument("profile")
    preview.add_argument("introduction")
    preview.add_argument("state")
    preview.add_argument("--job", default="")
    preview.add_argument("--portfolio-url", default="")
    preview.add_argument("--notes", default="")
    consent = subparsers.add_parser("record-consent")
    consent.add_argument("profile")
    consent.add_argument("state")
    consent.add_argument("--confirmed", action="store_true", required=True)
    submit_parser = subparsers.add_parser("submit")
    submit_parser.add_argument("profile")
    submit_parser.add_argument("state")
    subparsers.add_parser("self-test")
    args = parser.parse_args()
    try:
        if args.command == "self-test":
            self_test()
            return
        if args.command == "preview":
            job = Path(args.job).expanduser().resolve() if args.job else None
            result = prepare(
                Path(args.profile).expanduser().resolve(),
                Path(args.introduction).expanduser().resolve(),
                Path(args.state).expanduser().resolve(),
                job,
                args.portfolio_url,
                args.notes,
            )
        elif args.command == "record-consent":
            record_consent(
                Path(args.profile).expanduser().resolve(),
                Path(args.state).expanduser().resolve(),
                args.confirmed,
            )
            result = {"consent_recorded": True, "consent_version": CONSENT_VERSION}
        else:
            result = submit(
                Path(args.profile).expanduser().resolve(),
                Path(args.state).expanduser().resolve(),
            )
    except Exception as error:
        print(redact(str(error).strip() or "内推命令失败"), file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False, indent=2))


def self_test() -> None:
    import unittest

    suite = unittest.defaultTestLoader.discover(
        str(Path(__file__).resolve().parent),
        pattern="test_grok_bot_referral.py",
    )
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("grok_bot_referral self-test: ok")


if __name__ == "__main__":
    main()
