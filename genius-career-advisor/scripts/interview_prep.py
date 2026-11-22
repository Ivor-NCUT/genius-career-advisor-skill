#!/usr/bin/env python3
"""Build one interview-prep Markdown file per job from confirmed inputs.

The model fills the structured fields. This script only assembles and revises
the Markdown. It does not invent interview rounds, scores, or missing facts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import render_interview
import workspace


MODULES = (
    "1. 公司与岗位简报",
    "2. JD 与经历对应表",
    "3. 重点问题及追问",
    "4. 练习与反馈",
    "5. 反问清单",
)
NOT_STARTED = "尚未开始练习。没有真实回答，因此这里不生成模拟反馈、分数或进步记录。"
HEADING = re.compile(r"^##\s+(\d+\.\s+.+)$", re.M)


def job_key(job_id: str = "", job_url: str = "", company: str = "", title: str = "") -> str:
    url = str(job_url or "").strip().rstrip("/").casefold()
    if url:
        basis = "url:" + url
    elif str(job_id or "").strip():
        source = str(company or "").strip()
        if not source:
            raise ValueError("job_id_requires_source")
        basis = "id:" + source + "|" + job_id.strip()
    elif str(company or "").strip() and str(title or "").strip():
        basis = "name:" + company.strip() + "|" + title.strip()
    else:
        raise ValueError("job_key_basis_required")
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def prep_dir(workspace_dir: Path, key: str) -> Path:
    root = workspace_dir.expanduser().resolve()
    if not workspace.is_workspace_name(root.name):
        raise ValueError("interview_prep_must_be_in_workspace")
    return root / "interview" / key


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?%?", text or ""))


def _require(value: str, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field}_required")
    return text


def _facts_block(facts: list[dict]) -> str:
    if not facts:
        return "待确认：还没有可核验的公司或岗位事实。未确认前不写具体轮次。"
    lines = []
    for fact in facts:
        status = fact.get("status") or "未确认"
        if status not in {"已核验", "未确认", "推测"}:
            raise ValueError("fact_status_invalid")
        source = _require(fact.get("source"), "fact_source")
        date = _require(fact.get("date"), "fact_date")
        text = _require(fact.get("text"), "fact_text")
        lines.append(f"- [{status}] {text}（来源：{source}；日期：{date}）")
    return "\n".join(lines)


def _mapping_block(rows: list[dict]) -> str:
    if not rows:
        raise ValueError("mapping_required")
    lines = ["| JD 要求 | 本人经历与来源 | 个人贡献 | 证据缺口 |", "| --- | --- | --- | --- |"]
    for row in rows[:5]:
        experience = _require(row.get("experience"), "mapping_experience")
        contribution = _require(row.get("contribution"), "mapping_contribution")
        requirement = _require(row.get("requirement"), "mapping_requirement")
        gap = str(row.get("gap") or "待补充").replace("|", "/")
        lines.append("| " + " | ".join(item.replace("|", "/") for item in (requirement, experience, contribution, gap)) + " |")
    return "\n".join(lines)


def _questions_block(questions: list[dict]) -> str:
    if not questions:
        raise ValueError("questions_required")
    lines = []
    for index, item in enumerate(questions[:10], start=1):
        link = _require(item.get("jd_or_experience"), "question_link")
        prompt = _require(item.get("prompt"), "question_prompt")
        points = str(item.get("points") or "只用已确认事实回答。").strip()
        followups = str(item.get("followups") or "证据含糊时再追问本人具体负责的部分。").strip()
        lines.append(f"{index}. {prompt}\n   - 关联：{link}\n   - 回答要点：{points}\n   - 可能追问：{followups}")
    return "\n".join(lines)


def feedback_block(practice: dict | None, allowed_text: str) -> str:
    if not practice:
        return NOT_STARTED
    answer = _require(practice.get("answer_summary"), "answer_summary")
    cited = _require(practice.get("cited_problem"), "cited_problem")
    if cited not in answer:
        raise ValueError("feedback_must_cite_the_answer")
    move = _require(practice.get("priority_move"), "priority_move")
    reference = _require(practice.get("reference"), "reference")
    invented = _numbers(reference) - _numbers(f"{answer}\n{allowed_text}")
    if invented:
        raise ValueError("feedback_must_not_invent_numbers")
    question = _require(practice.get("question"), "question")
    session = str(practice.get("session_id") or "").strip()
    index = f"练习索引：{session}" if session else "练习索引：已写入 candidate-memory.json 的本条记录"
    return "\n".join((
        f"问题：{question}",
        f"回答摘要：{answer}",
        f"这次回答里的具体问题：{cited}",
        f"优先改进：{move}",
        f"参考表达：{reference}",
        index,
        "分数只在 candidate-memory.json 里保留兼容，不在这里解释为录取概率。",
    ))


def render_markdown(spec: dict) -> str:
    company = _require(spec.get("company"), "company")
    title = _require(spec.get("title"), "title")
    key = job_key(spec.get("job_id", ""), spec.get("job_url", ""), company, title)
    interview_round = str(spec.get("interview_round") or "").strip() or "待确认"
    if re.search(r"第[一二三123]面|一面|二面|三面", interview_round) and spec.get("round_confirmed") is not True:
        raise ValueError("interview_round_must_not_be_invented")
    allowed = "\n".join(
        str(row.get("experience") or "") + "\n" + str(row.get("contribution") or "")
        for row in spec.get("mappings") or []
    )
    parts = [
        f"# {company} · {title}",
        "",
        f"- 岗位键：{key}",
        f"- 面试轮次：{interview_round}",
        "",
        f"## {MODULES[0]}",
        "",
        str(spec.get("brief") or "待确认：用已投递简历和 JD 补齐岗位任务后再写动机。").strip(),
        "",
        _facts_block(spec.get("facts") or []),
        "",
        f"## {MODULES[1]}",
        "",
        _mapping_block(spec.get("mappings") or []),
        "",
        f"## {MODULES[2]}",
        "",
        _questions_block(spec.get("questions") or []),
        "",
        f"## {MODULES[3]}",
        "",
        feedback_block(spec.get("practice"), allowed),
        "",
        f"## {MODULES[4]}",
        "",
    ]
    reverse = spec.get("reverse_questions") or [
        "这个岗位前三个月怎样算做得好？",
        "入职后第一项具体任务是什么？",
        "这个角色和哪些人一起做决定？",
    ]
    parts.append("\n".join(f"- {item}" for item in reverse))
    parts.append("")
    return "\n".join(parts)


def module_bodies(markdown: str) -> dict[str, str]:
    matches = list(HEADING.finditer(markdown))
    found = [match.group(1).strip() for match in matches]
    if found != list(MODULES):
        raise ValueError("prep_modules_missing")
    bodies = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        bodies[match.group(1).strip()] = markdown[start:end].strip()
    return bodies


def update_feedback(markdown: str, practice: dict, allowed_text: str) -> str:
    bodies = module_bodies(markdown)
    replacement = feedback_block(practice, allowed_text)
    if "尚未开始练习" in replacement:
        raise ValueError("practice_feedback_required")
    pattern = re.compile(r"(## " + re.escape(MODULES[3]) + r"\n\n)([\s\S]*?)(\n## " + re.escape(MODULES[4]) + r")")

    def _replace(match):
        return match.group(1) + replacement + match.group(3)

    updated, count = pattern.subn(_replace, markdown, count=1)
    if count != 1:
        raise ValueError("feedback_module_missing")
    new_bodies = module_bodies(updated)
    for name in MODULES:
        if name == MODULES[3]:
            continue
        if new_bodies[name] != bodies[name]:
            raise ValueError("feedback_update_changed_other_module")
    return updated


def write_pair(workspace_dir: Path, spec: dict) -> dict:
    key = job_key(spec.get("job_id", ""), spec.get("job_url", ""), spec.get("company", ""), spec.get("title", ""))
    directory = prep_dir(workspace_dir, key)
    directory.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown(spec)
    md_path = directory / "prep.md"
    html_path = directory / "prep.html"
    md_path.write_text(markdown, encoding="utf-8")
    render_interview.render_file(md_path, html_path)
    return {"job_key": key, "markdown": str(md_path), "html": str(html_path)}


def self_test() -> None:
    import tempfile
    base_jd = [
        {"requirement": "能把用户反馈收成可执行需求", "gap": "缺一次亲自推进的例子"},
    ]
    def spec(name, experience, contribution, job_url):
        row = dict(base_jd[0], experience=f"{experience}（来源：职业经历.md#{name}）", contribution=contribution)
        return {
            "company": "示例公司",
            "title": "AI 产品运营",
            "job_url": job_url,
            "brief": f"{name}准备的岗位简报",
            "facts": [{"text": "公开产品页写明面向创作者", "source": "https://example.com/product", "date": "2026-11-22", "status": "已核验"}],
            "mappings": [row],
            "questions": [{
                "prompt": f"讲一次{name}把反馈收成需求的经历",
                "jd_or_experience": experience,
                "points": contribution,
            }],
            "practice": None,
        }
    with tempfile.TemporaryDirectory() as directory:
        root_a = Path(directory) / "a" / ".天才职业顾问"
        root_b = Path(directory) / "b" / ".天才职业顾问"
        root_a.mkdir(parents=True)
        root_b.mkdir(parents=True)
        first = spec("甲", "甲做过社区反馈周报", "甲亲自把三条反馈改成需求", "https://example.com/jobs/a")
        second = spec("乙", "乙做过商家客服质检", "乙亲自重写了质检标准", "https://example.com/jobs/a")
        other = spec("甲", "甲做过社区反馈周报", "甲亲自把三条反馈改成需求", "https://example.com/jobs/b")
        other["title"] = "算法工程师"
        written_a = write_pair(root_a, first)
        written_b = write_pair(root_b, second)
        written_c = write_pair(root_a, other)
        assert written_a["job_key"] == written_b["job_key"]
        assert written_a["job_key"] != written_c["job_key"]
        md_a = Path(written_a["markdown"]).read_text(encoding="utf-8")
        md_b = Path(written_b["markdown"]).read_text(encoding="utf-8")
        md_c = Path(written_c["markdown"]).read_text(encoding="utf-8")
        assert "社区反馈周报" in md_a and "社区反馈周报" not in md_b
        assert "质检标准" in md_b and "质检标准" not in md_a
        feedback = module_bodies(md_a)["4. 练习与反馈"]
        assert feedback == NOT_STARTED
        assert "优先改进" not in feedback
        try:
            render_markdown(dict(first, interview_round="一面"))
            raise AssertionError("未确认的轮次不能写成一面")
        except ValueError as error:
            assert "invented" in str(error)
        updated = update_feedback(md_a, {
            "question": "讲一次甲把反馈收成需求的经历",
            "answer_summary": "我们做了这个项目，效果很好",
            "cited_problem": "我们做了这个项目",
            "priority_move": "改成甲亲自拆出的那三条反馈",
            "reference": "甲把社区里的三条反馈收成了一份需求。",
            "session_id": "practice-1",
        }, "甲做过社区反馈周报\n甲亲自把三条反馈改成需求")
        assert module_bodies(updated)["2. JD 与经历对应表"] == module_bodies(md_a)["2. JD 与经历对应表"]
        assert "我们做了这个项目" in module_bodies(updated)["4. 练习与反馈"]
        try:
            update_feedback(md_a, {
                "question": "讲一次经历",
                "answer_summary": "效果很好",
                "cited_problem": "效果很好",
                "priority_move": "补证据",
                "reference": "增长了 30%",
            }, "甲做过社区反馈周报")
            raise AssertionError("不能补造回答里没有的数字")
        except ValueError as error:
            assert "invent_numbers" in str(error)
        html = Path(written_a["html"]).read_text(encoding="utf-8")
        assert render_interview.visible_text(html) == render_interview.visible_text_from_markdown(md_a)
        assert 'href="#module-1"' in html and "<details" in html
        assert '<a href="https://example.com/product">' in html
        linked = render_interview.render_html("占位\n\n## 1. 公司与岗位简报\n\n见[产品页](https://example.com/note)\n\n## 2. JD 与经历对应表\n\n表\n\n## 3. 重点问题及追问\n\n题\n\n## 4. 练习与反馈\n\n尚未开始练习\n\n## 5. 反问清单\n\n问")
        assert '<a href="https://example.com/note">产品页</a>' in linked
        assert "<style>" not in md_a
        company_a = job_key("123", "https://jobs.a.example/positions/1", "甲公司", "运营")
        company_b = job_key("123", "https://jobs.b.example/positions/9", "乙公司", "算法")
        assert company_a != company_b
        assert job_key("123", "", "甲公司", "运营") != job_key("123", "", "乙公司", "算法")
        escaped = update_feedback(md_a, {
            "question": "怎么提取编号",
            "answer_summary": r"我用正则 \d+ 提取编号",
            "cited_problem": r"\d+",
            "priority_move": "说明编号来自哪一列",
            "reference": r"我用正则 \d+ 提取编号。",
        }, "甲做过社区反馈周报")
        assert r"我用正则 \d+ 提取编号" in module_bodies(escaped)["4. 练习与反馈"]
    print("interview_prep self-test: ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--spec", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.workspace or not args.spec:
        parser.error("请提供 --workspace 和 --spec")
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    print(json.dumps(write_pair(args.workspace, spec), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
