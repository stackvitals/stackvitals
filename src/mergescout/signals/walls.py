import re

import duckdb
import pyarrow as pa

AI = r"\b(ai|llm|chatgpt|copilot)\b"
WALLS = {
    "cla": r"contributor license agreement|\bcla\b|cla-assistant",
    "dco": r"developer certificate of origin|signed-off-by|\bdco\b",
    "issue_first": r"(open|file|create) an issue (first|before)"
                   r"|discuss(ed)? .{0,40}(first|before (opening|sending|submitting))",
    "ai_ban": rf"(do not|don't|will not|won't|cannot|can't|not) (accept|allow|merge|review|take)[^.]{{0,40}}{AI}"
              rf"|{AI}[- ](generated|written|assisted)[^.]{{0,60}}"
              r"(not (be )?(accepted|allowed|merged|permitted|welcome)|prohibited|forbidden|banned|will be (closed|rejected))"
              rf"|\b(prohibit(s|ed)?|bans?|banned|forbid(s|den)?)\b[^.]{{0,30}}{AI}",
    # "...contributions that use other licenses" is a licence rule, not a ban on outside PRs.
    "no_outside_prs": r"(not|no longer) accept(ing)? (external |outside |unsolicited )?(pull requests|contributions|prs)"
                      r"(?! (that|which|who|with|without|unless|under|using|licensed|from (?:bots|ai)))",
}
# AI rules and bans come from CONTRIBUTING only: a README describes the product, which may itself be about AI.
CONTRIBUTING_ONLY = {"ai_ban"}
AI_RULES = (r"\b(ai|llm)[- ](generated|assisted|assistance|guidelines|policy|usage|tools?|agents?|powered)\b"
            r"|use of (ai|llm|generative)|generative ai|coding with ai")
# The Apache license header ("under one or more contributor license agreements") is not a CLA to sign.
LICENSE_HEADER = r"one or more\W+contributor license agreements?"
BLOCKING = set(WALLS) | {"issues_disabled"}
# "A lighter alternative, should the CLA prove heavy: the DCO" names a rule the repo does not have.
# Only words before the match count: "this is not optional" and "instead of sending a PR" follow real rules.
HYPOTHETICAL = r"\b(alternative|optionally|if you prefer|should (the|it|this|we) \S+ prove|we (might|may) (switch|adopt|move))\b"
# A list item, heading or blank line starts a new sentence even without a full stop.
BLOCK_BREAK = r"\n\s*\n|\n\s*(?=[-*+#>|]|\d+[.)]\s)"


def _clean(text: str | None) -> str:
    # One line of single spaces, so phrases broken across lines still match.
    text = re.sub(BLOCK_BREAK, ". ", text or "")
    return re.sub(LICENSE_HEADER, " ", " ".join(text.split()), flags=re.I)


def _snippet(text: str, m: re.Match) -> str:
    start = max(0, m.start() - 60)
    return text[start:start + 160].strip()


def _sentence_before(text: str, m: re.Match) -> str:
    starts = [b.end() for b in re.finditer(r"[.!?]\s", text[:m.start()])]
    return text[starts[-1] if starts else 0:m.start()]


def _first(wall: str, pattern: str, text: str) -> re.Match | None:
    for m in re.finditer(pattern, text, re.I):
        if re.search(HYPOTHETICAL, _sentence_before(text, m), re.I):
            continue
        # "For major changes, please open an issue first" (a common README template) does not stop small fixes.
        if wall == "issue_first" and re.search(r"major change", text[max(0, m.start() - 40):m.start()], re.I):
            continue
        return m
    return None


def find_walls(meta: dict) -> list[tuple[str, str]]:
    found = []
    if meta.get("has_issues") is False:
        found.append(("issues_disabled", "issues are turned off for this repo"))
    contributing = _clean(meta.get("contributing_excerpt"))
    text = f"{contributing} {_clean(meta.get('readme_excerpt'))}"
    for wall, pattern in WALLS.items():
        source = contributing if wall in CONTRIBUTING_ONLY else text
        m = _first(wall, pattern, source)
        if m:
            found.append((wall, _snippet(source, m)))
    if "ai_ban" not in {w for w, _ in found}:
        m = re.search(AI_RULES, contributing, re.I)
        if m:
            found.append(("ai_policy", _snippet(contributing, m)))
        elif meta.get("ai_policy_sha"):
            found.append(("ai_policy", "AI_POLICY.md in the repo root"))
    return found


def build_walls(con: duckdb.DuckDBPyConnection) -> None:
    rows = []
    for repo_id, has_issues, ai_sha, contributing, readme in con.execute(
            "SELECT repo_id, has_issues, ai_policy_sha, contributing_excerpt, readme_excerpt FROM repo_meta").fetchall():
        for wall, evidence in find_walls({"has_issues": has_issues, "ai_policy_sha": ai_sha,
                                          "contributing_excerpt": contributing, "readme_excerpt": readme}):
            rows.append({"repo_id": repo_id, "wall": wall, "blocking": wall in BLOCKING, "evidence": evidence})
    schema = pa.schema([("repo_id", pa.int64()), ("wall", pa.string()), ("blocking", pa.bool_()),
                        ("evidence", pa.string())])
    con.register("walls_rows", pa.Table.from_pylist(rows, schema=schema))
    con.execute("CREATE OR REPLACE TABLE repo_walls AS SELECT * FROM walls_rows")
