# Dependency evidence

What StackVitals says about a package (Dependency Steward, `stackvitals deps check`, the MCP tool `supply_chain`) comes
from the crawl's daily files: the package map (deps.dev, claims checked against manifests), OSV's records, and the
upgrade ledger built from Dependabot and Renovate pull requests in crawled repos. This card measures what those files
let the product say, before the 2026-10-23 changes added exploit likelihood (EPSS), known exploitation (CISA KEV), transitive paths and
rollback-weighted upgrades.

## Baseline (`baseline.py`, files built 2026-10-21)

| What | Today |
|---|---|
| Packages with evidence | 4,033 |
| With OSV advisories | 784 packages, 5,374 advisories (461 critical, 1,934 high) |
| Advisories with no fixed version | 8 |
| Malware records (OSV `MAL-`) | 26 packages |
| Advisories that can be scored for exploit likelihood (EPSS) or checked against KEV | none scored yet; 7,620 of the 7,865 cached advisory records (97%) carry a CVE alias, so nearly all can be |
| Upgrades merged in 180 days (ledger) | 125,992 in 6,420 package and step cells |
| Of those, reverted within 14 days | 8 (0.01%) |

**What the baseline shows:**
- **Rollbacks are almost never seen.** A revert pull request titled "Revert ..." is rare; teams roll an upgrade back by
  pinning the old version, a later downgrade, or `@dependabot ignore`. So "taken by N, rolled back by M" needs a better
  detector before it can weigh anything.
- **Exploit evidence is missing.** The advice ranks by severity only, though 97% of the advisories already carry the
  CVE alias that EPSS and KEV are keyed by.
- **The product shows no paths.** GitHub's SBOM lists every resolved package but not which direct dependency pulls it
  in, so a vulnerable transitive package can't be traced to the line a team would change.

## Exploit evidence added (`exploits.py`)

The crawler now reads CISA's Known Exploited Vulnerabilities list and FIRST's EPSS (the chance of exploitation in the
next 30 days) for every advisory's CVE, daily and free (`mergescout/signals/exploits.py`). On the same cached records:

| What | After |
|---|---|
| CVEs scored by EPSS | 4,541 of 4,575 (99%) |
| CVEs CISA lists as exploited in the wild | 20, in 17 packages (all fixed in newer releases today) |
| Of the 31 advisory records behind them, rated below HIGH or not rated | 15 (4 moderate, 11 with no rating) |
| Records with EPSS 10% or more | 220, of which 114 are rated below HIGH or not rated |
| Packages with an open (unfixed) advisory at EPSS 10% or more | 0 today |

**What it shows:** the severity label alone underrates about half of what attackers use or are likely to use, so the
advice now names exploited CVEs ("exploited in the wild; it is fixed in newer releases, so stay on a fixed version")
and raises an alarm for an open advisory that is exploited or at EPSS 10% or more. Nothing open meets that bar in the
crawl today, so the alarm is rare by design.

## Rollbacks seen

The ledger counted an upgrade as rolled back only when a pull request titled `Revert "Bump ..."` followed within 14
days, and the crawl keeps no title for most people's pull requests. It now also reads the merged pull request's branch,
which the crawl keeps for all: GitHub's Revert button names it `revert-<number>-...` after the pull request it undoes,
and people name rollbacks `rollback-litellm` or `downgrade-esbuild-0.24` (the package followed by a version or nothing,
so `revert-django-csp` after a django upgrade doesn't count).

| On the crawl's sample (48,994 merged bot upgrades) | Rolled back |
|---|---|
| Before (revert titles) | 6 |
| After (titles and branches) | 19, in 17 packages (every one a revert or rollback of that upgrade when read by hand) |

Rollbacks stay rare (about 1 in 2,500 merged upgrades), so "rolled back in M of N repos" is a rare red flag rather
than a rate, and the advice shows it only when it happened.

## Transitive paths

A flagged package another one pulls in now names the way it came in the pull request check ("npm:qs (via express ->
body-parser -> qs)"), from the lockfile's own graph (`lockfiles.dependency_paths`: npm v2/v3 following Node's lookup,
uv from the project's entry, Poetry from the packages nothing else needs, since its lock doesn't name the project's own
dependencies). Checked on public lockfiles:

| Lockfile | Packages | Path found | Pulled in by another |
|---|---|---|---|
| microsoft/vscode package-lock.json | 1,177 | 1,177 (100%) | 1,004 |
| pydantic/pydantic uv.lock | 165 | 164 (99.4%) | 105 |
| python-poetry/poetry poetry.lock | 77 | 77 (100%) | 52 |

Most packages arrive indirectly, so the path is what tells a team which line to change. requirements.txt and
Pipfile.lock record no graph, so they get no path. Poetry was dropped in the phase review: a direct dependency that
another package also needs (requests, needed by httpx) was shown as coming "via httpx", which names the wrong line to
change, and poetry.lock can't tell the two apart; the Poetry row above is kept as the measurement it was.

## Policy and fixing versions

- **The version a pull request installs is checked** against each advisory's affected spans, which the crawler now keeps
  with the version that fixes them: "Version 2.30.0, the one installed here, is affected by GHSA-j8r2-6x86-q33q,
  fixed in 2.31.0 (OSV)" (checked on that real advisory: 2.30.0 flagged, 2.31.0 not).
- **A repo's own policy** in `.github/stackvitals.toml`: `[deps.policy] max_severity` makes the pull request check flag
  a changed package whose open advisory is rated above it, with the command to accept it for a while
  (`/stackvitals accept package:<name> for 30d because ...`); `min_scorecard` lists the projects behind the
  dependencies scoring under it on the supply page, minus accepted packages. Licence rules were already there.
- **OpenSSF Scorecard stays one input:** it is shown on the supply page and never decides a package's verdict.

## Look-alike names (`lookalike.py`)

A package a pull request adds whose name is one edit from a popular one (a letter added, dropped, changed or two
swapped, or the same letters with other separators; popular names of 5+ letters, from the ~4,000 the evidence covers)
is a common way to slip in malware. Checked against OpenSSF's malicious-packages list (all 11,898 PyPI names; 20,000
sampled from the first 100,000 npm names) and against every less popular package in ten large public lockfiles:

| Names flagged by the name rule alone | Malicious | Legitimate |
|---|---|---|
| npm | 49 of 20,000 (0.25%) | 12 of 1,114 (1.1%) |
| PyPI | 873 of 11,898 (7.3%) | 0 of 81 |

On npm the name alone flags legitimate packages more often than malicious ones (most npm malware has spam names, not
look-alikes; the legitimate hits are old neighbours like extend and xtend). Downloads separate them: every legitimate
look-alike had at least 823,598 downloads last week; the 40 sampled malicious npm look-alikes had at most 75 (the PyPI
ones are gone, so their count is unknown). So a look-alike is flagged only under 1,000 downloads a week (or unknown):
with that, 0 of the 12 legitimate npm names and all 40 sampled malicious ones in each registry stay flagged. Only
added packages are checked, and the registry is asked only about a near name.

## Reachability for Go

Go's own free scanner, govulncheck, says for each advisory whether the code only requires the module, imports the
vulnerable package, or calls the vulnerable function. StackVitals reads its output when the workflow runs it (the
`govulncheck-json` input) and shows each advisory's reach, fix and call path on the supply page
(`deps/reach.py`). Run with govulncheck v1.1.4 on three public Go repos (charmbracelet/glow, jesseduffield/lazygit,
nektos/act; a fourth didn't build on this machine):

| Findings | Called | Imported only | Required only |
|---|---|---|---|
| Third-party modules (44) | 24 | 11 | 9 |
| All, with the standard library (97) | 60 | 20 | 17 |

So about half the third-party advisories a plain scan reports never run in the code. The standard library's count
depends on the Go version the scan used (here the machine's, not each repo's own), so it is shown apart.

## Before and after the 2026-10-23 changes (re-measured that day)

The same baseline script on the daily files built 2026-10-23 (`baseline-after-results.json`), beside the start of the
phase (`baseline-results.json`):

| | Start (files of 2026-10-21) | End (files of 2026-10-23) |
|---|---|---|
| Packages with evidence | 4,033 | 4,073 |
| Advisories on them | 5,374 | 5,476 (that day's refresh stopped at its cap; the rest carry over) |
| CVEs with an exploit score (EPSS) | 0 (CVE aliases not kept) | 4,541 of 4,575 |
| CVEs known exploited (CISA KEV) | 0 | 20, in 17 packages |
| Upgrades seen rolled back | 8 of 125,992 merged | 41 of 130,694, in 37 upgrade cells |
| Which direct dependency pulls a package in | not read | npm and uv lockfiles (poetry.lock doesn't say which packages are direct) |
| The version that fixes an advisory | not shown | shown, with whether the installed version is affected |
| Policy | licence deny list | plus a minimum Scorecard and a highest allowed severity |
| Look-alike package names | not checked | name rule with a download gate |
| Go reachability | none | govulncheck's called, imported and required findings |

The rollback count is still small against the upgrades, because most rollbacks leave no revert branch or named
rollback PR; it is a floor, as the section above says.

## The lockfiles OSV-Scanner reads, in every ecosystem it knows (`coverage.py`)

The Dependency Steward's deep evidence (upgrade outcomes, maintainers, publishers) covers the most-used npm and PyPI
packages. Known vulnerabilities now come for every package in the lockfiles OSV-Scanner reads, from Google's OSV-Scanner 2.7.0 (pinned,
SHA-256 checked) run on the lockfiles the Action reads through the API. On 100 crawled repos, 10 in each of Python,
TypeScript, JavaScript, Go, Rust, Java, Kotlin, C#, PHP and Ruby (drawn seeded from the MergeScout snapshot, 100+ stars),
read 2026-10-23 at their default branch:

| Lockfile | Found | Read | Packages | With a known vulnerability |
|---|---|---|---|---|
| pom.xml | 46 | 20 | 359 | 36 |
| requirements*.txt | 36 | 36 | 1,006 | 94 |
| Cargo.lock | 23 | 23 | 5,571 | 167 |
| package-lock.json | 22 | 22 | 9,891 | 314 |
| go.mod | 17 | 14 | 658 | 31 |
| pnpm-lock.yaml | 8 | 8 | 3,637 | 55 |
| bun.lock | 7 | 7 | 4,793 | 131 |
| Gemfile.lock | 6 | 6 | 854 | 35 |
| composer.lock | 6 | 6 | 423 | 23 |
| uv.lock | 5 | 5 | 380 | 20 |
| yarn.lock | 4 | 4 | 1,709 | 12 |
| Package.resolved | 3 | 1 | 5 | 0 |
| packages.lock.json | 1 | 1 | 29 | 0 |

- 65 of 100 repos have a lockfile the scanner reads; 24,003 packages in all (npm 16,431, crates.io 4,645, RubyGems 827, PyPI 794, Go 630, Packagist 423, Maven 218, NuGet 29, SwiftURL 5).
- The deep evidence covered 34% of those packages (npm and PyPI only); every one now
  gets a vulnerability check. 3,114 advisory matches; 45 of the 65 repos have a critical or high one.
- **What it can't read:** a Maven `pom.xml` whose versions come from a parent POM or properties elsewhere (20 of 46
  read); a `go.mod` with no requirements reads as empty. A Go repo first failed outright: the scanner's call analysis
  needs the source, and with Go installed (as on GitHub's runners) its failure stopped the scan, so it is turned off;
  reachability comes from govulncheck run in the repo's own workflow.
- **Malware:** matching GitHub's malware advisories and OSV's `MAL-` records by name and version is tested on recorded
  answers, but no sample of real compromises was replayed, so how many it catches, and how much sooner than OSV, is
  not measured.

## Release signs (`release_signs.py`)

Before any advisory exists, the pull request check compares each npm or PyPI version it brings in with the one it
replaces. On the newest two stable versions of 147 npm and 149 PyPI packages from the crawl's map (judged three days after
release, so release age never fires here):

| Sign | npm | PyPI |
|---|---|---|
| Adds an install script | 0 of 147 | 0 of 149 |
| Build provenance on the old version, gone on the new | 0 | 0 |
| New dependencies | 8 | 6 |

The first two never fired on ordinary releases, so they make a package "look first". New dependencies fire on about 5%
of releases (each a real, named addition) and also make it "look first", since the March 2026 axios compromise worked by
adding one. Release age alone (under 48 hours) is a note, not a verdict: update bots open most pull requests within hours
of a release. Recall can't be replayed live: the compromised versions were pulled from the registries.

## Release signs on known attacks (`incidents.py`)

The release signs above were measured on normal releases only. Here they meet seven known npm attacks. npm removes a bad
version's package files but keeps its publish time, so two things can be measured: how soon GitHub listed the attack
(the malware lane matches GitHub's malware advisories on the next scheduled or post-CI run, up to 3 hours later), and,
where the advisory says what the bad version changed, which sign it would have set off. The signs are judged from the
advisory's own words (in `incidents-results.json`), not from the removed package.

| Attack | Released | GitHub advisory | Hours later | What the advisory says changed | Release sign |
|---|---|---|---|---|---|
| event-stream 3.3.6 | 2018-09-09 | GHSA-mh6f-8j2x-4483 | 1,888 | a new dependency (flatmap-stream) | look first |
| ua-parser-js 0.7.29 | 2021-10-22 | GHSA-pjwm-rvh2-c87w | 8.4 | not stated | can't tell |
| eslint-config-prettier 8.10.1 | 2025-07-18 | GHSA-f29h-pxvx-f335 | 26.3 | an install script (install.js) | look first |
| nx 21.5.0 | 2025-08-26 | GHSA-cxm3-wv7p-598c | 18.2 | not stated | can't tell |
| chalk 5.6.1 | 2025-09-08 | GHSA-2v46-p5h4-248w | 4.0 | code only (a browser interceptor) | a note only |
| debug 4.4.2 | 2025-09-08 | GHSA-4x49-vf9v-38px | 176.3 | code only (the same interceptor) | a note only |
| @ctrl/tinycolor 4.1.1 | 2025-09-15 | GHSA-qjqf-7j6f-82c4 | 3.8 | not stated | can't tell |

- **The malware lane:** chalk, nx and tinycolor got malware-type advisories 4 to 18 hours after release; StackVitals
  flags them on its next run after that. eslint-config-prettier's advisory is a reviewed one (26 hours after release),
  which the scan picks up through OSV. debug's malware advisory of 2025-09-08 was withdrawn as a duplicate of a reviewed one listed a
  week later, so the lane would have seen it only through the scan.
- **The release signs:** the two attacks whose advisory names the mechanism that a sign looks at (a new dependency, an
  install script) would have been flagged "look first" before any advisory existed. The code-only attacks (chalk, debug)
  set off nothing but the "released under 48 hours ago" note: no sign reads code. For three attacks the advisory doesn't
  say what changed.
- **What it can't show:** the removed packages themselves, so this is a judgement from the advisories' words, on seven
  attacks, not a run of the code on the bad versions.

## Reproduce

```
GH_TOKEN=... python bench/accuracy/deps/incidents.py
python bench/accuracy/deps/baseline.py --deps <crawl deps folder>
python bench/accuracy/deps/exploits.py --deps <crawl deps folder>   # reads KEV and EPSS (free, no key)
GH_TOKEN=... python bench/accuracy/deps/lookalike.py --deps <crawl deps folder> --work <folder with OpenSSF's tree listings>
GH_TOKEN=... python bench/accuracy/deps/coverage.py run --scanner <osv-scanner 2.7.0 binary> --per-language 10   # then: score
python bench/accuracy/deps/release_signs.py run --per-ecosystem 150                                         # then: score
```

Results: `baseline-results.json` (counts only), `coverage-results.json`, `release-signs-results.json`.
