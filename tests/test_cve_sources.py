import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import render_openwall_cves as r

NVD = 'https://nvd.nist.gov/vuln/detail/cve-2026-124031'
ISSUE = 'https://github.com/gpac/gpac/issues/4030'
TITLE = 'compositor/texturing.c:370 NULL Pointer Dereference in gf_node_get_tag'
CVE_ORG = 'https://www.cve.org/CVERecord?id=CVE-2026-134686'
CVE_ISSUE = 'https://github.com/gpac/gpac/issues/3848'
CVE_TITLE = 'scenegraph/base_scenegraph.c:830 NULL Pointer Dereference in gf_node_register'
STANDALONE_CVE = 'CVE-2025-71474'
STANDALONE_URL = f'https://www.cve.org/CVERecord?id={STANDALONE_CVE}'
RECORD_TITLE = 'lwext4 through 1.0.0 Out-of-Bounds Write via ext4_fs_init_block_bitmap'


def record_json(**cna):
    return json.dumps({'cveMetadata': {'cveId': STANDALONE_CVE},
                       'containers': {'cna': cna}})


class SourceTests(unittest.TestCase):
    def test_standalone_cve_org_formats_order_and_png_exclusion(self):
        openwall = 'https://www.openwall.com/example'
        escaped = STANDALONE_URL.replace(':', r'\:').replace('.', r'\.')
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'links'
            p.write_text(f'{STANDALONE_URL}\n{openwall}\n'
                         f'[{STANDALONE_CVE}]({STANDALONE_URL})\n{escaped}\n', encoding='utf-8')
            self.assertEqual(r.load_sources(p), [(STANDALONE_URL, None), (openwall, None)])
            self.assertEqual(r.load_urls(p), [openwall])

    def test_standalone_cve_org_title_and_destinations(self):
        with patch.object(r, 'fetch_text', return_value=record_json(title=RECORD_TITLE)) as fetch:
            post = r.collect_posts([STANDALONE_URL], 20)[0]
            fetch.assert_called_once_with(
                'https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/'
                '2025/71xxx/CVE-2025-71474.json', 20)
        self.assertEqual(post.cves, (STANDALONE_CVE,))
        self.assertEqual(post.subject, f'{STANDALONE_CVE}: {RECORD_TITLE}')
        table = r.render_markdown_table([post])
        self.assertIn(f'[{STANDALONE_CVE}]({STANDALONE_URL})', table)
        self.assertIn(f'[{STANDALONE_CVE}: {RECORD_TITLE}]({STANDALONE_URL})', table)

    def test_record_title_falls_back_to_english_description(self):
        record = record_json(descriptions=[{'lang': 'fr', 'value': 'French description'},
                                           {'lang': 'en', 'value': 'English\n description'}])
        self.assertEqual(r.extract_record_subject(record, STANDALONE_CVE),
                         f'{STANDALONE_CVE}: English description')
        record = record_json(title=f'[security] {STANDALONE_CVE}: {RECORD_TITLE}')
        self.assertEqual(r.extract_record_subject(record, STANDALONE_CVE),
                         f'{STANDALONE_CVE}: {RECORD_TITLE}')

    def test_standalone_cve_failure_retains_identifier_and_link(self):
        for response in ('not JSON', '{}', '[]', record_json(),
                         record_json(title=RECORD_TITLE).replace(STANDALONE_CVE, 'CVE-2025-1234')):
            with self.subTest(response=response):
                with patch.object(r, 'fetch_text', return_value=response), patch('sys.stderr', new=io.StringIO()):
                    post = r.collect_posts([(STANDALONE_URL, None)], 20)[0]
                self.assertEqual(post.cves, (STANDALONE_CVE,))
                self.assertEqual(post.subject, 'Subject unavailable')
                self.assertIn(f'[{STANDALONE_CVE}]({STANDALONE_URL})', r.render_markdown_table([post]))
        with patch.object(r, 'fetch_text', side_effect=TimeoutError('timeout')), patch('sys.stderr', new=io.StringIO()):
            post = r.collect_posts([(STANDALONE_URL, None)], 20)[0]
        self.assertEqual(post.cves, (STANDALONE_CVE,))

    def test_standalone_cve_main_updates_readme_and_svg(self):
        with tempfile.TemporaryDirectory() as td:
            source, readme, output = (Path(td) / name for name in ('links', 'README.md', 'card.svg'))
            source.write_text(STANDALONE_URL, encoding='utf-8')
            readme.write_text('| CVE | Description |\n| --- | --- |\n', encoding='utf-8')
            argv = ['render_openwall_cves.py', '--input', str(source), '--readme', str(readme),
                    '--output', str(output)]
            with patch.object(sys, 'argv', argv), patch.object(r, 'fetch_text', return_value=record_json(title=RECORD_TITLE)):
                self.assertEqual(r.main(), 0)
            self.assertIn(f'[{STANDALONE_CVE}: {RECORD_TITLE}]({STANDALONE_URL})',
                          readme.read_text(encoding='utf-8'))
            self.assertIn('>1</tspan>', output.read_text(encoding='utf-8'))

    def test_record_json_url_number_buckets(self):
        for number, bucket in [('1234', '1xxx'), ('71474', '71xxx'), ('134686', '134xxx'),
                               ('1234567', '1234xxx')]:
            self.assertIn(f'/2025/{bucket}/CVE-2025-{number}.json',
                          r.cve_record_json_url(f'CVE-2025-{number}'))

    def test_cve_org_source_formats_and_png_exclusion(self):
        escaped = CVE_ORG.replace(':', r'\:').replace('.', r'\.')
        formats = [f'{CVE_ORG} {CVE_ISSUE}',
                   f'[{CVE_ORG}]({CVE_ORG}) [/issues]({CVE_ISSUE})',
                   f'{escaped} [/issues]\\({CVE_ISSUE}\\)']
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'links'
            p.write_text('\n'.join(formats), encoding='utf-8')
            self.assertEqual(r.load_sources(p), [(CVE_ORG, CVE_ISSUE)])
            self.assertEqual(r.load_urls(p), [])

    def test_cve_org_requires_valid_record_and_explicit_issue(self):
        invalid = [f'{CVE_ORG} https://github.com/gpac/gpac/pull/3848',
                   f'{CVE_ORG} {CVE_ISSUE} https://github.com/gpac/gpac/issues/4030',
                   f'https://www.cve.org/CVERecord {CVE_ISSUE}',
                   f'https://www.cve.org/other?id=CVE-2026-134686 {CVE_ISSUE}',
                   f'{CVE_ORG}0abc {CVE_ISSUE}',
                   f'{CVE_ORG}&id=CVE-2026-1234 {CVE_ISSUE}']
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'links'
            for line in invalid:
                with self.subTest(line=line):
                    p.write_text(line, encoding='utf-8')
                    with self.assertRaises(ValueError):
                        r.load_sources(p)

    def test_standalone_cve_org_duplicate_uses_explicit_pair(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'links'
            for lines in (f'{CVE_ORG}\n{CVE_ORG} {CVE_ISSUE}\n',
                          f'{CVE_ORG} {CVE_ISSUE}\n{CVE_ORG}\n'):
                p.write_text(lines, encoding='utf-8')
                self.assertEqual(r.load_sources(p), [(CVE_ORG, CVE_ISSUE)])

    def test_cve_org_title_and_link_destinations(self):
        for prefix in ('[security] ', '[SECURITY] CVE-2026-134686: '):
            with self.subTest(prefix=prefix):
                page = (f'<meta property="og:title" content="{prefix}{CVE_TITLE}'
                        ' · Issue #3848 · gpac/gpac">')
                with patch.object(r, 'fetch_text', return_value=page) as fetch:
                    post = r.collect_posts([(CVE_ORG, CVE_ISSUE)], 20)[0]
                    fetch.assert_called_once_with(CVE_ISSUE, 20)
                self.assertEqual(post.cves, ('CVE-2026-134686',))
                self.assertEqual(post.subject, f'CVE-2026-134686: {CVE_TITLE}')
                table = r.render_markdown_table([post])
                self.assertEqual(table.splitlines()[2],
                                 f'| [CVE-2026-134686]({CVE_ORG}) | '
                                 f'[CVE-2026-134686: {CVE_TITLE}]({CVE_ISSUE}) |')

    def test_cve_org_without_www_and_lowercase_identifier(self):
        url = 'https://cve.org/CVERecord?id=cve-2026-134686'
        self.assertEqual(r.extract_record_cve(url), 'CVE-2026-134686')

    def test_mixed_plain_and_markdown_sources(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'links'
            p.write_text(f'# comment\nhttps://www.openwall.com/example\n{NVD} {ISSUE}\n[{NVD}]({NVD}) [{ISSUE}]({ISSUE})\n')
            self.assertEqual(r.load_sources(p), [('https://www.openwall.com/example', None), (NVD, ISSUE)])
            self.assertEqual(r.load_urls(p), ['https://www.openwall.com/example'])
            p.write_text(NVD)
            with self.assertRaises(ValueError):
                r.load_sources(p)

    def test_standalone_nvd_duplicate_uses_explicit_pair(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'links'
            for lines in (f'{NVD}\n{NVD} {ISSUE}\n',
                          f'{NVD} {ISSUE}\n{NVD.upper().replace("HTTPS", "https")}\n'):
                p.write_text(lines)
                self.assertEqual(r.load_sources(p), [(NVD, ISSUE)])
                self.assertEqual(r.load_urls(p), [])

    def test_issue_title_and_link_destinations(self):
        page = f'<meta property="og:title" content="[security] {TITLE} · Issue #4030 · gpac/gpac">'
        with patch.object(r, 'fetch_text', return_value=page) as fetch:
            posts = r.collect_posts([(NVD, ISSUE)], 20)
            fetch.assert_called_once_with(ISSUE, 20)
        self.assertEqual(posts[0].subject, f'CVE-2026-124031: GPAC/MP4Box {TITLE}')
        table = r.render_markdown_table(posts)
        self.assertIn(f'[CVE-2026-124031]({NVD})', table)
        self.assertIn(f'[CVE-2026-124031: GPAC/MP4Box {TITLE}]({ISSUE})', table)
        self.assertNotIn('[security]', table)

    def test_title_fallback_and_existing_cve(self):
        title = 'CVE-2026-124031: sample &amp; example'
        page = f'<title>[SECURITY] {title} · Issue #4030 · gpac/gpac · GitHub</title>'
        with patch.object(r, 'fetch_text', return_value=page):
            post = r.collect_posts([(NVD, ISSUE)], 20)[0]
        self.assertEqual(post.subject, 'CVE-2026-124031: GPAC/MP4Box sample & example')

    def test_gpac_alias_is_case_insensitive(self):
        issue = 'https://github.com/GPAC/Gpac/issues/4030'
        with patch.object(r, 'fetch_text', return_value='<title>[security] example</title>'):
            post = r.collect_posts([(NVD, issue)], 20)[0]
        self.assertEqual(post.subject, 'CVE-2026-124031: GPAC/MP4Box example')
        self.assertIn(f']({issue})', r.render_markdown_table([post]))

    def test_repository_comes_from_issue_url(self):
        issue = 'https://github.com/another/vendor/issues/42'
        with patch.object(r, 'fetch_text', return_value='<title>[security] example</title>'):
            post = r.collect_posts([(NVD, issue)], 20)[0]
        self.assertEqual(post.subject, 'CVE-2026-124031: another/vendor example')

    def test_openwall_compatibility(self):
        with patch.object(r, 'fetch_text', return_value='Subject: CVE-2026-1234: old post\n\n'):
            post = r.collect_posts(['https://www.openwall.com/example'], 20)[0]
        self.assertEqual(post.cves, ('CVE-2026-1234',))
        self.assertIsNone(post.cve_url)
