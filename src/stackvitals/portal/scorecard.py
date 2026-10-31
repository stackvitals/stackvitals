"""Scorecards: rules in a TOML file in the portal repo (Python reads TOML without extra packages), each with a level.
A repo reaches a level when every rule of that level and the levels below passes or is exempt, and at least one rule of
that level passed. Data the token can't read is "not available", never a fail. Peer rules compare with similar public repos."""
import re
import tomllib
from datetime import datetime

from mergescout.bench.ci import tier
from stackvitals.ci.bench import _label
from stackvitals.portal import descriptor

LEVELS = ("bronze", "silver", "gold")
DEFAULT_RULES = """
# Bronze: someone owns it, changes are reviewed, and the basics are there.
[[rule]]
id = "codeowners"
check = "owners_present"
level = "bronze"

[[rule]]
id = "reviews-required"
check = "branch_rule"
rule = "pull_request"
level = "bronze"

[[rule]]
id = "readme-and-license"
check = "files"
files = ["readme", "license"]
level = "bronze"

# Silver: the owners are real, and CI and reviews do at least as well as half of similar public repos.
[[rule]]
id = "owners-valid"
check = "owners_valid"
level = "silver"

[[rule]]
id = "ci-first-try"
check = "ci_first_try"
peer = 50
level = "silver"

[[rule]]
id = "first-review"
check = "first_review"
peer = 50
level = "silver"

[[rule]]
id = "contributing"
check = "files"
files = ["contributing"]
level = "silver"

# Gold: first reviews faster than three quarters of similar repos, and security basics checked by OpenSSF Scorecard.
# (No "top quarter" CI rule: in many groups the top quarter is 100% first-try green, so it would ask for perfection.)
[[rule]]
id = "first-review-fast"
check = "first_review"
peer = 75
level = "gold"

[[rule]]
id = "security-policy"
check = "scorecard"
name = "Security-Policy"
min = 4
level = "gold"

[[rule]]
id = "token-permissions"
check = "scorecard"
name = "Token-Permissions"
min = 10
level = "gold"
"""
NA = "not available"


def _group(bench: dict | None, metric: str, repo: dict):
    groups = (bench or {}).get("groups") if isinstance(bench, dict) else None
    if not isinstance(groups, dict):
        return None
    lang, size = repo.get("language"), tier(repo.get("stars"))
    for key in (f"{lang}|{size}", f"{lang}|all", f"all|{size}", "all|all"):
        g = groups.get(key)
        if isinstance(g, dict) and isinstance(g.get(metric), dict):
            return key, g
    return None


def _peer(rule: dict, value: float, bench: dict | None, metric: str, repo: dict, lower_better: bool, show) -> tuple[str, str]:
    # "peer = 50" means better than half of similar repos: at least the median, or at most it for waits.
    peer = int(rule.get("peer") or 0)
    found = _group(bench, metric, repo) if peer in (25, 50, 75) else None
    if not found:
        if rule.get("min") is None:
            return NA, f"{show(value)}; no benchmark for similar repos yet"
        ok = value >= rule["min"] if not lower_better else value <= rule["min"]
        return ("pass" if ok else "fail"), f"{show(value)}, needs {show(rule['min'])}"
    key, g = found
    need = g[metric].get(f"p{100 - peer if lower_better else peer}")
    if not isinstance(need, (int, float)):
        return NA, f"{show(value)}; the benchmark lacks that percentile"
    ok = value <= need if lower_better else value >= need
    if show(value) == show(need) and value != need:
        # Values that round alike get a decimal, or "94%, needs 94%" would read as a pass.
        show = (lambda v: f"{v:.1%}") if not lower_better else (lambda v: f"{v:.1f} h")
    return ("pass" if ok else "fail"), (f"{show(value)}; better than {peer}% of {_label(key)} needs {show(need)} "
                                        f"({g.get('repos', '?')} repos)")


def _owners_present(repo, rule, bench):
    o = repo.get("owners")
    if not o:
        return NA, "owners not checked yet"
    where = "the repo root" if o.get("file") == "CODEOWNERS" else o.get("file")
    return ("fail", "no CODEOWNERS file") if o.get("status") == "none" else ("pass", f"CODEOWNERS file at {where}")


def _owners_valid(repo, rule, bench):
    o = repo.get("owners")
    if not o:
        return NA, "owners not checked yet"
    if o.get("status") == "none":
        return NA, "no CODEOWNERS file (the codeowners rule reports it)"
    seen = "owners checked" + (f" ({'; '.join(o['notes'])})" if o.get("notes") else "")
    return ("pass", seen) if o.get("status") == "valid" else ("fail", "; ".join(o.get("reasons") or []) or "no owners")


def _branch_rule(repo, rule, bench):
    rules = repo.get("rules")
    if not isinstance(rules, list):
        return NA, "branch rules not readable"
    branch = repo.get("default_branch") or "the default branch"
    if rule["rule"] in rules:
        return "pass", f"{rule['rule']} required on {branch}"
    if repo.get("protected"):
        return NA, (f"classic branch protection is on for {branch}; whether it requires {rule['rule']} needs an admin token "
                    "to read")
    return "fail", f"no {rule['rule']} rule on {branch}"


def _files(repo, rule, bench):
    docs = repo.get("docs")
    if not isinstance(docs, dict):
        return NA, "repo files not readable"
    if any(docs.get(f) is None for f in rule.get("files") or []):
        return NA, "some of these files couldn't be checked"
    missing = [f for f in rule.get("files") or [] if not docs.get(f)]
    shared = set(docs.get("org_defaults") or [])
    present = ", ".join(f + (" (org default from the .github repo)" if f in shared else "") for f in rule.get("files") or [])
    return ("fail", "missing: " + ", ".join(missing)) if missing else ("pass", "present: " + present)


def _ci_first_try(repo, rule, bench):
    modules = repo.get("modules") or {}
    text = modules.get("ci_first_try")
    try:
        share = modules.get("ci_first_try_share")
        # The number from app.json when there is one; the badge text ("85%") from older installs.
        value = share if isinstance(share, (int, float)) else float(str(text).rstrip("%")) / 100
        source = "CI Health"
    except (TypeError, ValueError):
        ci = repo.get("ci") or {}
        if not isinstance(ci.get("first_try_share"), (int, float)):
            return NA, "no push CI runs to measure"
        value, source = ci["first_try_share"], f"last {ci.get('pushes')} pushes"
    result, evidence = _peer(rule, value, (bench or {}).get("ci"), "first_try_share", repo, False, lambda v: f"{v:.0%}")
    return result, f"{evidence} ({source})"


def _first_review(repo, rule, bench):
    secs, source = ((repo.get("modules") or {}).get("flow") or {}).get("first_review_median_s"), "Team Flow"
    if not isinstance(secs, (int, float)):
        own = repo.get("reviews") or {}
        secs, source = own.get("first_review_median_s"), f"last {own.get('prs')} PRs"
    if not isinstance(secs, (int, float)):
        return NA, "too few recent PRs with a maintainer's review to measure"
    result, evidence = _peer(rule, secs / 3600, (bench or {}).get("flow"), "first_review_hours", repo, True, lambda v: f"{v:.0f} h")
    return result, f"{evidence} ({source})"


def _scorecard(repo, rule, bench):
    if not isinstance(repo.get("scorecard"), dict):
        return NA, "OpenSSF has no Scorecard result for this repo"
    score = repo["scorecard"].get(rule.get("name"))
    if not isinstance(score, (int, float)) or score < 0:
        return NA, f"no OpenSSF Scorecard result for {rule.get('name')}"
    ok = score >= rule.get("min", 10)
    when = (repo.get("openssf") or {}).get("date")
    return ("pass" if ok else "fail"), (f"OpenSSF Scorecard {rule.get('name')}: {score}/10, needs {rule.get('min', 10)}"
                                        + (f" (results of {str(when)[:10]})" if when else ""))


def _main_entity(d: dict) -> dict | None:
    entities = d.get("entities") or []
    return next((e for e in entities if e["kind"] in descriptor.NEEDS), entities[0] if entities else None)


def _catalog(repo, rule, bench):
    d = repo.get("descriptor")
    if not isinstance(d, dict):
        return NA, f"{descriptor.FILE} not checked yet"
    if not d.get("present"):
        return "fail", f"no {descriptor.FILE}"
    e = _main_entity(d)
    if not e:
        return "fail", "; ".join(d.get("problems") or []) or f"{descriptor.FILE} declares nothing"
    missing = [f for f in rule.get("fields") or ("owner", "lifecycle") if not e.get(f)]
    if missing:
        return "fail", f"{e['kind']} {e['name']}: no {', '.join(missing)}"
    what = ", ".join(x for x in (e.get("type"), e.get("lifecycle")) if x)
    return "pass", (f"{e['kind']} {e['name']}" + (f" ({what})" if what else "") + (f", owner {e['owner']}" if e.get("owner") else "")
                    + (f", system {e['system']}" if e.get("system") else ""))


def _catalog_owner(repo, rule, bench):
    d, o = repo.get("descriptor"), repo.get("owners")
    if not isinstance(d, dict) or not o:
        return NA, f"{descriptor.FILE} or owners not checked yet"
    if not d.get("present"):
        return NA, f"no {descriptor.FILE} (the catalog rule reports it)"
    if o.get("status") == "none":
        return NA, "no CODEOWNERS file (the codeowners rule reports it)"
    owners = list(dict.fromkeys(e.get("owner") for e in d.get("entities") or [] if e["kind"] in descriptor.NEEDS)) or [None]
    results = [descriptor.owner_check(x, o.get("owners") or []) for x in owners]
    bad = [why for result, why in results if result == "fail"]
    return ("fail", "; ".join(bad)) if bad else ("pass", "; ".join(why for _, why in results))


def _file(repo, rule, bench):
    path = rule["path"]
    f = (repo.get("files") or {}).get(path)
    if not isinstance(f, dict):
        return NA, f"{path} not checked yet"
    if not f.get("present"):
        return "fail", f"no {path}"
    for key in ("contains", "lacks"):
        if rule.get(key) and f.get(f"{key}:{rule[key]}") is None:
            return NA, f"{path} not read for this pattern yet"
    if rule.get("contains") and not f[f"contains:{rule['contains']}"]:
        return "fail", f"{path} doesn't match {rule['contains']}"
    if rule.get("lacks") and f[f"lacks:{rule['lacks']}"]:
        return "fail", f"{path} matches {rule['lacks']}"
    return "pass", (f"{path} present" + (f", matches {rule['contains']}" if rule.get("contains") else "")
                    + (f", without {rule['lacks']}" if rule.get("lacks") else ""))


CHECKS = {"owners_present": _owners_present, "owners_valid": _owners_valid, "branch_rule": _branch_rule, "files": _files,
          "ci_first_try": _ci_first_try, "first_review": _first_review, "scorecard": _scorecard, "catalog": _catalog,
          "catalog_owner": _catalog_owner, "file": _file}
CATALOG_FIELDS = {"type", "lifecycle", "owner", "system", "domain", "description", "tags", "links"}
# A group with a repeat inside, repeated again ("(\w+\s?)+"): Python's matcher can backtrack for hours on such patterns.
NESTED_REPEAT = re.compile(r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)(?:[+*]|\{\d*,)")


def _check_rule(r: dict) -> None:
    if not isinstance(r.get("check"), str) or not isinstance(r.get("level"), str):
        raise ValueError(f"rule {r.get('id')!r}: check and level are words, like check = \"file\" and level = \"bronze\"")
    if not r.get("id") or r.get("check") not in CHECKS or r.get("level") not in LEVELS:
        raise ValueError(f"rule {r.get('id')!r}: check {r.get('check')!r} or level {r.get('level')!r} is not known")
    if r["check"] == "file":
        path = r.get("path")
        if not isinstance(path, str) or not path.strip() or path.startswith("/") or ".." in path.split("/"):
            raise ValueError(f"rule {r['id']!r}: a file rule needs a path inside the repo, like docs/runbook.md")
        for key in ("contains", "lacks"):
            if key in r:
                try:
                    re.compile(r[key])
                except (re.error, TypeError) as exc:
                    raise ValueError(f"rule {r['id']!r}: {key} isn't a valid pattern ({exc})") from None
                if NESTED_REPEAT.search(r[key]):
                    raise ValueError(f"rule {r['id']!r}: {key} repeats a group that repeats, which can take hours on some "
                                     "files; simplify it") from None
    fields = r.get("fields") or []
    if r["check"] == "catalog" and (not isinstance(fields, list) or not all(isinstance(f, str) for f in fields)
                                    or not set(fields) <= CATALOG_FIELDS):
        raise ValueError(f"rule {r['id']!r}: fields can be {', '.join(sorted(CATALOG_FIELDS))}")
    if "from" in r:
        # "Enable later": the rule shows what it would say from today, and counts from this date.
        r["from"] = str(r["from"])[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["from"]):
            raise ValueError(f"rule {r['id']!r}: from must be a date like 2027-01-01")


def load_rules(text: str) -> tuple[list[dict], list[dict]]:
    """Rules and exemptions from TOML; a rule with an unknown check or level, or a broken file rule, is an error."""
    doc = tomllib.loads(text)
    rules = [r for r in doc.get("rule") or [] if isinstance(r, dict)]
    for r in rules:
        _check_rule(r)
    exemptions = [{**e, "until": str(e.get("until") or "9999-12-31")} for e in doc.get("exemption") or []
                  if isinstance(e, dict) and e.get("repo") and e.get("rule")]
    return rules, exemptions


def file_rules(rules: list[dict]) -> list[dict]:
    """The files the catalog run must read for the file rules, with their patterns."""
    return [{"path": r["path"], **{k: r[k] for k in ("contains", "lacks") if r.get(k)}} for r in rules if r["check"] == "file"]


def rules_or_default(text: str | None) -> tuple[list[dict], list[dict], list[str]]:
    rules, _ = load_rules(DEFAULT_RULES)
    if not text:
        return rules, [], []
    try:
        own, exemptions = load_rules(text)
        return (own or rules), exemptions, []
    except (ValueError, TypeError, tomllib.TOMLDecodeError) as exc:
        return rules, [], [f"portal.toml couldn't be used ({exc}); the default rules were used."]


def evaluate(repo: dict, rules: list[dict], exemptions: list[dict], now: datetime, bench: dict | None) -> dict:
    today = now.strftime("%Y-%m-%d")
    results = []
    for rule in rules:
        result, evidence = CHECKS[rule["check"]](repo, rule, bench)
        ex = next((e for e in exemptions if e["repo"] == repo["name"] and e["rule"] == rule["id"] and e["until"] >= today), None)
        if ex and result != "pass":
            result, evidence = "exempt", f"exempt until {ex['until']}: {ex.get('reason') or 'no reason given'}"
        if rule.get("from") and today < rule["from"]:
            result, evidence = "preview", f"counts from {rule['from']}; now: {result} ({evidence})"
        results.append({"id": rule["id"], "level": rule["level"], "result": result, "evidence": evidence})
    level = None
    for name in LEVELS:
        mine = [r for r in results if r["level"] == name and r["result"] != "preview"]
        if any(r["result"] == "fail" for r in mine) or not any(r["result"] in ("pass", "exempt") for r in mine):
            break
        level = name
    return {"level": level, "results": results, "not_available": sum(r["result"] == NA for r in results)}


def score_catalog(catalog: dict, rules: list[dict], exemptions: list[dict], now: datetime, bench: dict | None) -> dict:
    """A level and per-rule results for every checked repo; the counts per level and the rules that fail most often."""
    failed, levels = {}, {name: 0 for name in (*LEVELS, None)}
    for r in catalog["repos"]:
        if r.get("archived") or r.get("fork") or not r.get("checked"):
            continue
        r["score"] = evaluate(r, rules, exemptions, now, bench)
        levels[r["score"]["level"]] += 1
        for res in r["score"]["results"]:
            if res["result"] == "fail":
                failed[res["id"]] = failed.get(res["id"], 0) + 1
    return {"levels": levels, "failed": sorted(failed.items(), key=lambda kv: (-kv[1], kv[0]))}


RESULTS = ("pass", "fail", "exempt", "preview", "not available")


def pack(catalog: dict) -> dict:
    """The app's copy: each repo's results as [rule, result, evidence] rows pointing at one list of rules and one of
    evidence lines, which the app expands on load (data.js); scorecards were 72% of the file."""
    rules, said, repos = {}, {}, []
    for r in catalog.get("repos") or []:
        s = r.get("score")
        if s:
            rows = [[rules.setdefault((x["id"], x["level"]), len(rules)),
                     RESULTS.index(x["result"]) if x["result"] in RESULTS else x["result"],
                     said.setdefault(x["evidence"], len(said))]
                    for x in s.get("results") or []]
            r = {**r, "score": {**{k: v for k, v in s.items() if k != "results"}, "rows": rows}}
        repos.append(r)
    return {**catalog, "repos": repos, "packed": 2, "rule_index": [list(k) for k in rules], "result_codes": list(RESULTS),
            "evidence_index": list(said)}
