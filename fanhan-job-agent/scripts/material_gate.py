#!/usr/bin/env python3
"""Validate a proposal and render the first candidate-facing resume as editable HTML."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path


FACT_CHANGES = {"fact_addition", "fact_change"}
CHANGE_TYPES = FACT_CHANGES | {"rewrite", "reorder"}
ARTIFACT_STEM = re.compile(r"^.+-\d{8}-v[1-9]\d*$")
EDITOR_ASSETS = (
    "html2pdf.bundle.min.js",
    "html2pdf.bundle.min.js.LICENSE.txt",
    "html2pdf.LICENSE",
    "resume-editor.js",
)
MAX_PDF_BYTES = 10 * 1024 * 1024


def required_text(value: object, field: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{field} 不能为空")
    return value


def string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} 必须是非空字符串数组")
    return [required_text(item, field) for item in value]


def resume_path(profile: dict, profile_path: Path) -> Path:
    value = required_text(profile.get("resume", {}).get("path"), "profile.resume.path")
    path = Path(value).expanduser()
    return path if path.is_absolute() else profile_path.parent / path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def filename_part(value: object, field: str) -> str:
    value = unicodedata.normalize("NFKC", required_text(value, field))
    value = re.sub(r"\s+", "", value)
    value = re.sub(r'[\\/:*?"<>|]+', "-", value).strip("-.")
    return required_text(value, field)


def expected_artifact_prefix(profile: dict, proposal: dict) -> str:
    return "-".join([
        filename_part(profile.get("identity", {}).get("name"), "profile.identity.name"),
        filename_part(proposal.get("job", {}).get("company"), "job.company"),
        filename_part(proposal.get("job", {}).get("title"), "job.title"),
    ]) + "-"


def validate(profile: dict, proposal: dict) -> tuple[list[dict], list[dict], dict]:
    if profile.get("schema_version") != "fanhan-career-profile-v1":
        raise ValueError("profile.schema_version 必须是 fanhan-career-profile-v1")
    if proposal.get("schema_version") != "fanhan-tailored-material-v1":
        raise ValueError("proposal.schema_version 必须是 fanhan-tailored-material-v1")

    job = proposal.get("job", {})
    required_text(job.get("id"), "job.id")
    required_text(job.get("company"), "job.company")
    required_text(job.get("title"), "job.title")
    artifact_stem = required_text(proposal.get("artifact_stem"), "artifact_stem")
    if not ARTIFACT_STEM.fullmatch(artifact_stem) or not artifact_stem.startswith(expected_artifact_prefix(profile, proposal)):
        raise ValueError("artifact_stem 必须按 姓名-目标公司-目标岗位-YYYYMMDD-vN 命名")

    sections = proposal.get("sections")
    changes = proposal.get("changes")
    if not isinstance(sections, list) or not sections:
        raise ValueError("sections 必须是非空数组")
    if not isinstance(changes, list) or not changes:
        raise ValueError("changes 必须是非空数组")

    change_by_id = {}
    for index, change in enumerate(changes):
        change_id = required_text(change.get("id"), f"changes[{index}].id")
        if change_id in change_by_id:
            raise ValueError(f"重复的 change id：{change_id}")
        change_type = change.get("type")
        if change_type not in CHANGE_TYPES:
            raise ValueError(f"{change_id}.type 必须是 {sorted(CHANGE_TYPES)} 之一")
        required_text(change.get("summary"), f"{change_id}.summary")
        string_list(change.get("jd_basis"), f"{change_id}.jd_basis")
        string_list(change.get("fact_evidence"), f"{change_id}.fact_evidence")
        confirmation = change.get("confirmation")
        if change_type in FACT_CHANGES and confirmation != "confirmed":
            raise ValueError(f"事实变更 {change_id} 未经候选人确认")
        if confirmation == "confirmed":
            required_text(change.get("confirmed_at"), f"{change_id}.confirmed_at")
        elif change_type not in FACT_CHANGES and confirmation != "not_required":
            raise ValueError(f"非事实变更 {change_id}.confirmation 必须是 not_required")
        change_by_id[change_id] = change

    consultation = proposal.get("consultation", {})
    if consultation.get("status") != "completed":
        raise ValueError("生成简历前必须完成本岗位的针对性咨询")
    questions = consultation.get("questions")
    if not isinstance(questions, list) or not 1 <= len(questions) <= 2:
        raise ValueError("consultation.questions 必须包含 1–2 个已完成问题")
    question_ids = set()
    used_change_ids = set()
    for index, question in enumerate(questions):
        question_id = required_text(question.get("id"), f"consultation.questions[{index}].id")
        if question_id in question_ids:
            raise ValueError(f"重复的 consultation question id：{question_id}")
        question_ids.add(question_id)
        required_text(question.get("question"), f"{question_id}.question")
        string_list(question.get("jd_basis"), f"{question_id}.jd_basis")
        string_list(question.get("profile_basis"), f"{question_id}.profile_basis")
        required_text(question.get("answer_summary"), f"{question_id}.answer_summary")
        if question.get("confirmed") is not True:
            raise ValueError(f"{question_id} 未经候选人确认")
        linked = string_list(question.get("used_in_change_ids"), f"{question_id}.used_in_change_ids")
        unknown = [item for item in linked if item not in change_by_id]
        if unknown:
            raise ValueError(f"{question_id} 引用了未知变更：{unknown}")
        used_change_ids.update(linked)

    if not used_change_ids:
        raise ValueError("针对性咨询结果未进入简历变更")

    referenced = set()
    for index, section in enumerate(sections):
        required_text(section.get("heading"), f"sections[{index}].heading")
        required_text(section.get("content"), f"sections[{index}].content")
        ids = string_list(section.get("change_ids"), f"sections[{index}].change_ids")
        missing = [item for item in ids if item not in change_by_id]
        if missing:
            raise ValueError(f"sections[{index}] 引用了未知变更：{missing}")
        referenced.update(ids)
    unreferenced = set(change_by_id) - referenced
    if unreferenced:
        raise ValueError(f"存在未进入成稿的变更：{sorted(unreferenced)}")
    return sections, changes, consultation


def render_html(title: str, sections: list[dict], editor_version: str) -> str:
    body = []
    for section in sections:
        content = "<br>".join(html.escape(section["content"].strip()).splitlines())
        body.append(f"<section><h2>{html.escape(section['heading'])}</h2><p>{content}</p></section>")
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
@page{{size:A4;margin:0}}*{{box-sizing:border-box}}body{{margin:0;background:#eee;color:#222;font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}.toolbar{{position:sticky;z-index:2;top:0;display:flex;align-items:center;justify-content:flex-end;gap:12px;padding:10px;background:#fff;border-bottom:1px solid #ddd}}.status{{color:#666;font-size:12px}}.status[data-state="error"]{{color:#b42318}}button,.download{{padding:8px 14px;border:0;border-radius:6px;background:#1769e0;color:#fff;cursor:pointer;text-decoration:none}}button:disabled{{cursor:wait;opacity:.65}}.download[hidden]{{display:none}}main{{width:210mm;min-height:297mm;margin:16px auto;padding:14mm;background:#fff;box-shadow:0 2px 14px #bbb;outline:none}}section{{break-inside:avoid;page-break-inside:avoid}}h2{{font-size:16px;border-bottom:1px solid #ddd;padding-bottom:4px}}p{{white-space:normal}}body.exporting{{background:#fff}}body.exporting .toolbar{{display:none}}body.exporting main{{margin:0;box-shadow:none}}
</style></head><body data-fanhan-resume-editor="v2"><div class="toolbar"><span class="status" data-editor-status role="status" aria-live="polite">修改会自动保存；先生成 PDF，再点击下载并发回当前对话</span><button type="button" data-export-pdf>生成 PDF</button><a class="download" data-download-pdf hidden target="_blank" rel="noopener">下载 PDF</a></div>
<main contenteditable="true" spellcheck="false" data-resume-content>{''.join(body)}</main>
<script src=".fanhan-assets/html2pdf.bundle.min.js"></script><script src=".fanhan-assets/resume-editor.js?v={editor_version}"></script><script>FanhanResumeEditor.install();</script></body></html>
"""


def install_editor_assets(outbox: Path) -> None:
    source = Path(__file__).resolve().parent.parent / "assets"
    target = outbox / ".fanhan-assets"
    target.mkdir(parents=True, exist_ok=True)
    for name in EDITOR_ASSETS:
        asset = source / name
        if not asset.is_file():
            raise RuntimeError(f"缺少简历编辑器资源：{name}")
        shutil.copy2(asset, target / name)


def accept_exported_pdf(source_path: Path, html_path: Path) -> dict:
    source = source_path.expanduser().resolve()
    editable = html_path.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".pdf":
        raise ValueError("请选择从简历编辑器导出的 PDF")
    data = source.read_bytes()
    if not 0 < len(data) <= MAX_PDF_BYTES or not data.startswith(b"%PDF-"):
        raise ValueError("PDF 必须有效且不超过 10 MB")
    if b"jsPDF" not in data:
        raise ValueError("PDF 不是内置 HTML 编辑器的原始导出文件；禁止重新生成替代文件")
    if (not editable.is_file() or editable.suffix.lower() != ".html"
            or editable.parent.name != "outbox"
            or editable.parent.parent.name != ".fanhan-job-agent"):
        raise ValueError("缺少 .fanhan-job-agent/outbox/ 下的同名可编辑 HTML")
    page = editable.read_text(encoding="utf-8")
    if ('contenteditable="true"' not in page
            or not any(f'data-fanhan-resume-editor="v{version}"' in page for version in (2, 3))
            or "html2pdf.bundle.min.js" not in page
            or "resume-editor.js" not in page):
        raise ValueError("HTML 不是内置简历编辑器生成的文件")

    output = editable.with_suffix(".pdf")
    replaced = output.exists() and output != source
    if output != source:
        temporary = output.with_suffix(".pdf.tmp")
        temporary.write_bytes(data)
        temporary.chmod(0o600)
        temporary.replace(output)
    if sha256(output) != hashlib.sha256(data).hexdigest():
        raise RuntimeError("接收后的 PDF 与用户上传文件不一致")
    return {
        "status": "pdf_accepted",
        "pdf_path": str(output),
        "pdf_sha256": sha256(output),
        "replaced_existing": replaced,
    }


def render(profile_path: Path, proposal_path: Path, output_path: Path) -> None:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
    sections, changes, consultation = validate(profile, proposal)
    original = resume_path(profile, profile_path).resolve()
    if not original.is_file():
        raise ValueError("原始简历不存在")
    output = output_path.resolve()
    if (output.suffix.lower() != ".html" or output.parent.name != "outbox"
            or output.parent.parent.name != ".fanhan-job-agent"):
        raise ValueError("第一份候选人可见成稿必须是 .fanhan-job-agent/outbox/ 下的新 HTML 文件")
    if output == original:
        raise ValueError("成稿不能覆盖原始简历")
    if output.stem != proposal["artifact_stem"]:
        raise ValueError("输出文件名必须与 artifact_stem 一致")

    original_hash = sha256(original)
    editor = Path(__file__).resolve().parent.parent / "assets" / "resume-editor.js"
    rendered = render_html(output.stem, sections, sha256(editor)[:12])
    output.parent.mkdir(parents=True, exist_ok=True)
    install_editor_assets(output.parent)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(rendered)
    if sha256(original) != original_hash:
        output.unlink(missing_ok=True)
        raise RuntimeError("原始简历在生成过程中发生变化，已删除成稿")


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        original = root / "Rokid旧简历.pdf"
        original.write_bytes(b"%PDF-original")
        career_document = root / "职业经历.md"
        career_document.write_text("# 职业经历\n", encoding="utf-8")
        profile_path = root / "profile.json"
        proposal_path = root / "proposal.json"
        output = root / ".fanhan-job-agent" / "outbox" / "张三-Example-AI产品经理-20260818-v1.html"
        profile_path.write_text(json.dumps({
            "schema_version": "fanhan-career-profile-v1",
            "resume": {"path": str(original)},
            "identity": {"name": "张三"},
            "career_document": {"path": str(career_document)},
        }), encoding="utf-8")
        proposal = {
            "schema_version": "fanhan-tailored-material-v1",
            "job": {"id": "job-1", "company": "Example", "title": "AI 产品经理"},
            "artifact_stem": "张三-Example-AI产品经理-20260818-v1",
            "consultation": {
                "status": "completed",
                "questions": [{
                    "id": "question-1",
                    "question": "你亲自推动了哪个关键交付？",
                    "jd_basis": ["JD 要求端到端交付"],
                    "profile_basis": ["职业经历.md 中的 AI 项目"],
                    "answer_summary": "候选人确认自己负责验收闭环。",
                    "confirmed": True,
                    "used_in_change_ids": ["change-2"],
                }],
            },
            "sections": [{
                "heading": "相关经历", "content": "负责有证据的 AI 产品交付。",
                "change_ids": ["change-1", "change-2"],
            }],
            "changes": [
                {
                    "id": "change-1", "type": "rewrite", "summary": "突出 AI 产品交付",
                    "jd_basis": ["JD 要求 AI 产品经验"], "fact_evidence": ["简历第 1 页"],
                    "confirmation": "not_required",
                },
                {
                    "id": "change-2", "type": "fact_addition", "summary": "补充交付结果",
                    "jd_basis": ["JD 要求结果证据"], "fact_evidence": ["候选人明确回答"],
                    "confirmation": "pending",
                },
            ],
        }
        proposal_path.write_text(json.dumps(proposal, ensure_ascii=False), encoding="utf-8")
        try:
            render(profile_path, proposal_path, output)
            raise AssertionError("未确认事实不应生成成稿")
        except ValueError as error:
            assert "未经候选人确认" in str(error)
        assert not output.exists()

        proposal["changes"][1].update(confirmation="confirmed", confirmed_at="2026-08-18T00:00:00Z")
        proposal_without_consultation = json.loads(json.dumps(proposal, ensure_ascii=False))
        proposal_without_consultation.pop("consultation")
        proposal_path.write_text(json.dumps(proposal_without_consultation, ensure_ascii=False), encoding="utf-8")
        try:
            render(profile_path, proposal_path, output)
            raise AssertionError("未完成针对性咨询不应生成成稿")
        except ValueError as error:
            assert "针对性咨询" in str(error)
        assert not output.exists()

        proposal_path.write_text(json.dumps(proposal, ensure_ascii=False), encoding="utf-8")
        before = sha256(original)
        render(profile_path, proposal_path, output)
        assert sha256(original) == before
        page = output.read_text(encoding="utf-8")
        assert "contenteditable=\"true\"" in page and 'data-fanhan-resume-editor="v2"' in page
        assert "先生成 PDF，再点击下载并发回当前对话" in page
        assert "data-download-pdf" in page and ">生成 PDF</button>" in page
        assert re.search(r'resume-editor\.js\?v=[0-9a-f]{12}', page)
        assert "window.print()" not in page and "html2pdf.bundle.min.js" in page
        assert all((output.parent / ".fanhan-assets" / name).is_file() for name in EDITOR_ASSETS)
        assert "<title>张三-Example-AI产品经理-20260818-v1</title>" in page
        markdown = output.with_suffix(".md")
        try:
            render(profile_path, proposal_path, markdown)
            raise AssertionError("第一份成稿不应允许 Markdown 绕过可编辑 HTML")
        except ValueError as error:
            assert "HTML" in str(error)
        wrong_name = root / ".fanhan-job-agent" / "outbox" / "张三-Rokid-AI产品经理-20260818-v1.html"
        try:
            render(profile_path, proposal_path, wrong_name)
            raise AssertionError("不应沿用旧目标公司文件名")
        except ValueError as error:
            assert "artifact_stem" in str(error)
        try:
            render(profile_path, proposal_path, output)
            raise AssertionError("不应覆盖已有成稿")
        except FileExistsError:
            pass

        output.write_text(page.replace('data-fanhan-resume-editor="v2"', 'data-fanhan-resume-editor="v3"'), encoding="utf-8")
        downloaded = root / "Downloads" / output.with_suffix(".pdf").name
        downloaded.parent.mkdir()
        downloaded.write_bytes(b"%PDF-1.4\n% jsPDF 4.0.0\nfirst edit")
        accepted = accept_exported_pdf(downloaded, output)
        accepted_path = Path(accepted["pdf_path"])
        assert accepted_path.read_bytes() == downloaded.read_bytes()
        downloaded.write_bytes(b"%PDF-1.4\n% jsPDF 4.0.0\nsecond edit")
        accepted = accept_exported_pdf(downloaded, output)
        assert accepted["replaced_existing"] is True
        assert accepted_path.read_bytes() == downloaded.read_bytes()
        downloaded.write_bytes(b"%PDF-1.4\n% HeadlessChrome Skia/PDF\nstale html")
        try:
            accept_exported_pdf(downloaded, output)
            raise AssertionError("禁止用旧 HTML 重新生成 PDF 替换用户导出文件")
        except ValueError as error:
            assert "禁止重新生成" in str(error)
    print("material_gate self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", nargs="?", help="职业档案 JSON 路径")
    parser.add_argument("proposal", nargs="?", help="定制提案 JSON 路径")
    parser.add_argument("output", nargs="?", help=".fanhan-job-agent/outbox/ 下的 HTML 输出路径")
    parser.add_argument("--accept-exported-pdf", nargs=2, metavar=("EXPORTED_PDF", "HTML"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.accept_exported_pdf:
        print(json.dumps(accept_exported_pdf(
            Path(args.accept_exported_pdf[0]), Path(args.accept_exported_pdf[1]),
        ), ensure_ascii=False, indent=2))
        return
    if not args.profile or not args.proposal or not args.output:
        parser.error("请提供职业档案、定制提案和输出路径")
    output = Path(args.output).expanduser()
    render(
        Path(args.profile).expanduser().resolve(),
        Path(args.proposal).expanduser().resolve(),
        output,
    )
    print(json.dumps({
        "status": "html_ready",
        "html_path": str(output.resolve()),
        "next_action": "立即展示这个 HTML，并只提示用户：检查或修改后点击生成 PDF，再点击下载 PDF，并把文件重新发回当前对话；收到回传前不得继续。",
        "pdf_ready": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
