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


class SourceTests(unittest.TestCase):
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
        self.assertEqual(posts[0].subject, f'CVE-2026-124031: {TITLE}')
        table = r.render_markdown_table(posts)
        self.assertIn(f'[CVE-2026-124031]({NVD})', table)
        self.assertIn(f'[CVE-2026-124031: {TITLE}]({ISSUE})', table)
        self.assertNotIn('[security]', table)

    def test_title_fallback_and_existing_cve(self):
        title = 'CVE-2026-124031: sample &amp; example'
        page = f'<title>[SECURITY] {title} · Issue #4030 · gpac/gpac · GitHub</title>'
        with patch.object(r, 'fetch_text', return_value=page):
            post = r.collect_posts([(NVD, ISSUE)], 20)[0]
        self.assertEqual(post.subject, 'CVE-2026-124031: sample & example')

    def test_openwall_compatibility(self):
        with patch.object(r, 'fetch_text', return_value='Subject: CVE-2026-1234: old post\n\n'):
            post = r.collect_posts(['https://www.openwall.com/example'], 20)[0]
        self.assertEqual(post.cves, ('CVE-2026-1234',))
        self.assertIsNone(post.cve_url)
