import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import render_openwall_cves as summary
import render_openwall_pngs as renderer

CVE = 'CVE-2025-71474'
NVD = f'https://nvd.nist.gov/vuln/detail/{CVE}'
CVE_ORG = f'https://www.cve.org/CVERecord?id={CVE}'
ISSUE = 'https://github.com/gpac/gpac/issues/4032'
ISSUE_PAGE = '<title>[security] scenegraph.c: invalid pointer</title>'
OPENWALL = 'https://www.openwall.com/lists/oss-security/2026/06/29/3'
POC = 'https://github.com/sigdevel/pocs/blob/main/example'
PATCH = 'https://github.com/vendor/widget/commit/abcdef'


def record(cve=CVE, **overrides):
    cna = {
        'title': 'Widget uninitialized pointer dereference',
        'affected': [{'vendor': 'Acme', 'product': 'Widget',
                      'defaultStatus': 'unaffected',
                      'versions': [{'version': '0', 'lessThan': '26.10', 'status': 'affected'}]}],
        'credits': [{'type': 'finder', 'value': 'Researcher'},
                    {'type': 'remediation_developer', 'value': 'Maintainer'}],
        'references': [{'url': POC, 'tags': ['exploit']}, {'url': PATCH, 'tags': ['patch']}],
    }
    cna.update(overrides)
    return json.dumps({'cveMetadata': {'cveId': cve},
                       'containers': {'cna': cna, 'adp': [{'references': [
                           {'url': PATCH}, {'url': 'https://example.com/advisory'}]}]}})


class RecordCardTests(unittest.TestCase):
    def test_official_cve_fields_and_all_references(self):
        card = renderer.parse_record_card(record(), CVE_ORG)
        self.assertEqual(card.fields['Subject'], f'{CVE}: Widget uninitialized pointer dereference')
        self.assertEqual(card.fields['Product'], 'Acme/Widget')
        self.assertEqual(card.fields['Affected'], 'Acme/Widget: 0 to < 26.10 (affected); default: unaffected')
        self.assertEqual(card.fields['Reporter'], 'Researcher')
        self.assertEqual(card.fields['PoC'], POC)
        self.assertEqual(card.fields['References'].splitlines(), [
            CVE_ORG, summary.cve_record_json_url(CVE), POC, PATCH, 'https://example.com/advisory'])

    def test_issue_titles_and_index_destinations_for_both_providers(self):
        for url, expected in [(NVD, f'{CVE}: GPAC/MP4Box scenegraph.c: invalid pointer'),
                              (CVE_ORG, f'{CVE}: scenegraph.c: invalid pointer')]:
            with self.subTest(url=url):
                card = renderer.parse_record_card(record(), url, ISSUE, ISSUE_PAGE)
                self.assertEqual(card.fields['Subject'], expected)
                entry = renderer.render_index_entry(card)
                self.assertIn(f'Source: <{url}>', entry)
                self.assertIn(f'Issue: <{ISSUE}>', entry)
                self.assertIn(f')]({ISSUE})', entry)
                self.assertIn(ISSUE, card.fields['References'])
                self.assertNotIn('[security]', entry)

    def test_missing_fields_are_not_inferred_from_issue_or_repository(self):
        card = renderer.parse_record_card(record(affected=[], credits=[], references=[]), CVE_ORG)
        for field in ('Product', 'Affected', 'Reporter', 'PoC'):
            self.assertEqual(card.fields[field], '')
        with self.assertRaises(ValueError):
            renderer.parse_record_card(record('CVE-2025-1234'), CVE_ORG)
        with self.assertRaises(ValueError):
            renderer.parse_record_card(record(), NVD, ISSUE)

    def test_filenames_preserve_source_identity(self):
        names = {renderer.card_filename(NVD, ISSUE), renderer.card_filename(CVE_ORG),
                 renderer.card_filename(CVE_ORG, ISSUE),
                 renderer.card_filename(CVE_ORG, ISSUE.replace('4032', '4033'))}
        self.assertEqual(len(names), 4)
        self.assertTrue(all('cve-2025-71474' in name for name in names))
        self.assertEqual(renderer.card_filename(OPENWALL), 'openwall-2026-06-29-3.png')

    def test_missing_public_record_is_explicit_and_server_errors_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, output = root / 'links', root / 'cards'
            source.write_text(CVE_ORG + '\n')
            args = ['renderer', '--input', str(source), '--output-dir', str(output)]
            for status in (500, 403, 404):
                with self.subTest(status=status), patch.object(sys, 'argv', args), patch.object(
                    renderer, 'fetch_text', side_effect=HTTPError(
                        summary.cve_record_json_url(CVE), status, 'unavailable', {}, None)):
                    self.assertEqual(renderer.main(), 0 if status == 404 else 1)
                if status != 404:
                    self.assertFalse(output.exists())
            index = (output / 'README.md').read_text()
            self.assertIn(f'{CVE}: Public CVE record unavailable (HTTP 404)', index)
            self.assertIn(summary.cve_record_json_url(CVE), index)
            self.assertEqual(len(list(output.glob('*/*.png'))), 1)
            self.assertEqual(len(list(output.glob('*/*.txt'))), 1)

    def test_mixed_cli_matches_summary_count_and_preserves_cached_pairs(self):
        paired_cve = 'CVE-2025-71475'
        paired_url = f'https://www.cve.org/CVERecord?id={paired_cve}'

        def fetch(url, timeout):
            if url == OPENWALL:
                return '<pre>Subject: CVE-2023-0645: old Openwall post\n\nProduct: Example</pre>'
            if url == ISSUE:
                return ISSUE_PAGE
            for cve in (CVE, paired_cve):
                if url == summary.cve_record_json_url(cve):
                    return record(cve)
            self.fail(f'Unexpected fetch URL: {url}')

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source, readme, svg, output = (root / name for name in ('links', 'README.md', 'summary.svg', 'cards'))
            source.write_text(f'{OPENWALL}\n{NVD} {ISSUE}\n{CVE_ORG}\n{paired_url} {ISSUE}\n')
            readme.write_text('| CVE | Description |\n| --- | --- |\n')
            summary_args = ['renderer', '--input', str(source), '--output', str(svg), '--readme', str(readme)]
            with patch.object(sys, 'argv', summary_args), patch.object(summary, 'fetch_text', side_effect=fetch):
                self.assertEqual(summary.main(), 0)
            args = ['renderer', '--input', str(source), '--output-dir', str(output)]
            with patch.object(sys, 'argv', args), patch.object(renderer, 'fetch_text', side_effect=fetch):
                self.assertEqual(renderer.main(), 0)
            count = int(re.search(r'class="metric-number">(\d+)', svg.read_text()).group(1))
            self.assertEqual(count, 4)
            pngs = list(output.glob('*/*.png'))
            self.assertEqual(len(pngs), count)
            self.assertEqual(len(list(output.glob('*/*.txt'))), count)
            self.assertEqual((output / 'README.md').read_text().count('## '), count)
            for png in pngs:
                with Image.open(png) as image:
                    image.verify()
            before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.rglob('*') if p.is_file()}
            with patch.object(sys, 'argv', args), patch.object(renderer, 'fetch_text') as fetch_mock, patch.object(renderer, 'render_png') as render:
                self.assertEqual(renderer.main(), 0)
                fetch_mock.assert_not_called()
                render.assert_not_called()
            self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})
            # A new record fetch failure must not change any retained card or index.
            source.write_text(source.read_text() + 'https://www.cve.org/CVERecord?id=CVE-2025-71476\n')
            with patch.object(sys, 'argv', args), patch.object(renderer, 'fetch_text', side_effect=OSError('offline')):
                self.assertEqual(renderer.main(), 1)
            self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})


if __name__ == '__main__':
    unittest.main()
