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

The TXT file contains the source URL and all card fields, including full PoC,
reference and reporter links, without visual line wrapping.
Names include the source date and message number,
so different posts about the same CVE remain separate cards.

Cards display Subject, Product, Affected, PoC, References and Reporter, parsed
from the publication's message body. When there is no PoC section, links to
`github.com/sigdevel/pocs/` in References are also shown as PoC. Missing fields read `Not provided in
source`; values are never inferred. All source references are included. Text
and long URLs wrap to fit, and image height grows with content.

PNG images cannot contain clickable links. The generated Markdown index
provides clickable PoC and reference URLs, and each image links to its source.
It also links to each TXT file. Existing flat PNGs for successfully generated
posts are removed after generation; unrelated files are preserved.

Options: `--input PATH`, `--output-dir PATH`, `--timeout SECONDS`.
HTTPS access to `www.openwall.com` is required. A fetch failure or invalid
message exits unsuccessfully before updating any cards or the index.
The existing `render_openwall_cves.py` still generates the summary SVG and
README table independently. GitHub Actions runs both renderers and commits
the generated output.
