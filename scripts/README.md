# Openwall card generation

Run from the repository root with Python 3.10 or newer:

```sh
python3 -m pip install -r scripts/requirements.txt
python3 scripts/render_openwall_pngs.py
python3 -m unittest discover -s tests
```

The PNG renderer reads `data/openwall-cve-links.txt`, ignores comments and
repeated URLs, and creates one directory per unique post in
`generated/openwall-cves/`, containing a PNG card and a UTF-8 TXT file:

```text
generated/openwall-cves/openwall-2026-10-17-4/
  openwall-2026-10-17-4.png
  openwall-2026-10-17-4.txt
```

The TXT file contains only the `PoC:` and `References:` sections with full
URLs, without visual line wrapping.
Names include the source date and message number,
so different posts about the same CVE remain separate cards.

PNG cards display Subject, Product, Affected and Reporter, parsed
from the publication's message body, plus the source URL. PoC and References
are exported to TXT only and do not appear in the PNG. When there is no PoC section, links to
`github.com/sigdevel/pocs/` in References are also shown as PoC. Missing fields read `Not provided in
source`; values are never inferred. All source references are included. Text
and long URLs wrap to fit, and image height grows with content.

PNG images cannot contain clickable links. The generated Markdown index
provides clickable PoC and reference URLs, and each image links to its source.
It also links to each TXT file. Existing flat PNGs for successfully generated
posts are removed after generation; unrelated files are preserved.

Existing PNG/TXT pairs are skipped without fetching the post or rewriting
either file. If one file is missing, the pair is generated again. Existing
index entries are retained; new entries are added for newly generated posts.
Use `--force` to refresh all posts explicitly, for example after a design change.

Options: `--input PATH`, `--output-dir PATH`, `--timeout SECONDS`, `--force`.
HTTPS access to `www.openwall.com` is required only for new, incomplete or
forced posts. A fetch failure or invalid
message exits unsuccessfully before updating any cards or the index.
The existing `render_openwall_cves.py` still generates the summary SVG and
README table independently. GitHub Actions runs both renderers and commits
the generated output.
