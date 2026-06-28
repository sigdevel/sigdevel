#!/usr/bin/env python3
"""Render Openwall oss-security CVE links into a clickable Markdown list."""

from __future__ import annotations

import argparse
import html
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SUBJECT_RE = re.compile(
    r"Subject:\s*(.+?)(?:\n\s*\n|\r?\n(?:Date|From|To|Message-ID):|$)",
    re.IGNORECASE | re.DOTALL,
)
CVE_RE = re.compile(r"CVE-\d{4}-\d{4,7}", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
README_START = "<!-- OPENWALL-CVE-LIST:START -->"
README_END = "<!-- OPENWALL-CVE-LIST:END -->"


@dataclass(frozen=True)
class CvePost:
    url: str
    subject: str
    cves: tuple[str, ...]


def load_urls(path: Path) -> list[str]:
    urls: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def fetch_text(url: str, timeout: int) -> str:
    request = Request(url, headers={"User-Agent": "sigdevel-cve-list/1.0"})
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


def markdown_link(label: str, url: str) -> str:
    escaped_label = label.replace("[", "\\[").replace("]", "\\]")
    escaped_url = url.replace(")", "%29")
    return f"[{escaped_label}]({escaped_url})"


def render_markdown(posts: list[CvePost]) -> str:
    lines = ["### Openwall CVE Watch", ""]
    if not posts:
        lines.append("_No Openwall links configured._")
        return "\n".join(lines) + "\n"

    for post in posts:
        cve_labels = post.cves or ("CVE not found",)
        cve_links = ", ".join(markdown_link(cve, post.url) for cve in cve_labels)
        subject = post.subject.replace("|", "\\|")
        lines.append(f"- {cve_links} — {subject}")
    return "\n".join(lines) + "\n"


def write_markdown(posts: list[CvePost], output: Path) -> str:
    markdown = render_markdown(posts)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    return markdown


def update_readme(readme_path: Path, markdown: str) -> None:
    readme = readme_path.read_text(encoding="utf-8")
    block = f"{README_START}\n{markdown.rstrip()}\n{README_END}"

    if README_START in readme and README_END in readme:
        pattern = re.compile(f"{re.escape(README_START)}.*?{re.escape(README_END)}", re.DOTALL)
        updated = pattern.sub(block, readme)
    else:
        updated = readme.rstrip() + "\n\n" + block + "\n"

    readme_path.write_text(updated, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/openwall-cve-links.txt"))
    parser.add_argument("--output", type=Path, default=Path("generated/openwall-cve-watch.md"))
    parser.add_argument("--readme", type=Path, default=Path("README.md"))
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--skip-readme", action="store_true")
    args = parser.parse_args()

    urls = load_urls(args.input)
    posts = collect_posts(urls, args.timeout)
    markdown = write_markdown(posts, args.output)
    if not args.skip_readme:
        update_readme(args.readme, markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
