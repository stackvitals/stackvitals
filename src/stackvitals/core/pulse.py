"""A weekly developer pulse in the digest issue (SPACE's satisfaction and DX Core 4's experience, the GitHub-native way):
three questions posted as comments that people answer with a reaction, counted the next week. StackVitals keeps and
shows only the counts; GitHub itself shows who reacted to anyone who can see the issue. On a public repo only the
team's own people (insiders) are counted."""

QUESTIONS = (("flow", "Could you get your work done this week without waiting on others?"),
             ("friction", "Did CI and reviews stay out of your way this week?"),
             ("satisfaction", "Are you happy with how the team shipped this week?"))
ANSWERS = {"+1": "yes", "-1": "no", "confused": "mixed"}
NAMES = {"flow": "Flow", "friction": "Low friction", "satisfaction": "Satisfaction"}


def _marker(week: str, key: str) -> str:
    return f"<!-- stackvitals:pulse {week} {key} -->"


def ask(api, issue: int, week: str) -> None:
    for key, question in QUESTIONS:
        api.send("POST", f"/repos/{api.repo}/issues/{issue}/comments",
                 {"body": f"**Pulse:** {question}\n\nReact 👍 yes, 👎 no, 😕 mixed. StackVitals reads only the counts (reactions themselves are visible on GitHub).\n{_marker(week, key)}"})


def tally(api, issue: int, week: str, since: str | None = None, keep=None) -> dict:
    """Reaction counts on that week's three questions (`keep(login)` picks whose count); a question not found counts
    nothing. Up to 300 reactions a question."""
    comments = api._get(f"/repos/{api.repo}/issues/{issue}/comments", {"per_page": 100, **({"since": since} if since else {})})
    out = {key: {"yes": 0, "no": 0, "mixed": 0} for key, _q in QUESTIONS}
    for c in comments or []:
        key = next((k for k, _q in QUESTIONS if _marker(week, k) in (c.get("body") or "")), None)
        if not key:
            continue
        for page in (1, 2, 3):
            got = api._get(f"/repos/{api.repo}/issues/comments/{c['id']}/reactions", {"per_page": 100, "page": page}) or []
            for r in got:
                if r.get("content") in ANSWERS and (keep is None or keep((r.get("user") or {}).get("login"))):
                    out[key][ANSWERS[r["content"]]] += 1
            if len(got) < 100:
                break
    return out


def section(counts: dict) -> str | None:
    """The digest's pulse lines, or None when nobody answered."""
    if not any(sum(v.values()) for v in counts.values()):
        return None
    parts = [f"{NAMES[k]} {v['yes']} yes, {v['no']} no" + (f", {v['mixed']} mixed" if v["mixed"] else "")
             for k, v in counts.items() if sum(v.values())]
    return "**Team pulse last week** (reactions, counts only): " + "; ".join(parts) + "."


KEEP_WEEKS = 52
MIN_ANSWERS = 5  # fewer answers to a question in a week and no share is shown: too few to read, too easy to trace
# The number each question sits beside in the app: waiting on others / CI and reviews in the way / how the team shipped.
BESIDE = {"flow": "pickup", "friction": "first_try", "satisfaction": "deployments"}


def record(root, week: str, counts: dict) -> None:
    """Keep one week's counts (and nothing about who answered) in docs/pulse.json, a year at most."""
    import json
    from pathlib import Path

    from stackvitals.core.store import published, write_if_changed
    path = Path(root) / "docs" / "pulse.json"
    try:
        weeks = json.loads(path.read_text(encoding="utf-8")).get("weeks") or []
    except (OSError, ValueError):
        weeks = []
    clean = {k: {a: int((counts.get(k) or {}).get(a) or 0) for a in ("yes", "no", "mixed")} for k, _q in QUESTIONS}
    weeks = [w for w in weeks if w.get("week") != week] + [{"week": week, **clean}]
    weeks = sorted(weeks, key=lambda w: w["week"])[-KEEP_WEEKS:]
    path.parent.mkdir(parents=True, exist_ok=True)
    write_if_changed(path, published({"weeks": weeks, "beside": BESIDE, "min_answers": MIN_ANSWERS}))


def trend(weeks: list[dict]) -> dict:
    """{question: [{"week", "answers", "yes_share"}]}; the share is None for a week with fewer than 5 answers."""
    out = {}
    for key, _q in QUESTIONS:
        rows = []
        for w in weeks:
            c = w.get(key) or {}
            n = sum(int(c.get(a) or 0) for a in ("yes", "no", "mixed"))
            rows.append({"week": w["week"], "answers": n, "yes_share": round(c.get("yes", 0) / n, 4) if n >= MIN_ANSWERS else None})
        out[key] = rows
    return out
