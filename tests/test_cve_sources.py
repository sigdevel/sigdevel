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


class SourceTests(unittest.TestCase):
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

    def test_cve_org_requires_valid_record_and_issue(self):
        invalid = [CVE_ORG,
                   f'{CVE_ORG} https://github.com/gpac/gpac/pull/3848',
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
