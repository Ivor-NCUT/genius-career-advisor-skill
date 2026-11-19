#!/usr/bin/env python3
"""Referral webhook tests. Fixtures use a fake local URL and key only."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parent))

import grok_bot_referral as referral
from profile_status import CONSULTATION_DIMENSIONS


FAKE_URL = "http://127.0.0.1:9/referral-test"
FAKE_KEY = "test-key-not-real"
FILE_KEY = "local-config-key-not-real"
HTML = (
    '<body data-fanhan-resume-editor="v2"><main contenteditable="true"></main>'
    '<script src="html2pdf.bundle.min.js"></script><script src="resume-editor.js"></script></body>'
)
PDF = b"%PDF-1.4\njsPDF\n(Confirmed resume text for referral) Tj\n%%EOF\n"


class FakeTransport:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls = []

    def __call__(self, url, key, body):
        self.calls.append({"url": url, "key": key, "body": body})
        if not self.statuses:
            raise AssertionError("unexpected extra referral post")
        status = self.statuses.pop(0)
        if isinstance(status, Exception):
            raise status
        return status


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.server.seen.append({
            "authorization": self.headers.get("Authorization"),
            "content_type": self.headers.get("Content-Type"),
            "body": body,
        })
        code = self.server.codes.pop(0) if self.server.codes else 500
        payload = json.dumps({
            "application": {"id": "should-not-surface"},
            "notification": {"status": "sent"},
            "match": {"score": 99},
        }).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


def isolated_env(url="", key=""):
    class _Env:
        def __enter__(self):
            self.saved = {name: os.environ.get(name) for name in (referral.ENV_URL, referral.ENV_KEY)}
            os.environ.pop(referral.ENV_URL, None)
            os.environ.pop(referral.ENV_KEY, None)
            if url:
                os.environ[referral.ENV_URL] = url
            if key:
                os.environ[referral.ENV_KEY] = key
            return self

        def __exit__(self, exc_type, exc, tb):
            for name, value in self.saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            return False

    return _Env()


def write_case(root: Path, employment="full_time", phone="unknown", email="candidate@example.com", job=None, workspace_name=".fanhan-job-agent"):
    base = root / workspace_name
    outbox = base / "outbox"
    outbox.mkdir(parents=True)
    original = root / "resume.pdf"
    original.write_bytes(b"%PDF-test")
    career = base / "职业经历.md"
    career.write_text("# 职业经历\n", encoding="utf-8")
    html = outbox / "张三-Example-AI产品经理-20260818-v1.html"
    html.write_text(HTML, encoding="utf-8")
    pdf_path = html.with_suffix(".pdf")
    pdf_path.write_bytes(PDF)
    os.utime(pdf_path, (html.stat().st_atime + 5, html.stat().st_mtime + 5))
    profile = {
        "schema_version": "fanhan-career-profile-v1",
        "resume": {"path": str(original)},
        "application_resume": {"path": str(pdf_path)},
        "identity": {"name": "张三"},
        "career_document": {"path": str(career)},
        "contact": {"email": email, "phone_or_wechat": phone},
        "intent": {
            "target_roles": ["AI 产品经理"],
            "employment_type": employment,
            "preferred_locations": ["上海"],
            "remote_preference": "conditional",
            "relocation_preference": "reject",
            "available_from": "2026-09-01",
        },
        "education": {"status": "known", "items": []},
        "core_experiences": {"status": "known", "items": []},
        "career_consultation": {
            dimension: {
                "summary": f"已确认的{dimension}",
                "confirmed": True,
                "evidence": ["候选人明确回答"],
            }
            for dimension in CONSULTATION_DIMENSIONS
        },
        "evidence": {
            "identity.name": ["简历第 1 页"],
            "contact.email": ["简历第 1 页"],
            "contact.phone_or_wechat": ["候选人明确回答"],
            "intent.target_roles": ["候选人明确回答"],
            "intent.employment_type": ["候选人明确回答"],
            "intent.preferred_locations": ["候选人明确回答"],
            "intent.remote_preference": ["候选人明确回答"],
            "intent.relocation_preference": ["候选人明确回答"],
            "intent.available_from": ["候选人明确回答"],
            "education": ["简历教育经历"],
            "core_experiences": ["简历项目经历"],
        },
        "consent": {"confirmed": False},
    }
    profile_path = base / "profile.json"
    referral.save_private(profile_path, profile)
    introduction = base / "self-introduction.txt"
    introduction.write_text("我有真实 AI 产品交付经验。", encoding="utf-8")
    state_path = base / "submission.json"
    job_path = None
    if job is not None:
        job_path = base / "job.json"
        job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    return profile_path, introduction, state_path, job_path


def assert_no_blanks(testcase, value):
    if isinstance(value, dict):
        for key, item in value.items():
            testcase.assertNotIn(item, ("", [], {}))
            assert_no_blanks(testcase, item)
    elif isinstance(value, list):
        testcase.assertTrue(value)
        for item in value:
            testcase.assertNotEqual(item, "")
            assert_no_blanks(testcase, item)


class ReferralTests(unittest.TestCase):
    def test_payload_shape_and_mappings(self):
        self.assertEqual(referral.employment_type("正式"), "full_time")
        self.assertEqual(referral.employment_type("全职"), "full_time")
        self.assertEqual(referral.employment_type("正职"), "full_time")
        self.assertEqual(referral.employment_type("实习"), "internship")
        self.assertEqual(referral.employment_type("unknown"), "unknown")
        self.assertIsNone(referral.employment_type("either"))
        self.assertIsNone(referral.employment_type("两者都可以"))
        phone, wechat = referral.split_phone_wechat("13800138000")
        self.assertEqual((phone, wechat), ("13800138000", None))
        phone, wechat = referral.split_phone_wechat("zhang-san-wx")
        self.assertEqual((phone, wechat), (None, "zhang-san-wx"))
        role = referral.target_role({"title": "产品经理", "company": "泛函"})
        self.assertEqual(role, {"company": "泛函", "title": "产品经理"})
        external = referral.target_role({
            "id": "https://jobs.example/role",
            "title": "外部岗位",
            "company": "示例公司",
        })
        self.assertNotIn("job_id", external)
        self.assertEqual(external["source"], "https://jobs.example/role")

        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path, introduction, state_path, _ = write_case(root, employment="全职")
            with isolated_env():
                preview = referral.prepare(profile_path, introduction, state_path, None)
            self.assertEqual(preview["network_writes"], 0)
            self.assertNotIn("target_role", preview)
            self.assertEqual(preview["authorization_text"], referral.AUTHORIZATION_TEXT)
            self.assertNotIn("工作台", preview["authorization_text"])
            self.assertNotIn("飞书", preview["authorization_text"])
            state = referral.load(state_path)
            rendered = json.dumps(preview, ensure_ascii=False)
            self.assertNotIn(state["idempotency_key"], rendered)
            referral.record_consent(profile_path, state_path, True)
            _, pdf, confirmed_at = referral.authorized(referral.load(profile_path), profile_path, referral.load(state_path))
            payload = referral.build_payload(referral.load(state_path), confirmed_at, pdf)
            assert_no_blanks(self, payload)
            self.assertEqual(payload["type"], "skill_referral")
            self.assertEqual(payload["source"], "genius-career-advisor-skill")
            self.assertTrue(payload["consent"]["confirmed"])
            self.assertEqual(payload["consent"]["text"], referral.AUTHORIZATION_TEXT)
            self.assertEqual(payload["candidate"]["employment_type"], "full_time")
            self.assertEqual(payload["candidate"]["email"], "candidate@example.com")
            self.assertNotIn("phone", payload["candidate"])
            self.assertNotIn("wechat", payload["candidate"])
            self.assertNotIn("city", payload["candidate"])
            self.assertEqual(payload["candidate"]["desired_locations"], ["上海"])
            self.assertEqual(payload["candidate"]["direction"], "AI 产品经理")
            self.assertNotIn("target_role", payload)
            self.assertEqual(payload["resume_filename"], "张三-Example-AI产品经理-20260818-v1.pdf")
            self.assertIn("Confirmed resume text for referral", payload["resume_text"])
            self.assertEqual(base64.b64decode(payload["resume_pdf_base64"]), PDF)
            self.assertNotIn("client_token", payload)
            self.assertNotIn("notification", payload)
            self.assertNotIn("file_id", payload)
            datetime_text = payload["submitted_at"]
            self.assertIn("T", datetime_text)
            for banned in ("candidate-applications", "candidate-files", "飞书招聘话题群"):
                self.assertNotIn(banned, json.dumps(payload, ensure_ascii=False))

    def test_unknown_employment_and_wechat_contact(self):
        candidate = referral.candidate_snapshot({
            "identity": {"name": "李四"},
            "contact": {"email": "unknown", "phone_or_wechat": "zhang-san-wx"},
            "intent": {"employment_type": "unknown", "target_roles": []},
        })
        self.assertEqual(candidate["employment_type"], "unknown")
        self.assertEqual(candidate["wechat"], "zhang-san-wx")
        self.assertNotIn("email", candidate)
        self.assertNotIn("phone", candidate)
        omitted = referral.candidate_snapshot({
            "identity": {"name": "李四", "city": "未知"},
            "contact": {"email": "li@example.com", "phone_or_wechat": "unknown"},
            "intent": {"employment_type": "either"},
        })
        self.assertNotIn("employment_type", omitted)
        self.assertNotIn("city", omitted)

    def test_large_pdf_omits_base64_but_keeps_text_and_name(self):
        state = {
            "consent_version": referral.CONSENT_VERSION,
            "idempotency_key": "a" * 24,
            "packet": {
                "candidate": {"name": "张三", "email": "candidate@example.com"},
                "resume_name": "张三-Example-AI产品经理-20260818-v1.pdf",
                "self_introduction": "我有真实 AI 产品交付经验。",
            },
        }
        pdf = b"(Confirmed resume text for referral) Tj\n" + b"0" * (referral.INLINE_PDF_LIMIT + 8)
        payload = referral.build_payload(state, "2026-11-18T00:00:00+00:00", pdf)
        self.assertNotIn("resume_pdf_base64", payload)
        self.assertIn("Confirmed resume text for referral", payload["resume_text"])
        self.assertEqual(payload["resume_filename"], state["packet"]["resume_name"])

    def test_consent_gate_blocks_submit(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            profile_path, introduction, state_path, _ = write_case(Path(directory))
            with isolated_env():
                referral.prepare(profile_path, introduction, state_path, None)
            self.assertRaises(PermissionError, referral.record_consent, profile_path, state_path, False)
            self.assertFalse(referral.load(profile_path)["consent"]["confirmed"])
            transport = FakeTransport([200])
            with isolated_env(FAKE_URL, FAKE_KEY):
                with self.assertRaises(PermissionError):
                    referral.submit(profile_path, state_path, transport)
            self.assertEqual(transport.calls, [])

    def test_missing_config_fails_before_network(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path, introduction, state_path, _ = write_case(root)
            with isolated_env():
                referral.prepare(profile_path, introduction, state_path, None)
                referral.record_consent(profile_path, state_path, True)
                transport = FakeTransport([200])
                with self.assertRaises(RuntimeError) as caught:
                    referral.submit(profile_path, state_path, transport)
            self.assertIn("不要向候选人索取", str(caught.exception))
            self.assertIn(referral.ENV_URL, str(caught.exception))
            self.assertNotIn(FAKE_KEY, str(caught.exception))
            self.assertEqual(transport.calls, [])
            config = root / ".fanhan-job-agent" / referral.CONFIG_NAME
            config.write_text(json.dumps({
                "webhook_url": FAKE_URL,
                "webhook_key": FILE_KEY,
            }), encoding="utf-8")
            with isolated_env(FAKE_URL, ""):
                with self.assertRaises(RuntimeError) as partial:
                    referral.submit(profile_path, state_path, transport)
            self.assertIn("必须同时设置", str(partial.exception))
            self.assertNotIn(FILE_KEY, str(partial.exception))
            self.assertEqual(transport.calls, [])

    def test_idempotent_resubmit_reuses_key_and_does_not_repost(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path, introduction, state_path, job_path = write_case(
                root,
                job={"id": "job-real", "title": "AI 产品经理", "company": "泛函", "source": "public_jobs"},
            )
            with isolated_env():
                referral.prepare(profile_path, introduction, state_path, job_path)
            key = referral.load(state_path)["idempotency_key"]
            with isolated_env():
                referral.prepare(profile_path, introduction, state_path, job_path)
            self.assertEqual(referral.load(state_path)["idempotency_key"], key)
            referral.record_consent(profile_path, state_path, True)
            failed = FakeTransport([503, 503])
            with isolated_env(FAKE_URL, FAKE_KEY):
                with self.assertRaises(referral.DeliveryError) as caught:
                    referral.submit(profile_path, state_path, failed)
            self.assertIn("HTTP 503", str(caught.exception))
            self.assertIn("重试一次", str(caught.exception))
            self.assertNotIn(key, str(caught.exception))
            self.assertNotIn(FAKE_KEY, str(caught.exception))
            self.assertEqual(len(failed.calls), 2)
            self.assertEqual(failed.calls[0]["body"], failed.calls[1]["body"])
            self.assertEqual(failed.calls[0]["key"], FAKE_KEY)
            failed_body = json.loads(failed.calls[0]["body"])
            self.assertEqual(failed_body["idempotency_key"], key)
            self.assertEqual(failed_body["target_role"]["job_id"], "job-real")
            self.assertNotIn(FAKE_KEY, failed.calls[0]["body"].decode("utf-8"))
            state = referral.load(state_path)
            self.assertEqual(state["idempotency_key"], key)
            self.assertEqual(state["delivery"]["status"], "failed")
            self.assertNotIn(FAKE_URL, json.dumps(state))
            self.assertNotIn(FAKE_KEY, json.dumps(state))

            recovered = FakeTransport([500, 200])
            with isolated_env(FAKE_URL, FAKE_KEY):
                result = referral.submit(profile_path, state_path, recovered)
            self.assertEqual(result["delivered"], True)
            self.assertEqual(result["http_status"], 200)
            self.assertFalse(result["repeated"])
            self.assertNotIn("notification", result)
            self.assertNotIn("application", result)
            self.assertNotIn(key, json.dumps(result))
            self.assertEqual(len(recovered.calls), 2)
            self.assertEqual(recovered.calls[0]["body"], recovered.calls[1]["body"])
            self.assertEqual(json.loads(recovered.calls[0]["body"])["idempotency_key"], key)
            self.assertEqual(referral.load(state_path)["idempotency_key"], key)

            again = FakeTransport([200])
            with isolated_env():
                repeated = referral.submit(profile_path, state_path, again)
            self.assertTrue(repeated["repeated"])
            self.assertEqual(again.calls, [])
            self.assertEqual(referral.load(state_path)["idempotency_key"], key)

    def test_connection_error_retries_once_with_same_body(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            profile_path, introduction, state_path, _ = write_case(Path(directory))
            with isolated_env():
                referral.prepare(profile_path, introduction, state_path, None)
                referral.record_consent(profile_path, state_path, True)
            key = referral.load(state_path)["idempotency_key"]
            transport = FakeTransport([URLError("down"), URLError("down")])
            with isolated_env(FAKE_URL, FAKE_KEY):
                with self.assertRaises(referral.DeliveryError) as caught:
                    referral.submit(profile_path, state_path, transport)
            self.assertIn("无法连接", str(caught.exception))
            self.assertEqual(len(transport.calls), 2)
            self.assertEqual(transport.calls[0]["body"], transport.calls[1]["body"])
            self.assertEqual(referral.load(state_path)["idempotency_key"], key)

    def test_local_config_file_is_used_when_env_is_absent(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path, introduction, state_path, _ = write_case(root)
            config = root / ".fanhan-job-agent" / referral.CONFIG_NAME
            config.write_text(json.dumps({
                "webhook_url": FAKE_URL,
                "webhook_key": FILE_KEY,
            }), encoding="utf-8")
            with isolated_env():
                referral.prepare(profile_path, introduction, state_path, None)
                referral.record_consent(profile_path, state_path, True)
                transport = FakeTransport([200])
                result = referral.submit(profile_path, state_path, transport)
            self.assertTrue(result["delivered"])
            self.assertEqual(transport.calls[0]["url"], FAKE_URL)
            self.assertEqual(transport.calls[0]["key"], FILE_KEY)
            stored = state_path.read_text(encoding="utf-8")
            self.assertNotIn(FILE_KEY, stored)
            self.assertNotIn(FAKE_URL, stored)
            self.assertNotIn(FILE_KEY, json.dumps(result))

    def test_changed_materials_do_not_rotate_existing_key(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            profile_path, introduction, state_path, _ = write_case(Path(directory))
            with isolated_env():
                referral.prepare(profile_path, introduction, state_path, None)
            key = referral.load(state_path)["idempotency_key"]
            introduction.write_text("另一份自荐说明，材料已经不同。", encoding="utf-8")
            with isolated_env():
                with self.assertRaises(ValueError):
                    referral.prepare(profile_path, introduction, state_path, None)
            self.assertEqual(referral.load(state_path)["idempotency_key"], key)

    def test_preview_has_no_network_and_rejects_regenerated_pdf(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path, introduction, state_path, _ = write_case(root)
            original_opener = referral.build_opener
            original_post = referral.post_once
            referral.build_opener = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network"))
            referral.post_once = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network"))
            try:
                with isolated_env(FAKE_URL, FAKE_KEY):
                    preview = referral.prepare(profile_path, introduction, state_path, None)
            finally:
                referral.build_opener = original_opener
                referral.post_once = original_post
            self.assertEqual(preview["network_writes"], 0)
            pdf_path = root / ".fanhan-job-agent" / "outbox" / "张三-Example-AI产品经理-20260818-v1.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 HeadlessChrome Skia/PDF")
            other_state = root / ".fanhan-job-agent" / "submission-new.json"
            with self.assertRaises(ValueError) as caught:
                referral.prepare(profile_path, introduction, other_state, None)
            self.assertIn("禁止重新生成", str(caught.exception))

    def test_old_workbench_state_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path, introduction, state_path, _ = write_case(root)
            state_path.write_text(json.dumps({
                "schema_version": "fanhan-workbench-submission-v2",
                "client_token": "a" * 24,
            }), encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                referral.prepare(profile_path, introduction, state_path, None)
            self.assertIn("不要沿用旧的工作台提交状态", str(caught.exception))

    def test_live_webhook_contract_ignores_response_body(self):
        import tempfile
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.seen = []
        server.codes = [503, 200]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            url = f"http://127.0.0.1:{port}/referral-test"
            with tempfile.TemporaryDirectory() as directory:
                profile_path, introduction, state_path, _ = write_case(Path(directory))
                with isolated_env():
                    referral.prepare(profile_path, introduction, state_path, None)
                    referral.record_consent(profile_path, state_path, True)
                key = referral.load(state_path)["idempotency_key"]
                with isolated_env(url, FAKE_KEY):
                    result = referral.submit(profile_path, state_path)
                rendered = json.dumps(result, ensure_ascii=False)
                self.assertEqual(result, {
                    "delivered": True,
                    "http_status": 200,
                    "receiver": referral.RECEIVER,
                    "storage": referral.STORAGE,
                    "repeated": False,
                })
                self.assertNotIn("sent", rendered)
                self.assertNotIn("should-not-surface", rendered)
                self.assertNotIn(key, rendered)
                self.assertNotIn(FAKE_KEY, rendered)
                self.assertEqual(len(server.seen), 2)
                self.assertEqual(server.seen[0]["authorization"], f"Bearer {FAKE_KEY}")
                self.assertEqual(server.seen[0]["content_type"], "application/json")
                self.assertEqual(server.seen[0]["body"], server.seen[1]["body"])
                body = json.loads(server.seen[0]["body"])
                self.assertEqual(body["idempotency_key"], key)
                self.assertTrue(body["consent"]["confirmed"])
                with isolated_env():
                    repeated = referral.submit(profile_path, state_path)
                self.assertTrue(repeated["repeated"])
                self.assertEqual(len(server.seen), 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_command_output_hides_secrets(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path, introduction, state_path, _ = write_case(root)
            script = Path(referral.__file__).resolve()
            env = os.environ.copy()
            env.pop(referral.ENV_URL, None)
            env.pop(referral.ENV_KEY, None)
            env[referral.ENV_URL] = FAKE_URL
            env[referral.ENV_KEY] = FAKE_KEY
            preview = subprocess.run(
                [sys.executable, str(script), "preview", str(profile_path), str(introduction), str(state_path)],
                check=False, capture_output=True, text=True, env=env,
            )
            self.assertEqual(preview.returncode, 0, preview.stderr)
            key = referral.load(state_path)["idempotency_key"]
            visible = preview.stdout + preview.stderr
            self.assertNotIn(key, visible)
            self.assertNotIn(FAKE_KEY, visible)
            self.assertNotIn(FAKE_URL, visible)
            self.assertIn(referral.AUTHORIZATION_TEXT, preview.stdout)
            self.assertEqual(stat_mode(state_path), 0o600)
            consent = subprocess.run(
                [sys.executable, str(script), "record-consent", str(profile_path), str(state_path), "--confirmed"],
                check=False, capture_output=True, text=True, env=env,
            )
            self.assertEqual(consent.returncode, 0, consent.stderr)
            self.assertNotIn(key, consent.stdout + consent.stderr)
            refused = subprocess.run(
                [sys.executable, str(script), "record-consent", str(profile_path), str(state_path)],
                check=False, capture_output=True, text=True, env=env,
            )
            self.assertNotEqual(refused.returncode, 0)
            missing_env = os.environ.copy()
            missing_env.pop(referral.ENV_URL, None)
            missing_env.pop(referral.ENV_KEY, None)
            failed = subprocess.run(
                [sys.executable, str(script), "submit", str(profile_path), str(state_path)],
                check=False, capture_output=True, text=True, env=missing_env,
            )
            self.assertEqual(failed.returncode, 1)
            self.assertIn("不要向候选人索取", failed.stderr)
            self.assertNotIn(key, failed.stdout + failed.stderr)
            self.assertNotIn("Traceback", failed.stderr)

    def test_referral_script_does_not_call_retired_ingest(self):
        text = Path(referral.__file__).read_text(encoding="utf-8")
        for banned in (
            "candidate-applications",
            "candidate-files",
            "WORKBENCH_",
            "notification.status",
            "飞书招聘话题群",
        ):
            self.assertNotIn(banned, text)

    def test_http_201_is_not_delivery(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            profile_path, introduction, state_path, _ = write_case(Path(directory))
            with isolated_env():
                referral.prepare(profile_path, introduction, state_path, None)
                referral.record_consent(profile_path, state_path, True)
            key = referral.load(state_path)["idempotency_key"]
            transport = FakeTransport([201, 201])
            with isolated_env(FAKE_URL, FAKE_KEY):
                with self.assertRaises(referral.DeliveryError) as caught:
                    referral.submit(profile_path, state_path, transport)
            self.assertIn("HTTP 201", str(caught.exception))
            self.assertEqual(len(transport.calls), 2)
            self.assertEqual(json.loads(transport.calls[0]["body"])["idempotency_key"], key)
            self.assertEqual(referral.load(state_path)["delivery"]["status"], "failed")
            self.assertEqual(referral.load(state_path)["idempotency_key"], key)

    def test_retired_workbench_client_refuses(self):
        script = Path(referral.__file__).resolve().with_name("workbench_client.py")
        completed = subprocess.run(
            [sys.executable, str(script), "submit", "profile.json", "state.json"],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("已停用", completed.stderr)
        source = script.read_text(encoding="utf-8")
        self.assertNotIn("candidate-applications", source)
        self.assertNotIn("candidate-files", source)

    def test_public_workspace_accepts_state_and_pdf(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path, _, state_path, _ = write_case(root, workspace_name=".天才职业顾问")
            referral.validate_state_path(state_path)
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            referral.validate_pdf(referral.resume_path(profile, profile_path))
            outside = root / "submission.json"
            outside.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                referral.validate_state_path(outside)


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


if __name__ == "__main__":
    unittest.main()
