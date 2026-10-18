#!/usr/bin/env python3
"""Generate one PNG and a linked Markdown index per unique Openwall post."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from PIL import Image, ImageDraw, ImageFont

from render_openwall_cves import fetch_text, load_urls

FIELDS = ('Subject', 'Product', 'Affected', 'PoC', 'References', 'Reporter')


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


def card_filename(url: str) -> str:
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
    for name in FIELDS:
        font = title if name == 'Subject' else body
        lines = wrap_text(card.fields[name] or 'Not provided in source', font, width - 2 * padding)
        layout.append((name, lines, font, y))
        y += 30 + len(lines) * (38 if name == 'Subject' else 30) + 24
    source = wrap_text(card.url, label, width - 2 * padding)
    height = y + 38 + len(source) * 26 + padding
    image = Image.new('RGB', (width, height), '#0d1117')
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((1, 1, width - 2, height - 2), radius=14, outline='#30363d', width=2)
    draw.text((padding, 30), 'OPENWALL / OSS-SECURITY', font=label, fill='#58a6ff')
    for name, lines, font, top in layout:
        draw.text((padding, top), name.upper(), font=label, fill='#8b949e')
        for i, line in enumerate(lines):
            draw.text((padding, top + 30 + i * (38 if name == 'Subject' else 30)), line, font=font, fill='#f0f6fc')
    draw.line((padding, y, width - padding, y), fill='#30363d', width=1)
    for i, line in enumerate(source):
        draw.text((padding, y + 22 + i * 26), line, font=label, fill='#8b949e')
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format='PNG')


def render_index(cards: list[Card]) -> str:
    lines = ['# Openwall CVE cards', '', 'One card per unique source URL. PNG links are plain text; use the clickable links below.', '']
    for card in cards:
        lines += [f'## {escape(card.fields["Subject"])}', '', f'[![Openwall CVE card]({card_filename(card.url)})]({card.url})', '', f'Source: <{card.url}>', '']
        for name in ('PoC', 'References'):
            lines += [f'**{name}:**', '']
            lines += [f'- <{url}>' for url in card.fields[name].splitlines()] or ['Not provided in source.']
            lines.append('')
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('data/openwall-cve-links.txt'))
    parser.add_argument('--output-dir', type=Path, default=Path('generated/openwall-cves'))
    parser.add_argument('--timeout', type=int, default=20)
    args = parser.parse_args()
    cards = []
    # Fetch and parse everything first: a failed request must fail CI, not publish placeholders.
    for url in load_urls(args.input):
        try:
            card_filename(url)
            cards.append(parse_card(fetch_text(url, args.timeout), url))
        except (OSError, ValueError) as exc:
            print(f'Failed to render {url}: {exc}', file=sys.stderr)
            return 1
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for card in cards:
        render_png(card, args.output_dir / card_filename(card.url))
    (args.output_dir / 'README.md').write_text(render_index(cards), encoding='utf-8')
    print(f'Generated {len(cards)} PNG cards in {args.output_dir}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
