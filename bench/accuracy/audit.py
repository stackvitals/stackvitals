"""The human audit: plain-words question files for people to answer alone, and a reader for the answers they send back.

    python bench/accuracy/audit.py make --people 5            # writes .work/audit/person-A.txt ... and the key
    python bench/accuracy/audit.py read .work/audit/answers/   # checks the returned files, writes answers.csv

Each scenario shows the evidence the model labellers saw, as facts, with five plain options and never a model's answer.
A share of the items goes to everyone (agreement between people); every other item to two people."""
import argparse
import csv
import json
import random
import re
import sys
from collections import Counter
from glob import glob
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
from stackvitals.core.stats import wilson  # noqa: E402
WORK = HERE / ".work"
OUT = WORK / "audit"
SEED = 20261023
SHARED = 0.16
SIZES = {"ci": 80, "comment": 70, "deploy": 15, "incident": 25}

OPTIONS = {
    "ci": ["The change broke it: the new code, or a test for it, is wrong",
           "The test breaks now and then on its own (timing, order, luck), not because of this change",
           "Something outside the project failed: a download, a website, a package server, or GitHub's machine",
           "The project's CI setup broke (a setup step, a helper script, or a check on the pull request's title), not the code",
           "Can't tell from what's shown"],
    "comment": ["Acts for the project: triages it (a duplicate, by design, fixed in #12), asks the reporter for details "
                "needed to fix it, or points to a fix or a decision",
                "Helps with a real answer, without speaking for the project: a workaround, an explanation, a reproduction "
                "with its cause, or an offer to fix it that brings its own diagnosis",
                "Adds nothing yet: \"+1\", \"same here\", \"any update?\", a thank-you, their own different problem, or just "
                "\"I'd like to work on this\" or \"I can reproduce it\" with nothing more",
                "Something else",
                "Can't tell from what's shown"],
    "deploy": ["GitHub has deployment records for a live environment (see \"Deployment records\" above)",
               "A workflow publishes or deploys it, running on the main branch or on version tags (see the workflows above)",
               "Users get the GitHub releases listed above",
               "Every change merged into the main branch reaches users soon after (no separate release step)",
               "None of these, or can't tell"],
    "incident": ["Yes: the newest release before the report ({last}) brought the problem",
                 "An older release brought it (it was already broken in earlier versions)",
                 "No release brought it: it's the user's own setup, a build that wasn't released yet, or how to use it",
                 "It isn't a bug report at all (a question, a feature request, or a plan)",
                 "Can't tell from the report"],
}
QUESTION = {
    "ci": "Why did this check fail?",
    "comment": "What kind of reply is this?",
    "deploy": "How do new versions of this project reach its users?",
    "incident": "Did a release bring this problem?",
}
# One or two plain lines under each question, so every question can be read on its own.
CONTEXT = {
    "ci": "GitHub ran this project's automatic checks (build and tests) on a change, and one check failed.\n"
          "Decide why, from the facts and the log below.",
    "comment": "Someone opened an issue (a bug report or a question) on this project. Below is the first reply from\n"
               "someone who is NOT one of the project's maintainers (the people who run it). Decide what kind of reply it is.",
    "deploy": "A summary of one project over the last 90 days: its releases, its deployment records on GitHub, and its\n"
              "workflows (scripts GitHub runs, such as tests or publishing). Pick EVERY letter that fits, like \"B, C\".",
    "incident": "A problem report (an issue) from a project, and the releases published before it.\n"
                "Decide whether one of those releases brought the problem.",
}
HOW = {"deploy": "one or more letters, like B, C"}


def _jsonl(pattern: str) -> list[dict]:
    return [json.loads(line) for f in sorted(glob(str(WORK / pattern)))
            for line in Path(f).read_text(encoding="utf-8").splitlines() if line.strip()]


def _csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _cut(text: str, limit: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[: limit // 2] + "\n   [... middle cut ...]\n" + text[-limit // 2:]


def _lines(text: str, keep: int = 45) -> str:
    rows = [r for r in str(text or "").splitlines() if r.strip()]
    if len(rows) > keep:
        rows = rows[:8] + ["[... earlier lines cut ...]"] + rows[-(keep - 9):]
    return "\n".join("   | " + r[:220] for r in rows)


NOISE = re.compile(r"^\s*(\[command\].*\bgit(\.exe)?\"?\s|##\[(end)?group\]|Removing (SSH|HTTP|includeIf|auth)|Cleaning up orphan"
                   r"|Post job cleanup|Temporarily overriding HOME|Adding repository directory|git version \d|[0-9a-f]{40}$"
                   r"|.*git-credentials-|includeif\.gitdir|Removing credentials|Terminate orphan process|^\s*\.\.\.\s*$)")
ERR = re.compile(r"(?i)##\[error\]|\berror\b|\bfail(ed|ure|s)?\b|exception|traceback|assert|timed? ?out|exit code [1-9]"
                 r"|not found|denied|refused|panic")
STAMP = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z\s")


def _log(text: str, keep: int = 30) -> str:
    # The lines that look like the failure (with a little around them) and the end, never the checkout and cleanup noise.
    rows = [STAMP.sub("", r.rstrip()) for r in str(text or "").splitlines() if r.strip() and not NOISE.search(r)]
    if not rows:
        return "   | (the log shows only setup and cleanup lines)"
    pick = set(range(max(0, len(rows) - 5), len(rows)))
    for i in reversed([i for i, r in enumerate(rows) if ERR.search(r)]):
        if len(pick) >= keep:
            break
        pick.update(range(max(0, i - 2), min(len(rows), i + 3)))
    out, last = [], -1
    for i in sorted(pick)[-keep - 4:]:
        if i > last + 1:
            out.append("[... lines left out ...]")
        out.append(rows[i][:200])
        last = i
    return "\n".join("   | " + r for r in out)


def _pick(rows: list[dict], n: int, key, rng: random.Random) -> list[dict]:
    # Stratified: every value of `key` gets its share, disputed items first within it.
    groups: dict = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r)
    for g in groups.values():
        rng.shuffle(g)
        g.sort(key=lambda r: not r.get("_disputed"))
    out, i = [], 0
    while len(out) < n and any(groups.values()):
        for g in list(groups.values()):
            if g and len(out) < n:
                out.append(g.pop(0))
        i += 1
    return out


def ci_items(rng) -> list[dict]:
    views = {str(r["id"]): r for r in _jsonl("flaky/view-0*.jsonl")}
    disputed = {r["id"] for r in _csv(HERE / "flaky" / "adjudication-flaky.csv")}
    rows = [{**r, "_disputed": r["id"] in disputed} for r in _csv(HERE / "flaky" / "items.csv") if r["id"] in views]
    picked = _pick(rows, SIZES["ci"], lambda r: (r["caused_by_change"], r["sample"]), rng)
    return [{"kind": "ci", "source": f"flaky:{r['id']}", "body": _ci_body(views[r["id"]])} for r in picked]


def _ci_body(v: dict, rerun: bool = True) -> str:
    files = v.get("files_changed") or []
    if isinstance(files, str):
        files = [x.strip(" '\"") for x in files.strip("[]").split(",") if x.strip()]
    event = {"pull_request": "a pull request (a proposed change)", "push": "a push (new commits)"}.get(v["event"], v["event"])
    return (f"Project: {v['repo']}\nThe check: job \"{v['job']}\" in {v['workflow']}\n"
            f"Started by: {event}, branch {v['branch']} ({v['change']})\n"
            f"Step that failed: {v.get('failing_step') or 'not shown'}\n"
            + (f"Run again on the exact same code: {v.get('rerun') or 'not run again'}\n" if rerun else "")
            + f"Files the change touched ({len(files)}): {', '.join(files[:12])}{' ...' if len(files) > 12 else ''}\n"
            f"The failing step's log (the lines that look like the error, and its end):\n{_log(v.get('log'))}")


def comment_items(rng) -> list[dict]:
    out = []
    for part, labels in (("community-main", "labels-main.csv"), ("community-validation", "labels-validation.csv")):
        views = {str(r["id"]): r for r in _jsonl(f"{part}/part-*.jsonl")}
        rows = [{**r, "_part": part, "_disputed": r.get("claude_kind") != r.get("gemini_kind")}
                for r in _csv(HERE / "community" / labels) if r["id"] in views]
        for r in _pick(rows, SIZES["comment"] // 2, lambda r: r["kind"], rng):
            v = views[r["id"]]
            body = (f"The issue's title: {v.get('title')}\n"
                    f"Who replied: a {str(v.get('picked_login_role') or '').lower() or 'user'} on GitHub, not a maintainer\n"
                    f"When: {round(float(v.get('picked_hours') or 0))} hours after the issue was opened\n"
                    f"Did a maintainer reply later: {'yes' if v.get('later_maintainer_reply') else 'no'}\n"
                    f"The reply:\n{_lines(_cut(v.get('picked_text'), 1200), 25)}")
            out.append({"kind": "comment", "source": f"{part}:{r['id']}", "body": body})
    return out


def _workflow(w: dict) -> str:
    text = str(w.get("file") or "")
    on = re.search(r"(?ms)^on:\s*(.*?)(?=^\S)", text + "\nend:")
    trig = " ".join((on.group(1) if on else "").split())[:220] or "not shown"
    steps = [re.sub(r"@[0-9a-f]{40}\s*(#\s*)?", "@", s.strip()) for s in re.findall(r"(?m)^\s*-?\s*(?:name|uses|run):\s*(.+)$", text)]
    steps = [s for s in steps if s not in ("|", ">", "|-", ">-")][:12]
    return (f" - {w.get('path')} (\"{w.get('name')}\", {w.get('state')})\n   runs on: {trig}\n"
            + (f"   steps: {'; '.join(s[:80] for s in steps)}\n" if steps else ""))


def deploy_items(rng) -> list[dict]:
    views = {r["repo"]: r for r in _jsonl("dora-sources/src-view-[0-9].jsonl") + _jsonl("dora-sources-more/src-view-[0-9].jsonl")}
    rows = [r for f in ("sources-labels.csv", "sources-more-labels.csv") for r in _csv(HERE / "dora" / f) if r["repo"] in views]
    out = []
    for r in _pick(rows, SIZES["deploy"], lambda r: r["truth"].split()[0] if r["truth"] else "", rng):
        v = views[r["repo"]]
        rel = v.get("releases_90d") or []
        wfs = [w for w in v.get("workflows") or [] if "unavailable" not in str(w.get("file"))]
        envs = v.get("deployments_90d_by_environment") or {}
        envs = ", ".join(f"{k}: {n}" for k, n in envs.items()) if isinstance(envs, dict) else str(envs)
        body = (f"Project: {v['repo']} (main branch: {v.get('default_branch')})\n"
                f"Changes added to the main branch in 90 days: {v.get('commits_to_default_90d')} commits\n"
                f"GitHub releases in 90 days: {v.get('releases_90d_total')}"
                + (f" (newest: {', '.join(x['tag'] + (' [pre-release]' if x.get('prerelease') else '') for x in rel[:6])})" if rel else "")
                + f"\nDeployment records on GitHub in 90 days, by environment: {envs or 'none'}\n"
                f"Workflows ({len(wfs)}; each with what starts it and its main steps):\n" + "".join(_workflow(w) for w in wfs[:12]))
        out.append({"kind": "deploy", "source": f"dora:{r['repo']}", "body": body})
    return out


def incident_items(rng) -> list[dict]:
    views = {str(r["id"]): r for r in _jsonl("incidents/view.jsonl")}
    rows = [{**r, "_named": "named" if r.get("culprit") not in ("none", "unclear", "") else r.get("culprit")}
            for r in _csv(HERE / "dora" / "incidents-labels.csv") if r["id"] in views]
    out = []
    for r in _pick(rows, SIZES["incident"], lambda r: r["_named"], rng):
        v = views[r["id"]]
        before = [x for x in v.get("releases_before") or [] if not x.get("pre")][-8:]
        last = before[-1]["tag"] if before else "none"
        body = (f"Project: {v['repo']}, issue opened {str(v.get('opened'))[:10]}\nTitle: {v.get('title')}\n"
                f"Labels the project put on it: {', '.join(v.get('labels') or []) or 'none'}\n"
                f"Releases before the report (oldest first): {', '.join(x['tag'] + ' (' + str(x['at'])[:10] + ')' for x in before) or 'none'}\n"
                f"Newest release before the report: {last}\n"
                f"The report:\n{_lines(_cut(v.get('body'), 2000), 30)}")
        out.append({"kind": "incident", "source": f"incidents:{r['id']}", "body": body, "last": last})
    return out


HEADER = """StackVitals: {count} questions for {person}
=================================================

Thank you for helping. Each question is one real case from a public GitHub project, with the facts you need
written out. No need to open any link or look anything up.

HOW TO ANSWER
  - After "Answer:" type ONE letter, A to E. Example:   Answer: B
  - Only the "How do new versions reach its users?" questions take more than one letter. Example:   Answer: B, C
  - "Note" is optional. Leave it empty, or add a few words if you were torn between two letters.
  - Not sure? Pick the letter that fits best. If it really can't be told, choose "Can't tell": that's a useful
    answer too.
  - Please answer on your own. Compare with the others only after everyone has sent their file back.
  - Each question takes about a minute. You can stop at any point and continue later: just save this file.
  - When you're done, send this same file back.

WORDS USED HERE
  - Pull request: a proposed change to a project's code, waiting to be reviewed and merged.
  - Check (CI): the build and tests GitHub runs automatically on every change.
  - Run again on the exact same code: GitHub ran the failed check a second time with nothing changed.
  - Issue: a bug report or a question posted on the project.
  - Maintainer: one of the people who run the project.
  - Release: a published version, like v1.2.0.
  - Workflow: a script GitHub runs when something happens (a push, a new tag, a timer), such as tests or publishing.

ABOUT YOU (once; no name needed)
  Your id: {person}
  Your role (for example backend developer, maintainer, SRE):
  Years of experience:
  May we thank you by name in the credits? (no / yes and the name):
"""


def make(people: int, out: Path | None = None) -> Path:
    out = out or OUT
    rng = random.Random(SEED)
    items = ci_items(rng) + comment_items(rng) + deploy_items(rng) + incident_items(rng)
    rng.shuffle(items)
    for i, it in enumerate(items, 1):
        it["qid"] = f"Q{i:03d}"
    names = [chr(ord("A") + i) for i in range(people)]
    shared = items[: round(len(items) * SHARED)]
    rest = items[len(shared):]
    load = {n: [] for n in names}
    for it in shared:
        for n in names:
            load[n].append(it)
    # Every other item to the two people with the fewest so far, so the shares come out even.
    for it in rest:
        for n in sorted(names, key=lambda n: (len(load[n]), rng.random()))[:2]:
            load[n].append(it)
    OUT.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    key = []
    for n in names:
        mine = sorted(load[n], key=lambda it: it["qid"])
        parts = [HEADER.format(person=f"person {n}", count=len(mine))]
        for k, it in enumerate(mine, 1):
            opts = "\n".join(f"  {chr(65 + j)}. {o.format(last=it.get('last'))}" for j, o in enumerate(OPTIONS[it["kind"]]))
            parts.append(f"\n\n--- {it['qid']} (question {k} of {len(mine)}) ---\n{QUESTION[it['kind']]}\n"
                         f"({CONTEXT[it['kind']]})\n\n{it['body']}\n\n{opts}\n\n"
                         f"Answer ({HOW.get(it['kind'], 'one letter')}): \nNote (optional): \n")
        (out / f"team-review-person-{n}.txt").write_text("".join(parts), encoding="utf-8")
        key += [{"person": n, "qid": it["qid"], "kind": it["kind"], "source": it["source"]} for it in mine]
    with open(OUT / "key.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["person", "qid", "kind", "source"])
        w.writeheader()
        w.writerows(key)
    return out


EXTRA_NOTE = """
These are extra questions, all about failed CI checks, that two AI labellers read differently. What happened when the
check was run again is left out on purpose: decide only from what the change touched and what the log shows.
"""


def extra(people: int, out: Path | None = None) -> Path:
    """The replay's disputed CI items (the two adjudications ruled differently), each to two people, as R-numbered
    questions in team-review-extra-person-X.txt; the key gains their rows."""
    out = out or OUT
    items = _jsonl("replay/items.jsonl")
    ids = json.loads((WORK / "replay" / "disputed.json").read_text(encoding="utf-8"))
    names = [chr(ord("A") + i) for i in range(people)]
    load = {n: [] for n in names}
    for k, n in enumerate(ids):
        for who in (names[k % people], names[(k + 1) % people]):
            load[who].append({"qid": f"R{k + 1:03d}", "kind": "ci", "source": f"replay:{n}",
                              "body": _ci_body(items[n - 1], rerun=False)})
    key = [r for r in _csv(OUT / "key.csv") if not r["qid"].startswith("R")]
    for n in names:
        mine = load[n]
        parts = [HEADER.format(person=f"person {n}", count=len(mine)).replace("questions for", "extra questions for", 1),
                 EXTRA_NOTE]
        for k, it in enumerate(mine, 1):
            opts = "\n".join(f"  {chr(65 + j)}. {o}" for j, o in enumerate(OPTIONS["ci"]))
            parts.append(f"\n\n--- {it['qid']} (question {k} of {len(mine)}) ---\n{QUESTION['ci']}\n({CONTEXT['ci']})\n\n"
                         f"{it['body']}\n\n{opts}\n\nAnswer (one letter): \nNote (optional): \n")
        (out / f"team-review-extra-person-{n}.txt").write_text("".join(parts), encoding="utf-8")
        key += [{"person": n, "qid": it["qid"], "kind": "ci", "source": it["source"]} for it in mine]
    with open(OUT / "key.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["person", "qid", "kind", "source"])
        w.writeheader()
        w.writerows(key)
    return out


ANSWER = re.compile(r"(?ms)^--- ([QR]\d{3}) .*?^Answer[^:\n]*:[ \t]*(.*?)$\s*^Note[^:\n]*:[ \t]*(.*?)(?=^--- [QR]\d{3} |\Z)")


def read(folder: Path) -> dict:
    key = {(r["person"], r["qid"]): r for r in _csv(OUT / "key.csv")}
    rows, problems = [], []
    for path in sorted(Path(folder).glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        person = re.search(r"Your id:\s*person\s+(\w+)", text)
        who = person.group(1) if person else path.stem.rsplit("-", 1)[-1]
        about = {k: (m.group(1).strip() if (m := re.search(rf"{k}[^:]*:[ \t]*(.*)$", text, re.M)) else "")
                 for k in ("Your role", "Years of experience")}
        for qid, answer, why in ANSWER.findall(text):
            letters = sorted(set(re.findall(r"\b([A-Ea-e])\b", answer.upper())))
            if not letters:
                problems.append(f"{path.name} {qid}: no answer")
                continue
            if len(letters) > 1 and key.get((who, qid), {}).get("kind") != "deploy":
                problems.append(f"{path.name} {qid}: more than one letter ({answer.strip()})")
            rows.append({"person": who, "qid": qid, "kind": key.get((who, qid), {}).get("kind", "?"),
                         "source": key.get((who, qid), {}).get("source", "?"), "answer": "".join(letters),
                         "why": " ".join(why.split())[:400], **{k.lower().replace(" ", "_"): v for k, v in about.items()}})
    if rows:
        with open(OUT / "answers.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    return {"answers": len(rows), "problems": problems}


# What each letter means in the published labels' terms.
AS_LABEL = {"ci": {"A": "yes", "B": "no", "C": "no", "D": "no", "E": "unclear"},
            "comment": {"A": "project_answer", "B": "peer_help", "C": "drive_by", "D": "other", "E": "unclear"},
            "deploy": {"A": "deployments", "B": "workflow", "C": "releases", "D": "every_merge", "E": "none"},
            "incident": {"A": "newest", "B": "older", "C": "none", "D": "none", "E": "unclear"}}


def _published() -> dict:
    """source -> the published label, in the same terms as AS_LABEL (deploy: a set of sources)."""
    out = {f"flaky:{r['id']}": r["caused_by_change"] for r in _csv(HERE / "flaky" / "items.csv")}
    for part, name in (("community-main", "labels-main.csv"), ("community-validation", "labels-validation.csv")):
        out |= {f"{part}:{r['id']}": r["kind"] for r in _csv(HERE / "community" / name)}
    for name in ("sources-labels.csv", "sources-more-labels.csv"):
        for r in _csv(HERE / "dora" / name):
            out[f"dora:{r['repo']}"] = frozenset("workflow" if s in ("deploy_workflow", "release_workflow") else s
                                                 for s in r["truth"].split()) or frozenset({"none"})
    for r in _csv(HERE / "dora" / "incidents-labels.csv"):
        c = r["culprit"]
        out[f"incidents:{r['id']}"] = c if c in ("none", "unclear") else ("newest" if c == r["last_before"] else "older")
    for r in _csv(HERE / "replay" / "replay-labels.csv"):
        out[f"replay:{r['id']}"] = (r["caused_adjudicated_claude"], r["caused_adjudicated_gemini"])
    return out


def _fleiss(tables: list[Counter]) -> float | None:
    """Fleiss' kappa over items with at least two answers (unequal counts per item allowed, as Fleiss 1971 extended)."""
    items = [t for t in tables if sum(t.values()) >= 2]
    if not items:
        return None
    cats = {c for t in items for c in t}
    p_items = [sum(v * (v - 1) for v in t.values()) / (sum(t.values()) * (sum(t.values()) - 1)) for t in items]
    total = sum(sum(t.values()) for t in items)
    p_cat = {c: sum(t[c] for t in items) / total for c in cats}
    pe = sum(v * v for v in p_cat.values())
    po = sum(p_items) / len(p_items)
    return round((po - pe) / (1 - pe), 3) if pe < 1 else None


def score(panel: str) -> dict:
    """The panel's answers against each other and against the published labels, per kind of question; counts only."""
    from collections import Counter
    rows = _csv(OUT / "answers.csv")
    truth = _published()
    by_item = {}
    for r in rows:
        kind, letters = r["kind"], r["answer"]
        label = (frozenset(AS_LABEL["deploy"][x] for x in letters) if kind == "deploy" else AS_LABEL[kind][letters[0]])
        by_item.setdefault((r["qid"], kind, r["source"]), []).append(label)
    out = {"panel": panel, "answers": len(rows), "people": len({r["person"] for r in rows}), "kinds": {}}
    for kind in ("ci", "comment", "deploy", "incident"):
        groups = {k: v for k, v in by_item.items() if k[1] == kind and not k[0].startswith("R")}
        agree = against = decided = 0
        for (_q, _k, src), labels in groups.items():
            top, n = Counter(labels).most_common(1)[0]
            if n * 2 <= len(labels) or src not in truth or top == "unclear" or truth[src] == "unclear":
                continue
            decided += 1
            agree += top == truth[src]
        lo, hi = wilson(agree, decided)
        out["kinds"][kind] = {"items": len(groups), "kappa_between_panel": _fleiss([Counter(v) for v in groups.values()]),
                              "majority_matches_label": {"k": agree, "n": decided, "low": round(lo, 3), "high": round(hi, 3)}}
        if kind == "deploy":
            # Exact sets are strict: also each of the five sources, named or not, by the panel's majority and the label.
            cells = [(s in Counter(v).most_common(1)[0][0]) == (s in truth[src]) for (_q, _k, src), v in groups.items()
                     if src in truth for s in AS_LABEL["deploy"].values()]
            out["kinds"][kind]["sources_agree"] = {"k": sum(cells), "n": len(cells)}
    # The replay's disputed items: which adjudication the panel's majority sides with.
    sides = Counter()
    for (q, _k, src), labels in by_item.items():
        if not q.startswith("R") or src not in truth:
            continue
        top, n = Counter(labels).most_common(1)[0]
        claude, gemini = truth[src]
        sides["no majority" if n * 2 <= len(labels) else "can't tell" if top == "unclear" else
              "with Claude's adjudication" if top == claude else "with Gemini's adjudication" if top == gemini else "neither"] += 1
    out["replay_disputed"] = dict(sides)
    (HERE / "audit-results.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    mk = sub.add_parser("make")
    mk.add_argument("--people", type=int, default=5)
    mk.add_argument("--out", type=Path, default=None, help="where the question files go (the key stays in .work/audit)")
    ex = sub.add_parser("extra")
    ex.add_argument("--people", type=int, default=5)
    ex.add_argument("--out", type=Path, default=None)
    sub.add_parser("read").add_argument("folder", type=Path)
    sc = sub.add_parser("score")
    sc.add_argument("--panel", required=True, help="who answered, as published (for example a five-agent model panel)")
    args = ap.parse_args(argv)
    if args.cmd == "make":
        print(make(args.people, args.out))
    elif args.cmd == "extra":
        print(extra(args.people, args.out))
    elif args.cmd == "score":
        print(json.dumps(score(args.panel), indent=1))
    else:
        print(json.dumps(read(args.folder), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
