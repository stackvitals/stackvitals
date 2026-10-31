"""PR rules as code: each [[rules]] entry in the settings file is a `when` (author kind, paths, size, change risk, labels,
a first-time author) and a `then` (a label, reviewers, one comment). Matching open pull requests get each action once,
planned before the data branch's commit and sent after it like the rest of team automation; a dry-run rule only says
what it matched, and every rule can be replayed on past pull requests to see what it would have done."""
import re

from stackvitals.codeowners import matches as path_matches
from stackvitals.core.ai_outcomes import mode
from stackvitals.flow.analyze import is_bot

AUTHORS = ("agent", "person", "bot")
RISKS = ("medium", "high")
WHEN = {"author", "paths", "lines_over", "risk", "labels", "first_time"}
THEN = {"label", "reviewers", "comment"}
LOGIN = re.compile(r"@?[A-Za-z0-9][A-Za-z0-9-]{0,38}(/[A-Za-z0-9._-]{1,100})?")
MAX_COMMENT = 1000
MARK = "<!-- stackvitals-rule -->"


def check_rule(rule) -> str | None:
    """What is wrong with one [[rules]] entry, in words, or None when it can be used."""
    if not isinstance(rule, dict) or not isinstance(rule.get("name"), str) or not rule["name"].strip():
        return "each rule needs a name"
    when, then = rule.get("when") or {}, rule.get("then")
    if not isinstance(when, dict) or set(when) - WHEN:
        return f"when takes {', '.join(sorted(WHEN))}"
    if "author" in when and when["author"] not in AUTHORS:
        return f"author is one of {', '.join(AUTHORS)}"
    if "risk" in when and when["risk"] not in RISKS:
        return "risk is medium or high"
    if "paths" in when and not (isinstance(when["paths"], list) and all(isinstance(x, str) and x for x in when["paths"])):
        return "paths is a list of CODEOWNERS-style patterns"
    if "labels" in when and not (isinstance(when["labels"], list) and all(isinstance(x, str) for x in when["labels"])):
        return "labels is a list of label names"
    if "lines_over" in when and not (isinstance(when["lines_over"], int) and when["lines_over"] >= 0):
        return "lines_over is a number of lines"
    if "first_time" in when and not isinstance(when["first_time"], bool):
        return "first_time is true or false"
    if not isinstance(then, dict) or not then or set(then) - THEN:
        return f"then needs one or more of {', '.join(sorted(THEN))}"
    if "label" in then and not (isinstance(then["label"], str) and 0 < len(then["label"]) <= 50):
        return "label is a label name"
    if "reviewers" in then and not (isinstance(then["reviewers"], list) and then["reviewers"]
                                    and all(isinstance(x, str) and LOGIN.fullmatch(x) for x in then["reviewers"])):
        return "reviewers is a list of logins or @org/team names"
    if "comment" in then and not (isinstance(then["comment"], str) and 0 < len(then["comment"]) <= MAX_COMMENT):
        return f"comment is text up to {MAX_COMMENT} characters"
    if "dry_run" in rule and not isinstance(rule["dry_run"], bool):
        return "dry_run is true or false"
    return None


def _kind(p: dict) -> str:
    if mode(p) == "agent":
        return "agent"
    return "bot" if is_bot(p) else "person"


def matches(p: dict, when: dict, ctx: dict) -> bool:
    if "author" in when and _kind(p) != when["author"]:
        return False
    if "paths" in when and not any(path_matches(pat, path) for path in p.get("paths") or [] for pat in when["paths"]):
        return False
    if "lines_over" in when and (p.get("add") or 0) + (p.get("del") or 0) <= when["lines_over"]:
        return False
    if "risk" in when:
        # "medium" matches medium and high; a PR without a risk score never matches a risk condition.
        level = (ctx.get("risk") or {}).get(p.get("n"))
        if level not in RISKS or RISKS.index(level) < RISKS.index(when["risk"]):
            return False
    if "labels" in when and not set(when["labels"]) & set(p.get("lb") or []):
        return False
    if "first_time" in when and ((p.get("au") or "").lower() in {x.lower() for x in ctx.get("first_time") or ()}) != when["first_time"]:
        return False
    return True


def plan(open_prs: list[dict], rules: list[dict], ctx: dict, state: dict) -> tuple[list[dict], dict, dict]:
    """(writes to make, the state to keep, {rule name: matched PR numbers}); each rule's action on a PR happens once."""
    done = list(state.get("rules_done") or [])
    seen, acts, report = set(done), [], {}
    for rule in rules:
        hit = [p for p in open_prs if not p.get("draft") and matches(p, rule.get("when") or {}, ctx)]
        report[rule["name"]] = [p["n"] for p in hit]
        if rule.get("dry_run"):
            continue
        then = rule["then"]
        for p in hit:
            # Each action once: a label someone removed afterwards stays removed.
            label = {"labels": [then["label"]]} if "label" in then and then["label"] not in (p.get("lb") or []) else None
            for kind, body in (("label", label), ("review", _reviewers(then.get("reviewers"), p)),
                               ("comment", _comment(then.get("comment"), rule))):
                key = f"{rule['name']}:{p['n']}:{kind}"
                if body and key not in seen:
                    acts.append({"kind": kind, "n": p["n"], "body": body})
                    seen.add(key)
                    done.append(key)
    return acts, {"rules_done": done[-2000:]}, report


def _reviewers(names, p: dict) -> dict | None:
    if not names:
        return None
    people = [x.lstrip("@") for x in names if "/" not in x and x.lstrip("@").lower() != (p.get("au") or "").lower()]
    teams = [x.split("/", 1)[1] for x in names if "/" in x]
    return {"reviewers": people, "team_reviewers": teams} if people or teams else None


def _comment(text, rule: dict) -> dict | None:
    return {"body": f"{text}\n\n_From the StackVitals rule \"{rule['name']}\"._\n{MARK}"} if text else None


def replay(rules: list[dict], past: list[dict], ctx: dict, examples: int = 10) -> dict:
    """What each rule would have matched among past pull requests (newest last), so a rule is checked before it acts."""
    out = {}
    for rule in rules:
        hit = [p["n"] for p in past if matches(p, rule.get("when") or {}, ctx)]
        out[rule["name"]] = {"matched": len(hit), "of": len(past), "examples": hit[:examples]}
    return out


def context(flow: dict, rules: list[dict]) -> dict:
    """The signals rules can ask about, worked out only when a rule needs them: change risk (shown only where the
    repo's own backtest says it works) and authors with no merged pull request yet."""
    ctx = {}
    wants = {k for r in rules for k in (r.get("when") or {})}
    closed = flow.get("closed") or []
    if "risk" in wants:
        from stackvitals.core import change_risk
        found = change_risk.assess(closed, change_risk.follow_up_fixes(closed), flow.get("open") or [])
        ctx["risk"] = {s["pr"]: s["level"] for s in found.get("open") or []}
    if "first_time" in wants:
        merged = {(p.get("au") or "").lower() for p in closed if p.get("mg")}
        ctx["first_time"] = {p.get("au") for p in flow.get("open") or [] if (p.get("au") or "").lower() not in merged}
    return ctx
