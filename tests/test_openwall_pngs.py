import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import render_openwall_pngs as renderer

URL = 'https://www.openwall.com/lists/oss-security/2026/06/29/3'
PAGE = '''<html><title>Navigation title</title><pre>
Subject: CVE-2023-0645: libjxl/cjxl out-of-bounds read in EXIF metadata
 parsing

Product: JPEG XL / libjxl
Affected: libjxl versions before 0.8.1
Reporter: sigdevel &lt;<a href="https://infosec.exchange/&#64;sigdevel">https://infosec.exchange/&#64;sigdevel</a>&gt; / Alexander A. Shvedov

Description:
  unrelated body
PoC:
  <a href="https://github.com/sigdevel/pocs/blob/main/res/libjxl/2022_01_25/sig_11_src_000122_poc">https://github.com/sigdevel/pocs/blob/main/res/libjxl/2022_01_25/sig_11_src_000122_poc</a>
References:
  <a href="https://nvd.nist.gov/vuln/detail/CVE-2023-0645">https://nvd.nist.gov/vuln/detail/CVE-2023-0645</a>
  https://github.com/libjxl/libjxl/issues/2100

——
Best regards, Alexander A. Shvedov
https://github.com/sigdevel
</pre><p>Other navigation</p></html>'''


class RendererTests(unittest.TestCase):
    def test_fields_and_html_entities(self):
        card = renderer.parse_card(PAGE, URL)
        self.assertEqual(card.fields['Subject'], 'CVE-2023-0645: libjxl/cjxl out-of-bounds read in EXIF metadata parsing')
        self.assertEqual(card.fields['Product'], 'JPEG XL / libjxl')
        self.assertEqual(card.fields['Affected'], 'libjxl versions before 0.8.1')
        self.assertEqual(card.fields['Reporter'], 'sigdevel <https://infosec.exchange/@sigdevel> / Alexander A. Shvedov')
        self.assertEqual(len(card.fields['PoC'].splitlines()), 1)
        self.assertEqual(card.fields['References'].splitlines(), ['https://nvd.nist.gov/vuln/detail/CVE-2023-0645', 'https://github.com/libjxl/libjxl/issues/2100'])

    def test_missing_fields_and_invalid_page(self):
        card = renderer.parse_card('<pre>Subject: Example\n\nProduct: Example</pre>', URL)
        self.assertEqual(card.fields['Affected'], '')
        with self.assertRaises(ValueError):
            renderer.parse_card('<title>Access denied</title>', URL)

    def test_poc_repository_link_in_references(self):
        url = 'https://github.com/sigdevel/pocs/blob/main/res/lwext4/example'
        card = renderer.parse_card(f'<pre>Subject: Example\n\nReferences:\n  {url}\n  https://example.com/fix\n</pre>', URL)
        self.assertEqual(card.fields['PoC'], url)
        self.assertIn(url, card.fields['References'])

    def test_wrap_preserves_long_urls_without_overflow(self):
        font = ImageFont.load_default(size=22)
        url = 'https://example.com/' + 'very-long-url' * 30
        lines = renderer.wrap_text(url, font, 300)
        self.assertEqual(''.join(lines), url)
        self.assertTrue(all(font.getlength(line) <= 300 for line in lines))

    def test_cli_deduplicates_and_renders_valid_png(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / 'links.txt').write_text(f'# comment\n{URL}\n{URL}\n')
            args = ['renderer', '--input', str(p / 'links.txt'), '--output-dir', str(p / 'cards')]
            with patch.object(sys, 'argv', args), patch.object(renderer, 'fetch_text', return_value=PAGE) as fetch:
                self.assertEqual(renderer.main(), 0)
                fetch.assert_called_once()
            pngs = list((p / 'cards').glob('*/*.png'))
            self.assertEqual(len(pngs), 1)
            self.assertEqual(pngs[0].name, 'openwall-2026-06-29-3.png')
            self.assertEqual(pngs[0].parent.name, 'openwall-2026-06-29-3')
            text = pngs[0].with_suffix('.txt').read_text()
            self.assertIn(f'Source:\n{URL}', text)
            self.assertIn('https://nvd.nist.gov/vuln/detail/CVE-2023-0645', text)
            self.assertIn('https://infosec.exchange/@sigdevel', text)
            with Image.open(pngs[0]) as image:
                self.assertEqual(image.format, 'PNG')
                self.assertEqual(image.width, 1200)
                image.verify()
            self.assertIn('<https://nvd.nist.gov/vuln/detail/CVE-2023-0645>', (p / 'cards/README.md').read_text())
            self.assertIn('(openwall-2026-06-29-3/openwall-2026-06-29-3.txt)', (p / 'cards/README.md').read_text())
            # An upgrade removes its old flat image, preserving unrelated files.
            legacy = p / 'cards' / pngs[0].name
            legacy.write_bytes(b'old image')
            unrelated = p / 'cards/custom.png'
            unrelated.write_bytes(b'user image')
            with patch.object(sys, 'argv', args), patch.object(renderer, 'fetch_text', return_value=PAGE):
                self.assertEqual(renderer.main(), 0)
            self.assertFalse(legacy.exists())
            self.assertEqual(unrelated.read_bytes(), b'user image')

    def test_failure_keeps_existing_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / 'links.txt').write_text(URL)
            (p / 'README.md').write_text('existing index')
            with patch.object(sys, 'argv', ['renderer', '--input', str(p / 'links.txt'), '--output-dir', td]), patch.object(renderer, 'fetch_text', side_effect=OSError('network unavailable')):
                self.assertEqual(renderer.main(), 1)
            self.assertEqual((p / 'README.md').read_text(), 'existing index')
            self.assertEqual(list(p.glob('*.png')), [])


if __name__ == '__main__':
    unittest.main()
