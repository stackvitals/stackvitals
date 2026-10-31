"""One package's dossier: use / monitor / investigate, and the evidence lines behind it, each with its counts, dates and
source. Never "safe": the evidence can only say what happened, not what will."""
import re
from datetime import datetime, timedelta

from mergescout.signals.bumps import _norm

# Upgrade rates are shown from 30 PRs in 10 repos; thinner cells only say how much evidence there is.
MIN_PRS, MIN_REPOS, MIN_CI = 30, 10, 20
EXCESS_FAIL = 0.10
# Full-crawl backtest (2026-10-20): flagged at 30% closed saw 1.45x the later closes of others, 40% 1.74x, 50% 1.79x, 60% 2.1x (13).
CLOSED_SHARE = 0.40
REVERT_SHARE = 0.03
STALE_DAYS = 730
ONE_MERGER = 0.8
SIZES = {"major": "Major upgrades", "minor": "Minor upgrades", "patch": "Patch upgrades", "nonmajor": "Minor or patch upgrades",
         "range": "Range updates", "unknown": "Upgrades (size unknown)", "combined": "Upgrades (sizes combined)"}
# A steady merge rate is a good sign only when outside PRs actually get merged.
GOOD_MERGE_RATE = 0.3
# Of 440 crawled repos with 20+ outside PRs last quarter, half had 24%+ still open and 1 in 10 had 70%+ (2026-10-18).
MIN_OPENED = 20
STILL_OPEN = 0.7
# A fall under 15 points from the first quarter shown to the last is noise (22 of 102 "falling" repos, 2026-10-18).
FALL_STEP = 0.15
# 3+ advisories first published in 90 days: 4% of mapped packages (nltk, vllm, axios, electron), 2026-10-18.
BURST = 3
# EPSS at 10% or more: a common action line, a few percent of all scored CVEs (FIRST's own guidance names 10%).
EPSS_ALARM = 0.1
BAD_STATUS = {"ARCHIVED", "QUARANTINED", "DEPRECATED"}


def _pct(x: float) -> int:
    return round(100 * x)


def _line(signal: str, text: str, source: str) -> dict:
    return {"signal": signal, "text": text, "source": source}


def dossier(ecosystem: str, name: str, ev: dict, now: datetime, versions: list[str] | None = None) -> dict:
    eco = ecosystem.lower()
    pkg = _norm(eco, name)
    key = f"{eco}:{pkg}"
    m, cells, osv = ev["map"].get(key), ev["ledger"].get(key, []), ev["osv"].get(key)
    out = {"ecosystem": eco, "package": pkg, "verdict": None, "reasons": [], "lines": [], "repo": (m or {}).get("repo"),
           "osv": {"open_severity": (osv or {}).get("open_severity")},
           "link": (m or {}).get("link"), "as_of": ev.get("built_at")}
    if not m and not cells:
        out["lines"].append(_line("info", f"{pkg} is not in the evidence set yet: packages join when crawled repos upgrade them.",
                                  "ledger"))
        return out
    lines = (_osv_lines(osv, ev.get("osv_complete", True), (m or {}).get("version"), versions) + _status_lines(m) + _link_lines(m, now)
             + _release_lines(m, now))
    upgrade_lines, upgrade_history = _ledger_lines(cells)
    trend_lines, trend_history = _trend_lines(ev["trends"].get(((m or {}).get("repo") or "").lower()), m)
    lines += upgrade_lines + trend_lines + _owner_lines((ev.get("owners") or {}).get(key), now)
    out["lines"] = lines
    alarms = [x["text"] for x in lines if x["signal"] == "alarm"]
    warns = [x["text"] for x in lines if x["signal"] == "warn"]
    if alarms:
        out["verdict"], out["reasons"] = "investigate", alarms
    elif warns:
        out["verdict"], out["reasons"] = "monitor", warns
    elif not (upgrade_history or trend_history):
        # Too little history for any verdict (real data: 925 of 2,266 packages); saying "monitor" would mean nothing.
        out["reasons"] = ["Not enough evidence yet: too few upgrades seen and no maintainer trend to judge by."]
    elif not any(x["signal"] == "good" and x["source"] in ("ledger", "crawl") for x in lines):
        # Real data: gradio's only history was a low upgrade merge rate; "use" with no good evidence would have no reasons.
        out["reasons"] = ["Not enough evidence for a verdict: the history seen shows nothing clearly good or bad."]
    else:
        # History leads: how upgrades and maintainers behaved says more than an empty advisory list.
        good = sorted((x for x in lines if x["signal"] == "good"), key=lambda x: x["source"] not in ("ledger", "crawl"))
        out["verdict"], out["reasons"] = "use", [x["text"] for x in good][:3]
    return out


def _vkey(v: str | None) -> tuple:
    from mergescout.signals.osv import version_key
    return version_key(v)


def _in_span(v: str, span: list) -> bool:
    """Whether a version sits in an advisory's [introduced, fixed) span, or [introduced, last_affected] when inclusive."""
    start, end, inclusive = span[0], span[1], len(span) > 2 and span[2]
    if _vkey(v) < _vkey(start):
        return False
    return end is None or (_vkey(v) <= _vkey(end) if inclusive else _vkey(v) < _vkey(end))


def affected_by(osv: dict | None, versions: list[str], disputed: bool = True) -> list[dict]:
    """The advisories whose spans hold one of these versions (a version that doesn't parse is never judged)."""
    known = [v for v in versions or [] if re.match(r"v?\d", v or "")]
    return [a for a in (osv or {}).get("affects") or [] if (disputed or not a.get("disputed"))
            and any(_in_span(v, s) for v in known for s in a["ranges"])]


def _osv_lines(osv: dict | None, complete: bool, version: str | None = None,
               versions: list[str] | None = None) -> list[dict]:
    if osv is None:
        return [_line("info", "Not checked against OSV yet.", "osv")]
    out = []
    ids = osv.get("ids") or []
    if osv.get("malware"):
        mal = ", ".join((osv.get("malware_ids") or [])[:2]) or next((i for i in ids if i.startswith("MAL-")), ids[0] if ids else "a MAL- record")
        bad = osv.get("malware_versions") or []
        if bad == ["all"]:
            what = "every published version is listed as malicious"
        elif bad:
            listed = ", ".join(bad[-5:]) + (f" and {len(bad) - 5} more" if len(bad) > 5 else "")
            what = f"version{'s' if len(bad) > 1 else ''} {listed} {'were' if len(bad) > 1 else 'was'} malicious"
            # In a PR the version being installed matters, not the registry's current one.
            hit = [v for v in versions or [] if v in bad]
            if versions:
                what += f"; the version installed here ({', '.join(hit or versions)}) is {'one' if hit else 'not one'} of them"
            elif version:
                what += f"; the current version {version} is {'one of them' if version in bad else 'not one of them'}"
        else:
            what = "a published version was malicious"
        out.append(_line("alarm", f"OSV has a malware record for it ({mal}): {what}.", "osv"))
    # Exploited in the wild beats any severity label; EPSS says how likely an open one is to be exploited soon.
    e = osv.get("epss_open")
    for k in osv.get("kev") or []:
        if k.get("fixed"):
            out.append(_line("warn", f"{k['id']} was exploited in the wild (CISA KEV); it is fixed in newer releases, so "
                                     "stay on a fixed version.", "kev"))
        else:
            odds = f"; EPSS puts the chance of exploitation in the next 30 days at {e['score']:.0%}" if e and e["id"] == k["id"] else ""
            out.append(_line("alarm", f"{k['id']} is being exploited in the wild (CISA KEV) and has no fixed version yet{odds}.",
                             "kev"))
    if e and e.get("score", 0) >= EPSS_ALARM and not any(k["id"] == e["id"] for k in osv.get("kev") or []):
        out.append(_line("alarm", f"An open advisory ({e['id']}) has a {e['score']:.0%} chance of being exploited in the next "
                                  "30 days (EPSS).", "epss"))
    # In a PR, the version being installed is checked against each advisory's affected spans.
    for v in versions or []:
        hit = [(a["id"], s) for a in affected_by(osv, [v]) for s in a["ranges"] if _in_span(v, s)]
        if hit:
            named = "; ".join(f"{i}, " + ("affected up to " + s[1] + ", no fix named" if len(s) > 2 and s[2]
                                          else "fixed in " + s[1] if s[1] else "no fixed version yet") for i, s in hit[:3])
            more = f" and {len(hit) - 3} more" if len(hit) > 3 else ""
            out.append(_line("alarm", f"Version {v}, the one installed here, is affected by {named}{more} (OSV).", "osv"))
    if osv.get("unfixed"):
        n = osv["unfixed"]
        out.append(_line("alarm", f"{n} {'advisory has' if n == 1 else 'advisories have'} no fixed version yet (OSV).", "osv"))
    # A range that ends at a "last affected" version is still open only while the newest release is inside it.
    inside = [b for b in osv.get("last_affected") or [] if version and _vkey(version) <= _vkey(b)]
    if inside:
        out.append(_line("alarm", f"The newest release {version} is still inside an advisory's affected range (up to "
                                  f"{inside[-1]}, OSV).", "osv"))
    if osv.get("disputed"):
        out.append(_line("info", f"{osv['disputed']} advisory is disputed by the maintainers (OSV)." if osv["disputed"] == 1
                         else f"{osv['disputed']} advisories are disputed by the maintainers (OSV).", "osv"))
    recent = osv.get("last_90d") or 0
    if recent >= BURST:
        out.append(_line("warn", f"{recent} advisories in the last 90 days: it is under active security scrutiny, so stay on "
                                 "the newest version (OSV).", "osv"))
    loading = "" if complete else " History still loading."
    if osv.get("advisories"):
        n = osv["advisories"]
        out.append(_line("info", f"{n} {'advisory' if n == 1 else 'advisories'} in total, {osv.get('last_2y', 0)} in the last 2 years "
                                 f"(latest {osv.get('latest')}, OSV).{loading}", "osv"))
    else:
        out.append(_line("good", f"No advisories in OSV.{loading}", "osv"))
    return out


def _status_lines(m: dict | None) -> list[dict]:
    if not m:
        return []
    out = []
    if m.get("deprecated"):
        why = f': "{m["deprecated_reason"]}"' if m.get("deprecated_reason") else ""
        end = "" if why and why[-2] in ".!?" else "."
        out.append(_line("alarm", f"Its registry marks the default version deprecated{why}{end}", "deps.dev"))
    if (m.get("status") or "").upper() in BAD_STATUS:
        out.append(_line("alarm", f"PyPI marks the project {m['status'].lower()}.", "deps.dev"))
    return out


def _link_lines(m: dict | None, now: datetime) -> list[dict]:
    if not m:
        return [_line("warn", "Its source repo isn't known yet.", "deps.dev")]
    repo, link = m.get("repo"), m.get("link")
    if not repo:
        # Established packages sometimes live off GitHub (beautifulsoup4, docutils); a young one with no source is the risky case.
        young = (m.get("first_release") or "") >= (now - timedelta(days=STALE_DAYS)).strftime("%Y-%m-%d")
        return [_line("alarm" if young else "warn",
                      f"No source repo is linked{' and it is under 2 years old' if young else ''}, so its maintainer history "
                      "can't be checked.", "deps.dev")]
    if link == "verified":
        return [_line("info", f"Source repo {repo}, proven by a signed build or publish attestation (deps.dev).", "deps.dev")]
    if link == "claimed_checked":
        return [_line("info", f"Source repo {repo}: the package names it and that repo's manifest names the package back.",
                      "deps.dev + GitHub")]
    if link == "claimed_unconfirmed":
        # Monorepos keep the manifest in a subfolder (swiper, postcss-lab-function, typescript): a warning only for young packages.
        young = (m.get("first_release") or "") >= (now - timedelta(days=STALE_DAYS)).strftime("%Y-%m-%d")
        if young:
            return [_line("warn", f"It names {repo} as its source, but no manifest we checked there names it back and the "
                                  "package is under 2 years old: check the real source before trusting this history.",
                          "deps.dev + GitHub")]
        return [_line("info", f"It names {repo} as its source; that repo's top-level manifest doesn't name it (monorepos and "
                              "generated packages often do this).", "deps.dev + GitHub")]
    return [_line("warn", f"It names {repo} as its source; not checked yet.", "deps.dev")]


def _release_lines(m: dict | None, now: datetime) -> list[dict]:
    if not m or not m.get("last_release"):
        return []
    last = m["last_release"]
    if last < (now - timedelta(days=STALE_DAYS)).strftime("%Y-%m-%d"):
        return [_line("warn", f"There has been no release since {last}.", "deps.dev")]
    return [_line("info", f"{m.get('releases_12m', 0)} releases in the last 12 months, latest {last} (version {m.get('version')}).",
                  "deps.dev")]


def _ledger_lines(cells: list[dict]) -> tuple[list[dict], bool]:
    strong = [c for c in cells if c["prs"] >= MIN_PRS and c["repos"] >= MIN_REPOS]
    if not strong and cells and sum(c["prs"] for c in cells) >= MIN_PRS and max(c["repos"] for c in cells) >= MIN_REPOS:
        # Real data: httpx had 33 upgrade PRs from 23 repos split across sizes; together they are enough evidence.
        keys = ("prs", "merged", "closed_unmerged", "ci_known", "ci_failed", "expected_failed", "extra_commits", "reverted")
        strong = [{"bump": "combined", "repos": max(c["repos"] for c in cells), "eco_inferred": all(c.get("eco_inferred") for c in cells),
                   **{k: sum(c.get(k) or 0 for c in cells) for k in keys}}]
    if not strong:
        if not cells:
            return [_line("info", "No Dependabot or Renovate upgrades of it seen in crawled repos yet.", "ledger")], False
        prs, repos = sum(c["prs"] for c in cells), max(c["repos"] for c in cells)
        return [_line("info", f"Not enough upgrade evidence yet ({prs} PRs from {repos} repos; rates are shown from "
                              f"{MIN_PRS} PRs in {MIN_REPOS} repos).", "ledger")], False
    out = []
    for c in sorted(strong, key=lambda c: list(SIZES).index(c["bump"]) if c["bump"] in SIZES else 99):
        label = SIZES.get(c["bump"], f"{c['bump'].capitalize()} upgrades")
        fail = c["ci_failed"] / c["ci_known"] if c["ci_known"] >= MIN_CI else None
        usual = (c.get("expected_failed") or 0) / c["ci_known"] if fail is not None else None
        closed, reverted = c["closed_unmerged"] / c["prs"], c["reverted"] / c["prs"]
        trouble = (fail is not None and fail - usual >= EXCESS_FAIL) or closed >= CLOSED_SHARE or reverted >= REVERT_SHARE
        if trouble and fail is not None and fail - usual >= EXCESS_FAIL:
            text = (f"{label} failed CI in {_pct(fail)}% of {c['ci_known']} PRs from {c['repos']} repos; "
                    f"usually {_pct(usual)}% in these repos")
        else:
            text = f"{label}: {_pct(c['merged'] / c['prs'])}% of {c['prs']} PRs in {c['repos']} repos merged"
            if fail is not None:
                text += f"; CI failed in {_pct(fail)}% (usually {_pct(usual)}% in these repos)"
        if closed >= CLOSED_SHARE:
            text += f"; {_pct(closed)}% closed without merging"
        if c["reverted"]:
            text += f"; {c['reverted']} reverted within 14 days"
        if c.get("extra_commits"):
            text += f"; {c['extra_commits']} needed extra commits"
        if c.get("eco_inferred"):
            # Renovate's "update dependency X" names no ecosystem; a guess from the repo's language can count another package
            # (real data: Docker "ubuntu" bumps counted as npm's "ubuntu"), so it is shown but never decides.
            out.append(_line("info", text + " (crawl, last 180 days; ecosystem guessed from the repo's language).", "ledger"))
            continue
        merged = c["merged"] / c["prs"]
        out.append(_line("warn" if trouble else "good" if merged >= 0.5 else "info", text + " (crawl, last 180 days).", "ledger"))
    return out, any(not c.get("eco_inferred") for c in strong)


def _trend_lines(trend: dict | None, m: dict | None) -> tuple[list[dict], bool]:
    if not m or not m.get("repo"):
        return [], False
    if not trend:
        return [_line("info", "Its source repo isn't crawled yet; maintainer trends arrive once it is.", "crawl")], False
    q, d = trend.get("quarters") or [], trend.get("direction") or {}
    rates = [x["outside_merge_rate"] for x in q if x.get("outside_merge_rate") is not None]
    hours = [x["first_response_hours"] for x in q if x.get("first_response_hours") is not None]
    out, last = [], (q[-1] if q else {})
    opened, decided = last.get("outside_opened") or 0, last.get("outside_decided") or 0
    # Merge rates count decided PRs only; a quarter where most outside PRs got no decision is the real signal (dask: 71 of 89).
    if opened >= MIN_OPENED and (opened - decided) / opened >= STILL_OPEN:
        out.append(_line("warn", f"{opened - decided} of {opened} outside PRs opened last quarter are still open.", "crawl"))
    quiet = 0
    for x in reversed(q):
        if (x.get("outside_opened") or 0) > 0:
            break
        quiet += 1
    known = [x for x in q if x.get("outside_merge_rate") is not None]
    if 2 <= quiet < len(q) and known:
        # Real data (httpx): 23-28 outside PRs a quarter, then none at all; the empty quarters are the news.
        k = known[-1]
        out.append(_line("warn", f"No outside pull requests were opened in the last {quiet} quarters; before that, about "
                                 f"{_pct(k['outside_merge_rate'])}% of them were merged ({k['quarter']}).", "crawl"))
    elif not rates and not hours and last.get("top_merger_share") is None:
        out.append(_line("info", "Its repo had too few outside PRs in the last year to show a trend.", "crawl"))
    n = f" ({decided} decided)" if decided else ""
    if d.get("outside_merge_rate") == "falling" and rates:
        out.append(_line("warn" if rates[0] - rates[-1] >= FALL_STEP else "info",
                         f"Outside PRs merged fell from {_pct(rates[0])}% to {_pct(rates[-1])}% over the last 4 quarters{n}.", "crawl"))
    elif d.get("outside_merge_rate") and rates:
        good = rates[-1] >= GOOD_MERGE_RATE
        out.append(_line("good" if good else "info", f"Outside PRs merged: {d['outside_merge_rate']}, about {_pct(rates[-1])}% "
                                                    f"last quarter{n}.", "crawl"))
    if d.get("first_response_hours") == "slower" and hours:
        out.append(_line("warn", f"First maintainer answers slowed from about {hours[0]:.0f} to {hours[-1]:.0f} hours.", "crawl"))
    elif d.get("first_response_hours") and hours:
        out.append(_line("good", f"First maintainer answers: {d['first_response_hours']}, about {hours[-1]:.0f} hours last quarter.",
                         "crawl"))
    top = (q[-1] if q else {}).get("top_merger_share")
    # One lead merging and a place among peers are facts to know, not warnings (real data: one lead is normal, and big
    # libraries merge fewer drive-by PRs); only a worsening trend warns.
    if top is not None and top >= ONE_MERGER:
        out.append(_line("info", f"Merging rests on one person: {_pct(top)}% of last quarter's merges.", "crawl"))
    names = {"outside_merge_rate": "Outside PRs merged", "first_response_hours": "First maintainer answers"}
    for metric, peer in (trend.get("peers") or {}).items():
        out.append(_line("info", f"{names.get(metric, metric)} against {peer['peers']} similar repos: {peer['place']}.", "crawl"))
    return out, any(v for v in d.values())


OWNER_DAYS = 90


def _owner_lines(watch: dict | None, now: datetime) -> list[dict]:
    """Recent changes in who publishes it (a takeover usually starts here), and who does now."""
    if not watch:
        return []
    out, recent = [], (now - timedelta(days=OWNER_DAYS)).strftime("%Y-%m-%d")
    for e in watch.get("events") or []:
        if e["date"] < recent:
            continue
        if e["kind"] == "trusted_lost":
            out.append(_line("alarm", f"On {e['date']}, release {e.get('version')} was published without the trusted CI "
                                      "publishing used before.", "registry watch"))
        elif e["kind"] == "maintainer_added":
            out.append(_line("warn", f"New maintainer{'s' if len(e['who']) > 1 else ''} added on {e['date']}: "
                                     f"{', '.join(e['who'])}.", "registry watch"))
        elif e["kind"] == "organization_changed":
            out.append(_line("warn", f"The owning organization changed on {e['date']}: {e.get('from')} to {e.get('to')}.",
                             "registry watch"))
        elif e["kind"] == "maintainer_removed":
            out.append(_line("info", f"Maintainer{'s' if len(e['who']) > 1 else ''} removed on {e['date']}: {', '.join(e['who'])}.",
                             "registry watch"))
    cur = watch.get("current") or {}
    names = ", ".join(cur.get("maintainers") or []) or "none listed"
    if "trusted" in cur:
        how = "came through trusted CI publishing" if cur.get("trusted") else f"was published by {cur.get('publisher')}"
        out.append(_line("info", f"Latest release {cur.get('version')} {how}; maintainers: {names} (watched since "
                                 f"{watch.get('since')}).", "registry watch"))
    else:
        org = f", organization {cur['organization']}" if cur.get("organization") else ""
        out.append(_line("info", f"Owners on PyPI: {names}{org} (watched since {watch.get('since')}).", "registry watch"))
    return out
