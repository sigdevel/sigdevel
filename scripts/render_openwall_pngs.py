#!/usr/bin/env python3
"""Generate PNG/TXT cards for Openwall, NIST/NVD and CVE.org sources."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit

from PIL import Image, ImageDraw, ImageFont

from render_openwall_cves import (
    cve_record_json_url, extract_issue_subject, extract_record_cve,
    extract_record_subject, fetch_text, format_issue_subject, load_sources,
    parse_cve_record,
)

FIELDS = ('Subject', 'Product', 'Affected', 'PoC', 'References', 'Reporter')
PNG_FIELDS = ('Subject', 'Product', 'Affected', 'Reporter')


class MessageParser(HTMLParser):
    """Read message text only; decode entities after stripping HTML tags."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_pre = False
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == 'pre':
            self.in_pre = True
        elif tag == 'br' and self.in_pre:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag == 'pre':
            self.in_pre = False
            self.parts.append('\n')

    def handle_data(self, data):
        if self.in_pre:
            self.parts.append(data)


@dataclass(frozen=True)
class Card:
    url: str
    fields: dict[str, str]
    issue_url: str | None = None


def parse_card(page: str, url: str) -> Card:
    parser = MessageParser()
    parser.feed(page)
    sections: dict[str, list[str]] = {}
    current = None
    for line in ''.join(parser.parts).splitlines():
        match = re.match(r'^([A-Za-z][A-Za-z0-9 ._/-]*):[ \t]*(.*)$', line)
        if match:
            current = match[1].lower()
            sections.setdefault(current, []).append(match[2])
        elif current and (not line.strip() or line[:1].isspace()):
            sections[current].append(line.strip())
        else:
            # Signatures and unindented body text do not belong to a field.
            current = None
    fields = {}
    for name in FIELDS:
        lines = sections.get(name.lower(), [])
        if name in ('PoC', 'References'):
            # Keep every URL, excluding trailing punctuation and duplicates.
            urls = re.findall(r'https?://[^\s<>]+', '\n'.join(lines))
            fields[name] = '\n'.join(dict.fromkeys(u.rstrip('.,;)') for u in urls))
        else:
            fields[name] = ' '.join(' '.join(lines).split())
    if not fields['PoC']:
        # Some posts list the author's PoC repository only under References.
        fields['PoC'] = '\n'.join(
            url for url in fields['References'].splitlines()
            if urlsplit(url).hostname == 'github.com'
            and urlsplit(url).path.startswith('/sigdevel/pocs/')
        )
    if not fields['Subject']:
        raise ValueError(f'No message Subject found in {url}')
    return Card(url, fields)


def parse_record_card(record_text: str, url: str, issue: str | None = None,
                      issue_page: str | None = None) -> Card:
    cve = extract_record_cve(url)
    if not cve:
        raise ValueError(f'Unsupported CVE record URL: {url}')
    record = parse_cve_record(record_text, cve)
    cna = record['containers']['cna']
    fields = dict.fromkeys(FIELDS, '')
    if issue:
        if issue_page is None:
            raise ValueError(f'GitHub issue title unavailable: {issue}')
        fields['Subject'] = format_issue_subject(url, issue, extract_issue_subject(issue_page))
    else:
        fields['Subject'] = extract_record_subject(record_text, cve)

    products, affected = [], []
    for item in cna.get('affected', []):
        vendor, product = item.get('vendor', ''), item.get('product', '')
        name = f'{vendor}/{product}' if vendor and product and vendor.lower() != product.lower() else product or vendor
        if name and name not in products:
            products.append(name)
        versions = []
        for version in item.get('versions', []):
            text = version.get('version', '')
            if version.get('lessThan'):
                text += f' to < {version["lessThan"]}'
            if version.get('lessThanOrEqual'):
                text += f' to <= {version["lessThanOrEqual"]}'
            if version.get('status'):
                text += f' ({version["status"]})'
            if text.strip():
                versions.append(text.strip())
        if item.get('defaultStatus'):
            versions.append(f'default: {item["defaultStatus"]}')
        if versions:
            affected.append(f'{name}: {"; ".join(versions)}' if name else '; '.join(versions))
    fields['Product'] = '; '.join(products)
    fields['Affected'] = '\n'.join(affected)
    fields['Reporter'] = '; '.join(dict.fromkeys(
        credit['value'] for credit in cna.get('credits', [])
        if credit.get('type') in ('finder', 'reporter') and credit.get('value')
    ))

    references = [url, *([issue] if issue else []), cve_record_json_url(cve)]
    poc = []
    for container in [cna, *record['containers'].get('adp', [])]:
        for reference in container.get('references', []):
            link = reference.get('url', '')
            if urlsplit(link).scheme not in ('http', 'https'):
                continue
            references.append(link)
            if ('exploit' in reference.get('tags', [])
                    or (urlsplit(link).hostname == 'github.com'
                        and urlsplit(link).path.startswith('/sigdevel/pocs/'))):
                poc.append(link)
    fields['PoC'] = '\n'.join(dict.fromkeys(poc))
    fields['References'] = '\n'.join(dict.fromkeys(references))
    return Card(url, fields, issue)


def unavailable_record_card(url: str, issue: str | None = None,
                            issue_page: str | None = None) -> Card:
    """Keep an explicitly listed CVE visible when its public JSON returns 404."""
    cve = extract_record_cve(url)
    if not cve:
        raise ValueError(f'Unsupported CVE record URL: {url}')
    fields = dict.fromkeys(FIELDS, '')
    subject = (format_issue_subject(url, issue, extract_issue_subject(issue_page))
               if issue and issue_page is not None else cve)
    fields['Subject'] = f'{subject}: Public CVE record unavailable (HTTP 404)'
    fields['References'] = '\n'.join([url, *([issue] if issue else []), cve_record_json_url(cve)])
    return Card(url, fields, issue)


def card_filename(url: str, issue: str | None = None) -> str:
    cve = extract_record_cve(url)
    if cve:
        provider = 'nvd' if urlsplit(url).hostname == 'nvd.nist.gov' else 'cve'
        identity = sha256(f'{url}\0{issue or ""}'.encode()).hexdigest()[:12]
        return f'{provider}-{cve.lower()}-{identity}.png'
    match = re.fullmatch(r'/lists/oss-security/(\d{4})/(\d{2})/(\d{2})/(\d+)/?', urlsplit(url).path)
    if not match:
        raise ValueError(f'Unsupported Openwall post URL: {url}')
    return 'openwall-' + '-'.join(match.groups()) + '.png'


def wrap_text(text: str, font, width: int) -> list[str]:
    """Wrap by measured pixels, including URLs longer than a whole line."""
    result = []
    for paragraph in text.splitlines():
        line = ''
        for word in paragraph.split():
            candidate = f'{line} {word}' if line else word
            if font.getlength(candidate) <= width:
                line = candidate
                continue
            if line:
                result.append(line)
            line = ''
            for char in word:
                if line and font.getlength(line + char) > width:
                    result.append(line)
                    line = ''
                line += char
        result.append(line)
    return result


def render_png(card: Card, output: Path) -> None:
    width, padding = 1200, 44
    # Pillow's bundled scalable font avoids system-font dependencies.
    body = ImageFont.load_default(size=22)
    label = ImageFont.load_default(size=18)
    title = ImageFont.load_default(size=29)
    layout = []
    y = 84
    for name in PNG_FIELDS:
        font = title if name == 'Subject' else body
        lines = wrap_text(card.fields[name] or 'Not provided in source', font, width - 2 * padding)
        layout.append((name, lines, font, y))
        y += 30 + len(lines) * (38 if name == 'Subject' else 30) + 24
    source = wrap_text(card.url, label, width - 2 * padding)
    height = y + 38 + len(source) * 26 + padding
    image = Image.new('RGB', (width, height), '#0d1117')
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((1, 1, width - 2, height - 2), radius=14, outline='#30363d', width=2)
    provider = {'nvd.nist.gov': 'NIST / NVD', 'www.cve.org': 'CVE.ORG', 'cve.org': 'CVE.ORG'}.get(
        urlsplit(card.url).hostname, 'OPENWALL / OSS-SECURITY')
    draw.text((padding, 30), provider, font=label, fill='#58a6ff')
    for name, lines, font, top in layout:
        draw.text((padding, top), name.upper(), font=label, fill='#8b949e')
        for i, line in enumerate(lines):
            draw.text((padding, top + 30 + i * (38 if name == 'Subject' else 30)), line, font=font, fill='#f0f6fc')
    draw.line((padding, y, width - padding, y), fill='#30363d', width=1)
    for i, line in enumerate(source):
        draw.text((padding, y + 22 + i * 26), line, font=label, fill='#8b949e')
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format='PNG')


def render_index_entry(card: Card) -> str:
    filename = card_filename(card.url, card.issue_url)
    stem = Path(filename).stem
    lines = [f'## {escape(card.fields["Subject"])}', '', f'[![CVE card]({stem}/{filename})]({card.issue_url or card.url})', '', f'[PoC and References (TXT)]({stem}/{stem}.txt)', '', f'Source: <{card.url}>', '']
    if card.issue_url:
        lines += [f'Issue: <{card.issue_url}>', '']
    for name in ('PoC', 'References'):
        lines += [f'**{name}:**', '']
        lines += [f'- <{url}>' for url in card.fields[name].splitlines()] or ['Not provided in source.']
        lines.append('')
    return '\n'.join(lines)


def render_text(card: Card) -> str:
    """Export only PoC and reference links, without visual line wrapping."""
    sections = []
    for name in ('PoC', 'References'):
        sections.append(f'{name}:\n{card.fields[name] or "Not provided in source"}')
    return '\n\n'.join(sections) + '\n'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('data/openwall-cve-links.txt'))
    parser.add_argument('--output-dir', type=Path, default=Path('generated/openwall-cves'))
    parser.add_argument('--timeout', type=int, default=20)
    parser.add_argument('--force', action='store_true', help='Fetch and regenerate existing PNG/TXT pairs too')
    args = parser.parse_args()
    index_path = args.output_dir / 'README.md'
    old_index = index_path.read_text(encoding='utf-8') if index_path.is_file() else ''
    cached_entries = {}
    for entry in re.split(r'(?=^## )', old_index, flags=re.MULTILINE):
        source = re.search(r'^Source: <([^>]+)>$', entry, re.MULTILINE)
        if source:
            issue = re.search(r'^Issue: <([^>]+)>$', entry, re.MULTILINE)
            cached_entries[(source[1], issue[1] if issue else None)] = entry.strip()
    cards = []
    entries = []
    skipped = 0
    # Fetch new/incomplete sources first; transient errors must not alter outputs.
    for url, issue in load_sources(args.input):
        try:
            filename = card_filename(url, issue)
            stem = Path(filename).stem
            directory = args.output_dir / stem
            if not args.force and (directory / filename).is_file() and (directory / f'{stem}.txt').is_file():
                skipped += 1
                # Preserve the existing title and clickable links without fetching.
                # If the index was deleted, still link the retained materials.
                entries.append(cached_entries.get((url, issue)) or render_index_entry(Card(url, {
                    'Subject': stem, 'PoC': '', 'References': '',
                }, issue)).strip())
                continue
            cve = extract_record_cve(url)
            if cve:
                issue_page = fetch_text(issue, args.timeout) if issue else None
                try:
                    record_text = fetch_text(cve_record_json_url(cve), args.timeout)
                except HTTPError as exc:
                    if exc.code != 404:
                        raise
                    print(f'Warning: public record unavailable for {cve} (HTTP 404)', file=sys.stderr)
                    card = unavailable_record_card(url, issue, issue_page)
                else:
                    card = parse_record_card(record_text, url, issue, issue_page)
            else:
                card = parse_card(fetch_text(url, args.timeout), url)
            cards.append(card)
            entries.append(render_index_entry(card).strip())
        except (OSError, ValueError) as exc:
            print(f'Failed to render {url}: {exc}', file=sys.stderr)
            return 1
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for card in cards:
        filename = card_filename(card.url, card.issue_url)
        stem = Path(filename).stem
        directory = args.output_dir / stem
        render_png(card, directory / filename)
        (directory / f'{stem}.txt').write_text(render_text(card), encoding='utf-8')
    index = '# CVE cards\n\nOne card per source entry (Openwall, NIST/NVD or CVE.org). PNG links are plain text; use the clickable links below.\n\n'
    index += '\n\n'.join(entries) + '\n'
    if index != old_index:
        index_path.write_text(index, encoding='utf-8')
    # Migrate only the old flat PNGs for posts successfully generated above.
    for card in cards:
        (args.output_dir / card_filename(card.url, card.issue_url)).unlink(missing_ok=True)
    print(f'Generated {len(cards)} PNG cards; skipped {skipped} existing pairs in {args.output_dir}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
