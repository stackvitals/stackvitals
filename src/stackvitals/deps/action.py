"""The PR check: when a pull request changes a lockfile, each added or changed package's verdict goes to the job summary
and annotations. Files are read through the API at the base and head commits; no PR code is checked out or run."""
import codecs
import json
import subprocess
import time
from datetime import datetime, timezone

from stackvitals.ci.api import ActionsAPI, APIError, OutOfBudget
from stackvitals.ci.cli import home
from stackvitals.deps.dossier import dossier
from stackvitals.deps.evidence import load_evidence
from stackvitals.deps.lockfiles import dependency_paths, foreign_sources, is_lockfile, parse_lockfile
from stackvitals.deps.lookalike import judge
from stackvitals.deps import guarddog, release, vulns
from stackvitals.flow.report import _md

MARKER = "<!-- stackvitals:deps -->"
NOTE = ("Evidence from upgrade PRs across public repos, maintainer history, the package's registry and OSV. Verdicts weigh "
        "what happened, not what will.")
ORDER = {"investigate": 0, "monitor": 1, "use": 2, None: 3}
FLAGGED = ("investigate", "monitor")
# GitHub caps a comment at 65,536 characters: every flagged package is listed, then this many others.
MAX_FLAGGED, MAX_OTHERS = 100, 30
MAX_PAGES = 10


def lockfile_changes(filename: str, base: str | None, head: str) -> list[dict]:
    """Packages added or moved to other versions between two versions of a lockfile (removals need no check)."""
    def versions(text):
        out = {}
        for eco, name, version in parse_lockfile(filename, text) if text else []:
            out.setdefault((eco, name), set()).add(version or "")
        return out
    old, new = versions(base), versions(head)
    changes = []
    for (eco, name), vs in sorted(new.items()):
        if (eco, name) not in old:
            changes.append({"ecosystem": eco, "package": name, "change": "added", "from": [], "to": sorted(v for v in vs if v)})
        elif vs != old[(eco, name)]:
            changes.append({"ecosystem": eco, "package": name, "change": "changed", "from": sorted(v for v in old[(eco, name)] if v),
                            "to": sorted(v for v in vs if v)})
    return changes


def _annotation(text: str) -> str:
    # Workflow commands treat %, CR and LF specially.
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _prop(text: str) -> str:
    # Property values (file=, title=) come from the PR, so ":" and "," are escaped too, or a path could add commands.
    return _annotation(text).replace(":", "%3A").replace(",", "%2C")


def _cell(text) -> str:
    # Registry text and package names are untrusted: one line, no table breaks, no @mentions that ping people.
    return _md(" ".join(str(text).split())).replace("@", "@​")


def _text(raw: bytes) -> str:
    # PowerShell's "pip freeze > requirements.txt" writes UTF-16; editors add a UTF-8 BOM.
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def _vulns(found: dict | None) -> list[str]:
    if not found:
        return []
    if found.get("error"):
        return ["", f"Known vulnerabilities weren't checked this time ({_cell(found['error'])})."]
    added, removed = found.get("added") or [], found.get("removed") or []
    if not added and not removed:
        return ["", f"No known vulnerabilities added or removed in the {found.get('files', 0)} changed lockfile(s) (OSV)."]
    lines = ["", f"**Known vulnerabilities this PR adds: {len(added)}**" + (f"; it removes {len(removed)}." if removed else ".")]
    if added:
        lines += ["", "| Package | Advisory | Severity | Fixed in | Lockfile |", "|---|---|---|---|---|"]
        lines += [f"| {_cell(f['ecosystem'] + ':' + f['package'] + ' ' + f['version'])} | {_cell(f['id'])} | "
                  f"{'**malware**' if f['malware'] else f['severity']} | {_cell(f['fixed'] or 'no fix yet')} | {_cell(f['file'])} |"
                  for f in added[:MAX_FLAGGED]]
    return lines


def _report(rows: list[tuple[str, dict, dict | None]], has_evidence: bool, unread: list[tuple[str, str]], cut: bool,
            found: dict | None = None) -> str:
    lines = [MARKER, "### Dependency changes in this PR", ""]
    flagged = [r for r in rows if (r[2] or {}).get("verdict") in FLAGGED][:MAX_FLAGGED]
    others = [r for r in rows if (r[2] or {}).get("verdict") not in FLAGGED][:MAX_OTHERS]
    if rows:
        lines += ["| Package | Change | Verdict | Why |", "|---|---|---|---|"]
    for path, c, d in flagged + others:
        change = f"added {', '.join(c['to'])}" if c["change"] == "added" else f"{', '.join(c['from'])} → {', '.join(c['to'])}"
        verdict = (d or {}).get("verdict") or "not enough evidence"
        why = ((d or {}).get("reasons") or [""])[0]
        via = f" (via {' → '.join(c['via'])})" if c.get("via") else ""
        lines.append(f"| {_cell(c['ecosystem'] + ':' + c['package'] + via)} | {_cell(change)} | "
                     f"{'**' + verdict + '**' if verdict == 'investigate' else verdict} | {_cell(why)} |")
    hidden = len(rows) - len(flagged) - len(others)
    if hidden:
        lines.append(f"\n…and {hidden} more changed packages{' with nothing to flag' if len(flagged) < MAX_FLAGGED else ''}.")
    lines += _vulns(found)
    if unread:
        lines.append("\nThese lockfiles couldn't be read: " + "; ".join(f"{_cell(p)} ({_cell(why[:80])})" for p, why in unread) + ".")
    if cut:
        lines.append(f"\nOnly the first {MAX_PAGES * 100:,} changed files were checked for lockfiles.")
    note = NOTE if has_evidence else "The dependency evidence isn't available to this run yet, so only the changes are listed."
    return "\n".join(lines) + f"\n\n<sub>{note}</sub>\n"


def accepted_packages(api, now: datetime) -> set[str]:
    """Packages a `/stackvitals accept package:<name>` decision still covers, read from the data branch (a PR's check
    has no checkout of it); nothing when it can't be read."""
    from stackvitals.core.decisions import STATE
    try:
        state = json.loads(api.file(STATE, "stackvitals-data"))
    except Exception:  # noqa: BLE001 - the check never fails over the decisions file
        return set()
    day = now.date().isoformat()
    return {v["id"] for v in state.values() if isinstance(v, dict) and v.get("kind") == "package"
            and v.get("verb") == "accept" and (not v.get("until") or v["until"] >= day)}


def apply_policy(d: dict | None, policy: dict | None, name: str, versions: list[str] | None = None,
                 accepted: set[str] = frozenset()) -> dict | None:
    """The repo's severity policy on one package's verdict: an advisory rated above max_severity that holds the version
    installed here (or, without one, an open advisory) makes it "investigate", unless a decision accepted the package."""
    from stackvitals.core.config import SEVERITIES
    from stackvitals.deps.dossier import affected_by
    limit = (policy or {}).get("max_severity")
    osv = (d or {}).get("osv") or {}
    if name in accepted:
        return d
    if versions and osv.get("affects") is not None:
        labels = [a["severity"].lower() for a in affected_by(osv, versions, disputed=False)
                  if (a.get("severity") or "").lower() in SEVERITIES]
        worst = max(labels, key=SEVERITIES.index, default=None)
    else:
        worst = osv.get("open_severity")
    if not d or not limit or not worst or worst.lower() not in SEVERITIES:
        return d
    if SEVERITIES.index(worst.lower()) <= SEVERITIES.index(limit):
        return d
    what = "an advisory affecting the version installed here" if versions and osv.get("affects") is not None else "an open advisory"
    why = (f"Policy: {what} is rated {worst.lower()}, above this repo's max_severity ({limit}); to accept it "
           f"for a while, comment `/stackvitals accept package:{name} for 30d because <reason>`.")
    return {**d, "verdict": "investigate", "reasons": [why, *(d.get("reasons") or [])]}


def run_deps_action(env: dict, now: datetime | None = None, make_api=ActionsAPI, evidence=..., comments: bool = False,
                    policy: dict | None = None, registry=None, outside: bool = True, scan=False,
                    deep: bool = False, deny: list[str] | None = None) -> dict | None:
    """One check of a pull request's lockfile changes; other events are skipped."""
    if env.get("GITHUB_EVENT_NAME") != "pull_request":
        return None
    now = now or datetime.now(timezone.utc)
    pr = json.loads(open(env["GITHUB_EVENT_PATH"], encoding="utf-8").read()).get("pull_request") or {}
    repo, token = env["GITHUB_REPOSITORY"], env.get("STACKVITALS_TOKEN") or env.get("GITHUB_TOKEN")
    api = make_api(token, repo, max_requests=80)
    files, cut = [], False
    for page in range(1, MAX_PAGES + 1):
        batch = api._get(f"/repos/{repo}/pulls/{pr['number']}/files", {"per_page": 100, "page": page})
        files += batch
        if len(batch) < 100:
            break
    else:
        cut = True
    # A renamed lockfile is compared with its old path, or every package would look new.
    locks = [(f["filename"], f.get("previous_filename") if f.get("status") == "renamed" else f["filename"]) for f in files
             if is_lockfile(f["filename"]) and f.get("status") != "removed"]
    if evidence is ...:
        evidence = load_evidence(token, home() / "deps")
    accepted = accepted_packages(api, now)
    rows, unread = [], []
    # The packages the evidence covers are the popular names a look-alike would imitate.
    popular = {}
    for key in (evidence or {}).get("map") or {}:
        eco, _, name = key.partition(":")
        popular.setdefault(eco, set()).add(name)
    own = registry is None and outside
    if own:
        import httpx
        registry = httpx.Client(timeout=15, headers={"User-Agent": "stackvitals"})
    checked = deep_checked = 0
    # The job has 20 minutes: GuardDog gets 5 of them in all, and each scan of the PR's lockfiles 4 (base and head).
    deep_until = time.monotonic() + 300
    for path, old_path in locks:
        try:
            head = _text(api.file(path, pr["head"]["sha"]))
            try:
                base = _text(api.file(old_path, pr["base"]["sha"])) if old_path and is_lockfile(old_path) else None
            except APIError as exc:
                if "HTTP 404" not in str(exc):
                    raise
                base = None  # a lockfile the PR adds
            changes, foreign = lockfile_changes(path, base, head), foreign_sources(path, head)
        except (APIError, OutOfBudget, ValueError) as exc:
            # One unreadable file (conflict markers, a GitHub hiccup) is reported; the rest are still checked.
            unread.append((path, str(exc) or type(exc).__name__))
            continue
        for c in changes:
            d = apply_policy(dossier(c["ecosystem"], c["package"], evidence, now, versions=c["to"]) if evidence else None,
                             policy, c["package"], versions=c["to"], accepted=accepted)
            # Only a package the PR adds can be a look-alike slipped in; the registry is asked only for a near name.
            fake = judge(c["ecosystem"], c["package"], popular, registry) if c["change"] == "added" and popular else None
            if fake:
                worse = min(fake["verdict"], (d or {}).get("verdict"), key=lambda v: ORDER.get(v, 3))
                d = {**(d or {}), "verdict": worse, "reasons": fake["reasons"] + list((d or {}).get("reasons") or [])}
            # Signs before any advisory (only hours old, a new install script or dependencies, provenance gone): look first.
            if registry is not None and checked < release.MAX_PACKAGES and c["ecosystem"] in ("npm", "pypi"):
                checked += 1
                signs = release.release_signs(registry, c["ecosystem"], c["package"], c["from"], c["to"], now)
                # Update bots open most PRs within hours of a release, so age alone is a note; another sign makes it a look.
                strong = [s for s in signs if not s.startswith("Released ")]
                if strong:
                    worse = min("monitor", (d or {}).get("verdict"), key=lambda v: ORDER.get(v, 3))
                    d = {**(d or {}), "verdict": worse, "reasons": signs + list((d or {}).get("reasons") or [])}
                elif signs:
                    d = {**(d or {}), "verdict": (d or {}).get("verdict"), "reasons": list((d or {}).get("reasons") or []) + signs}
            # Opt-in: GuardDog reads the new version's code for what malware does.
            left = deep_until - time.monotonic()
            if (deep and outside and deep_checked < guarddog.MAX_PACKAGES and c["ecosystem"] in guarddog.ECOSYSTEMS and c["to"]
                    and left > 20):
                deep_checked += 1
                rules = guarddog.scan(c["ecosystem"], c["package"], max(c["to"], key=release._key), timeout=int(min(180, left)))
                if rules:
                    worse = min("monitor", (d or {}).get("verdict"), key=lambda v: ORDER.get(v, 3))
                    d = {**(d or {}), "verdict": worse, "reasons": [f"GuardDog flagged its code: {', '.join(rules)}."]
                         + list((d or {}).get("reasons") or [])}
            host = foreign.get((c["ecosystem"], c["package"]))
            if host:
                # Evidence about the registry package says nothing about a copy from elsewhere.
                d = {**(d or {}), "verdict": "monitor", "reasons": [f"Installed from {host}, not the public registry: the "
                                                                    "evidence here is about the registry package of that name."]}
            rows.append((path, c, d))
        # A flagged package another one pulls in names the way it came, so the team knows which dependency to change.
        flagged = {c["package"] for p, c, d in rows if p == path and (d or {}).get("verdict") in FLAGGED}
        for name, chain in dependency_paths(path, head, flagged).items() if flagged else ():
            for p, c, _d in rows:
                if p == path and c["package"] == name and len(chain) > 1:
                    c["via"] = chain
    if own:
        registry.close()
    rows.sort(key=lambda r: (ORDER[(r[2] or {}).get("verdict")], r[1]["package"]))
    # Known vulnerabilities the PR adds or removes, in any ecosystem: `scan` is True (download the pinned scanner) or a path.
    found = None
    targets = [(f["filename"], f.get("previous_filename") if f.get("status") == "renamed" else f["filename"]) for f in files
               if vulns.scannable(f["filename"]) and f.get("status") != "removed"]
    if scan and targets:
        try:
            binary = scan if not isinstance(scan, bool) else vulns.ensure_scanner(vulns.tool_dir(env))
            found = vulns.pr_diff(api, targets, pr["base"]["sha"], pr["head"]["sha"], binary, offline=not outside, timeout=240)
        except (vulns.ScannerError, APIError, OutOfBudget, OSError, ValueError, subprocess.TimeoutExpired) as exc:
            found = {"error": str(exc)[:200]}
    if found and found.get("new_packages") and deny and outside:
        import httpx

        from stackvitals.deps.supply import pr_licences
        # Licences the repo's policy denies, among the package versions this PR brings in.
        with httpx.Client(timeout=20) as c:
            found["licences"] = pr_licences(found["new_packages"], deny, c)
    out = {"lockfiles": len(locks), "changed": len(rows),
           **({"new_vulnerabilities": len(found.get("added") or [])} if found is not None else {}),
           "investigate": sum(1 for r in rows if (r[2] or {}).get("verdict") == "investigate"),
           "monitor": sum(1 for r in rows if (r[2] or {}).get("verdict") == "monitor")}
    if (found or {}).get("licences"):
        out["denied_licences"] = len(found["licences"])
    if (not rows and not unread and not cut and not (found or {}).get("added") and not (found or {}).get("removed")
            and not (found or {}).get("licences")):
        return out
    for path, c, d in rows:
        if d and d["verdict"] in FLAGGED:
            level = "warning" if d["verdict"] == "investigate" else "notice"
            print(f"::{level} file={_prop(path)},title={_prop(c['package'])}: {d['verdict']}::{_annotation(d['reasons'][0])}")
    for f in (found or {}).get("added") or []:
        print(f"::warning file={_prop(f['file'])},title={_prop(f['package'])}: {'malware' if f['malware'] else f['severity']}"
              f"::{_annotation(f['id'] + ' affects ' + f['version'] + (', fixed in ' + f['fixed'] if f['fixed'] else ''))}")
    for f in (found or {}).get("licences") or []:
        print(f"::warning title={_prop(f['package'])}: licence::{_annotation(f['package'] + ' ' + f['version'] + ' is ' + f['licence'] + ', which the licence policy denies')}")
    report = _report(rows, evidence is not None, unread, cut, found)
    if (found or {}).get("licences"):
        report += "\n**Licences the policy denies** (`[deps.licenses] deny`):\n" + "".join(
            f"- {f['package']} {f['version']} ({f['ecosystem']}): {f['licence']}\n" for f in found["licences"])
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(report)
    # Comments are opt-in, and a fork's PR gets a read-only token, so only same-repo PRs are commented on.
    same_repo = ((pr.get("head") or {}).get("repo") or {}).get("full_name") == repo
    if comments and same_repo and (rows or (found or {}).get("added") or (found or {}).get("licences")):
        try:
            old = [c for c in api._get(f"/repos/{repo}/issues/{pr['number']}/comments", {"per_page": 100})
                   if MARKER in (c.get("body") or "")]
            if old:
                api.send("PATCH", f"/repos/{repo}/issues/comments/{old[0]['id']}", {"body": report})
            else:
                api.send("POST", f"/repos/{repo}/issues/{pr['number']}/comments", {"body": report})
        except (APIError, OutOfBudget) as exc:
            print(f"Could not post the dependency note ({exc}); posting needs `pull-requests: write`.")
    return out
