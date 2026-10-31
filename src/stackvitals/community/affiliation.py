"""Which organisation the people behind the merged work say they work for, for the elephant factor (CHAOSS): the
company on their public profile, else unknown (counted and shown, never guessed). Membership of the org that owns the
repo isn't used: volunteer projects' orgs aren't employers. Looked up each run and kept only in memory, so no person's
employer is written to the data branch."""
import hashlib
import json
import re

from mergescout.github.graphql import GraphQLError, RateLimited

BATCH, MAX_PEOPLE = 25, 150
SUFFIX = re.compile(r"\b(inc|llc|ltd|limited|corp|corporation|gmbh|co|company|plc|sa|ag|bv|oy|ab|the)\b\.?")
NOT_A_COMPANY = {"freelance", "freelancer", "independent", "self", "self-employed", "selfemployed", "none", "n/a", "na",
                 "student", "retired", "personal", "home", "me", "myself", "open source", "opensource", "unemployed"}


def key(login: str) -> str:
    return hashlib.sha1((login or "").lower().encode()).hexdigest()[:12]


def normalize(company: str | None) -> str | None:
    """A company field as one organisation name: "@Google LLC" and "google, inc." are google; self-employment is none."""
    text = (company or "").strip().lower()
    if not text:
        return None
    text = text.split()[0] if text.startswith("@") else text  # "@acme @other": the first one
    text = re.split(r"[,/|;(]", text.lstrip("@"))[0]
    text = SUFFIX.sub("", text).strip(" .-_")
    text = re.sub(r"\s+", " ", text)
    return None if not text or text in NOT_A_COMPANY else text


def _query(logins: list[str]) -> str:
    parts = [f"u{i}: user(login: {json.dumps(x)}) {{ login company }}" for i, x in enumerate(logins)]
    return "query { rateLimit { cost remaining resetAt } " + " ".join(parts) + " }"


def collect(gql, logins: list[str]) -> dict[str, str | None]:
    """Each login's organisation (by hash), looked up fresh each run and never written down: a hash of a public login
    can be reversed, so a kept file would name each person's employer. At most 150 people (the busiest first)."""
    out = {}
    for i in range(0, min(len(logins), MAX_PEOPLE), BATCH):
        batch = logins[i:min(i + BATCH, MAX_PEOPLE)]
        try:
            # Partial: a renamed or deleted account answers null instead of failing the whole batch.
            data = gql.query(_query(batch), {}, partial=True).data or {}
        except (GraphQLError, RateLimited):
            break
        for j, login in enumerate(batch):
            out[key(login)] = normalize((data.get(f"u{j}") or {}).get("company"))
    return out
