#!/usr/bin/env python3
"""Render Openwall oss-security CVE links into a GitHub-friendly SVG card."""

from __future__ import annotations

import argparse
import html
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SUBJECT_RE = re.compile(r"Subject:\s*(.+?)(?:\n\s*\n|\r?\n(?:Date|From|To|Message-ID):|$)", re.IGNORECASE | re.DOTALL)
CVE_RE = re.compile(r"CVE-\d{4}-\d{4,7}", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class CvePost:
    url: str
    subject: str
    cves: tuple[str, ...]


def load_urls(path: Path) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or not line.startswith(("http://", "https://")) or line in seen:
            continue
        seen.add(line)
        urls.append(line)
    return urls


def fetch_text(url: str, timeout: int) -> str:
    request = Request(url, headers={"User-Agent": "sigdevel-cve-card/1.0"})
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def normalize_subject(raw: str) -> str:
    subject = html.unescape(raw)
    subject = TAG_RE.sub("", subject)
    subject = subject.replace("\r", "\n")
    subject = " ".join(line.strip() for line in subject.splitlines())
    return WS_RE.sub(" ", subject).strip()


def extract_subject(page_text: str) -> str:
    text = html.unescape(page_text)
    match = SUBJECT_RE.search(text)
    if match:
        return normalize_subject(match.group(1))

    title_match = re.search(r"<title>(.*?)</title>", page_text, re.IGNORECASE | re.DOTALL)
    if title_match:
        return normalize_subject(title_match.group(1))

    return "Subject unavailable"


def extract_cves(subject: str) -> tuple[str, ...]:
    seen: set[str] = set()
    cves: list[str] = []
    for match in CVE_RE.findall(subject):
        cve = match.upper()
        if cve not in seen:
            seen.add(cve)
            cves.append(cve)
    return tuple(cves)


def shorten(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def collect_posts(urls: list[str], timeout: int) -> list[CvePost]:
    posts: list[CvePost] = []
    failures: list[str] = []
    for url in urls:
        try:
            page_text = fetch_text(url, timeout)
            subject = extract_subject(page_text)
            cves = extract_cves(subject)
            posts.append(CvePost(url=url, subject=subject, cves=cves))
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            failures.append(f"{url}: {exc}")
            posts.append(CvePost(url=url, subject="Subject unavailable", cves=()))

    if failures:
        print("Warnings while fetching Openwall posts:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
    return posts


def escape_markdown_cell(text: str) -> str:
    return text.replace("|", r"\|").replace("\n", " ")


def with_minimum_cell_height(cell: str, visible_text: str, min_chars: int = 90) -> str:
    """Add a blank visual line to short markdown cells for consistent row height."""
    if len(visible_text) >= min_chars or cell.endswith("<br>&nbsp;"):
        return cell
    return f"{cell}<br>&nbsp;"


def render_markdown_table(posts: list[CvePost]) -> str:
    rows = ["| CVE | Description |", "| --- | --- |"]
    for post in posts:
        subject = escape_markdown_cell(post.subject)
        cves = post.cves or ("—",)
        for cve in cves:
            if cve == "—":
                cve_cell = cve
            else:
                cve_cell = f"[{cve}]({post.url})"
            description_cell = with_minimum_cell_height(f"[{subject}]({post.url})", subject)
            rows.append(f"| {cve_cell} | {description_cell} |")
    return "\n".join(rows) + "\n"


def update_readme_table(readme: Path, posts: list[CvePost]) -> None:
    content = readme.read_text(encoding="utf-8")
    table = render_markdown_table(posts)
    table_re = re.compile(
        r"^\| CVE \| Description \|\n\| --- \| --- \|\n(?:^\| .* \| .* \|\n?)*",
        re.MULTILINE,
    )
    updated, replacements = table_re.subn(table, content, count=1)
    if replacements != 1:
        raise ValueError(f"Could not find CVE table in {readme}")
    readme.write_text(updated, encoding="utf-8")


def render_svg(posts: list[CvePost], output: Path) -> None:
    width = 700
    height = 82

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<style>* { font-family: 'Segoe UI', Ubuntu, 'Helvetica Neue', Sans-Serif; } .title { font-size: 22px; fill: #58a6ff; font-weight: 600; } .meta { font-size: 12px; fill: #8b949e; } .metric-number { font-size: 20px; fill: #f0f6fc; font-weight: 700; } .cve { font-size: 14px; fill: #f0f6fc; font-weight: 600; } .subject { font-size: 13px; fill: #8b949e; }</style>",
        '<rect x="1" y="1" rx="5" ry="5" height="99%" width="99.714%" stroke="#2e343b" stroke-width="1" fill="#0d1117"/>',
        '<text x="30" y="38" class="title">Openwall CVE Watch</text>',
        f'<text x="30" y="58" class="meta"><tspan class="metric-number">{len(posts)}</tspan> tracked oss-security post(s)</text>',
    ]

    lines.append(f'<text x="30" y="{height - 10}" class="meta">Source: Openwall oss-security Subject headers</text>')
    lines.append("</svg>")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/openwall-cve-links.txt"))
    parser.add_argument("--output", type=Path, default=Path("generated/openwall-cve-watch.svg"))
    parser.add_argument("--readme", type=Path, default=Path("README.md"))
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    urls = load_urls(args.input)
    posts = collect_posts(urls, args.timeout)
    render_svg(posts, args.output)
    update_readme_table(args.readme, posts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
