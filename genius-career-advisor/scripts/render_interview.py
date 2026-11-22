#!/usr/bin/env python3
"""Render a fixed interview-prep Markdown file into a readable HTML page.

This script does not generate or revise the preparation text.
"""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path


HEADING = re.compile(r"^##\s+(\d+)\.\s+(.+)$", re.M)


def _inline(text: str) -> str:
    escaped = html.escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)


def _blocks(markdown: str) -> str:
    chunks = re.split(r"\n\s*\n", markdown.strip())
    rendered = []
    for chunk in chunks:
        lines = chunk.splitlines()
        if lines and all(line.startswith("|") for line in lines):
            rows = [[_inline(cell.strip()) for cell in line.strip("|").split("|")] for line in lines if not re.match(r"^\|\s*---", line)]
            if not rows:
                continue
            head = "".join(f"<th>{cell}</th>" for cell in rows[0])
            body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows[1:])
            rendered.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
            continue
        if lines and all(re.match(r"^(\d+\.|-)\s+", line) for line in lines):
            items = "".join(f"<li>{_inline(re.sub(r'^(\d+\.|-)\s+', '', line))}</li>" for line in lines)
            tag = "ol" if lines[0][0].isdigit() else "ul"
            rendered.append(f"<{tag}>{items}</{tag}>")
            continue
        rendered.append(f"<p>{_inline(chunk).replace(chr(10), '<br>')}</p>")
    return "\n".join(rendered)


def render_html(markdown: str, title: str = "岗位面试准备") -> str:
    matches = list(HEADING.finditer(markdown))
    if len(matches) != 5:
        raise ValueError("prep_modules_missing")
    nav = []
    sections = []
    for index, match in enumerate(matches):
        number = match.group(1)
        name = match.group(2).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        anchor = f"module-{number}"
        nav.append(f'<a href="#{anchor}">{html.escape(number)}. {html.escape(name)}</a>')
        sections.append(
            f'<details id="{anchor}" open><summary>{html.escape(number)}. {html.escape(name)}</summary>'
            f'{_blocks(markdown[start:end])}</details>'
        )
    intro_end = matches[0].start()
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body{{margin:0;background:#f6f4ef;color:#222;font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:840px;margin:0 auto;padding:24px}}
nav{{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 20px}}
nav a{{color:#174ea6;text-decoration:none}}
details{{background:#fff;border:1px solid #e4e0d8;border-radius:8px;margin:0 0 12px;padding:8px 14px}}
summary{{cursor:pointer;font-weight:650}}
table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ddd;padding:6px;vertical-align:top;text-align:left}}
</style></head><body><main>
{_blocks(markdown[:intro_end])}
<nav>{''.join(nav)}</nav>
{''.join(sections)}
</main></body></html>
"""


def visible_text(page: str) -> str:
    text = re.sub(r"<style[\s\S]*?</style>", " ", page, flags=re.I)
    text = re.sub(r"<title[\s\S]*?</title>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())


def visible_text_from_markdown(markdown: str) -> str:
    return visible_text(render_html(markdown))


def render_file(source: Path, target: Path) -> None:
    markdown = source.read_text(encoding="utf-8")
    title = "岗位面试准备"
    heading = re.search(r"^#\s+(.+)$", markdown, re.M)
    if heading:
        title = heading.group(1).strip()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_html(markdown, title), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    render_file(Path(args.input), Path(args.output))


if __name__ == "__main__":
    main()
