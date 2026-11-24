# CVE card generation

Run from the repository root with Python 3.10 or newer:

```sh
python3 -m pip install -r scripts/requirements.txt
python3 scripts/render_openwall_pngs.py
python3 -m unittest discover -s tests
```

The PNG renderer reads every source from `data/openwall-cve-links.txt`:
Openwall posts, NIST/NVD and GitHub issue pairs, and CVE.org records with or
without a GitHub issue. It uses the same source list and deduplication as the
summary SVG, so the number of cards matches its counter. Each source entry
gets one directory in
`generated/openwall-cves/`, containing a PNG card and a UTF-8 TXT file:

```text
generated/openwall-cves/openwall-2026-10-17-4/
  openwall-2026-10-17-4.png
  openwall-2026-10-17-4.txt
```

The TXT file contains only the `PoC:` and `References:` sections with full
URLs, without visual line wrapping.
Openwall names retain the source date and message number. NVD and CVE.org
names contain the provider, CVE identifier and a hash of the source/issue
URLs, for example `cve-cve-2025-71474-<hash>`. Different sources or issue pairs
about the same CVE remain separate cards, just as in the summary counter.

PNG cards display Subject, Product, Affected and Reporter, plus the source URL.
Openwall fields are parsed from the publication's message body. NVD and
CVE.org cards use the official `CVEProject/cvelistV5` JSON record: CNA title
or English description, affected products and version ranges, and finder or
reporter credits. For paired sources, Subject comes from the GitHub issue,
using the same formatting as the README table. PoC and References
are exported to TXT only and do not appear in the PNG. When there is no PoC section, links to
`github.com/sigdevel/pocs/` in References are also shown as PoC. Missing fields read `Not provided in
source`; values are never inferred. CVE records include all CNA/ADP reference
URLs, the original source URL, the JSON URL and the issue URL when present.
References tagged `exploit` are also exported as PoC. Text
and long URLs wrap to fit, and image height grows with content.

PNG images cannot contain clickable links. The generated Markdown index
provides clickable PoC and reference URLs, and each image links to its issue
when paired, otherwise to its source.
It also links to each TXT file. Existing flat PNGs for successfully generated
posts are removed after generation; unrelated files are preserved.

Existing PNG/TXT pairs are skipped without fetching the source or rewriting
either file. If one file is missing, the pair is generated again. Existing
index entries are retained; new entries are added for newly generated sources.
Use `--force` to refresh all sources explicitly, for example after a design change.

Options: `--input PATH`, `--output-dir PATH`, `--timeout SECONDS`, `--force`.
HTTPS access to `www.openwall.com`, `raw.githubusercontent.com` and, for
paired records, `github.com` is required only for new, incomplete or forced
sources. A fetch failure or invalid record exits unsuccessfully before updating
any cards or the index. An official CVE JSON HTTP 404 is handled explicitly:
the card says `Public CVE record unavailable (HTTP 404)`, keeps the CVE and
source links, and leaves vulnerability fields empty. It does not assert that
the CVE is reserved or invent details. Such cards are cached too; use `--force`
after publication to refresh them. Other HTTP errors still fail generation.
The existing `render_openwall_cves.py` still generates the summary SVG and
README table independently. GitHub Actions runs both renderers and commits
the generated output.

## NVD and GitHub issues in the CVE list

In `data/openwall-cve-links.txt`, put an NVD URL and a GitHub issue URL on
one line, separated by whitespace (Markdown links are also accepted):

```text
https://nvd.nist.gov/vuln/detail/cve-2026-124031 https://github.com/gpac/gpac/issues/4030
```

`render_openwall_cves.py` takes the CVE identifier from the NVD URL without
fetching NVD and reads the issue title from GitHub. It removes a leading
`[security]` (case insensitive), removes GitHub's title suffix, and prefixes
the title with `CVE-…: owner/repository`, using the repository from the issue
URL. The repository `gpac/gpac` is displayed as `GPAC/MP4Box` (case
insensitive); other repositories keep their names. Link destinations are
unchanged. An existing leading CVE identifier is not repeated. The CVE cell links to NVD;
the description links to the issue. Duplicate pairs are ignored. The PNG
renderer generates cards for these pairs using the official CVE JSON fields
and the same issue title.

A standalone NVD URL that duplicates an explicit NVD/issue pair is ignored,
regardless of line order. A standalone NVD URL without a pair is an input
error: add its GitHub issue URL on the same line.

## CVE.org and GitHub issues in the CVE list

CVE.org record URLs are also supported, with the GitHub issue on the same
line (plain URLs, Markdown links and escaped Markdown punctuation are accepted):

```text
https://www.cve.org/CVERecord?id=CVE-2026-134686 [/issues](https://github.com/gpac/gpac/issues/3848)
```

The identifier comes from the record URL's `id` query parameter; the record
page is not fetched. The description uses the GitHub issue title without a
leading `[security]` or GitHub's title suffix, prefixed with `CVE-…: `.
An existing leading CVE identifier is not repeated. No repository name is
added for CVE.org sources. The example renders as:

| CVE | Description |
| --- | --- |
| [CVE-2026-134686](https://www.cve.org/CVERecord?id=CVE-2026-134686) | [CVE-2026-134686: scenegraph/base_scenegraph.c:830 NULL Pointer Dereference in gf_node_register](https://github.com/gpac/gpac/issues/3848) |

### Standalone CVE.org records

A CVE.org URL can also appear on its own:

```text
https://www.cve.org/CVERecord?id=CVE-2025-71474
```

For these entries, the renderer fetches the official JSON record from
`CVEProject/cvelistV5` and uses its CNA title, falling back to the English
description when the title is absent. Both table cells link to the original
CVE.org URL. The CVE identifier remains visible if the record cannot be fetched
or has no title or English description; a warning is printed and the description
reads `Subject unavailable`.

Duplicate URLs are ignored. When the same CVE.org URL has an explicit GitHub
issue pair elsewhere in the file, that pair takes precedence regardless of
line order. The PNG renderer generates cards for all these CVE.org entries.
Standalone NVD URLs still require an explicit issue pair.
