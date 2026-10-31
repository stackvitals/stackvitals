"""What a repo states about itself, read once a week and shown beside its numbers: a governance file, funding links, a
security policy, a code of conduct, Discussions, how many maintainers it lists, and any response time its contributing
guide promises (so a slow first answer is read against the project's own word). File text is read, never kept."""
import re

from mergescout.github.graphql import GraphQLError, RateLimited

PATHS = {"gov": ("GOVERNANCE.md", ".github/GOVERNANCE.md", "docs/GOVERNANCE.md"),
         "c": ("CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md"),
         "m": ("MAINTAINERS", "MAINTAINERS.md"), "o": (".github/CODEOWNERS", "CODEOWNERS")}
UNITS = {"hour": 1, "day": 24, "week": 168}
# "respond ... within 3 business days", "triage issues within 48 hours": a promise about people answering.
PROMISE = re.compile(r"(?i)\b(respond|reply|replies|response|triage|review|get back|acknowledge|answer)\w*\b[^.\n]{0,80}?"
                     r"\b((?:within|in)\s+(\d+)\s*(?:business\s+|working\s+)?(hour|day|week)s?)")


def stated_response(text: str | None) -> dict | None:
    m = PROMISE.search(text or "")
    if not m:
        return None
    return {"hours": int(m.group(3)) * UNITS[m.group(4).lower()], "said": " ".join(m.group(2).lower().split())}


def query() -> str:
    files = " ".join(f'{k}{i}: object(expression: "HEAD:{p}") {{ ... on Blob {{ byteSize text }} }}'
                     for k, paths in PATHS.items() for i, p in enumerate(paths, 1))
    return ("query($owner: String!, $name: String!) { rateLimit { cost remaining resetAt } repository(owner: $owner, name: $name) { isSecurityPolicyEnabled "
            "hasDiscussionsEnabled codeOfConduct { name } fundingLinks { platform url } " + files + " } }")


def _first(repo: dict, k: str) -> dict | None:
    return next((repo.get(f"{k}{i}") for i in range(1, len(PATHS[k]) + 1) if repo.get(f"{k}{i}")), None)


def context_record(repo: dict) -> dict:
    """The facts, from one GraphQL answer: what is stated, never the files' text."""
    contributing = (_first(repo, "c") or {}).get("text")
    listed = [x for x in ((_first(repo, "m") or {}).get("text") or "").splitlines() if x.strip() and not x.lstrip().startswith("#")]
    owners = {o for line in ((_first(repo, "o") or {}).get("text") or "").splitlines() if not line.lstrip().startswith("#")
              for o in line.split()[1:] if o.startswith("@")}
    return {"governance": bool(_first(repo, "gov")), "security_policy": bool(repo.get("isSecurityPolicyEnabled")),
            "code_of_conduct": (repo.get("codeOfConduct") or {}).get("name"),
            "funding": [f["platform"] for f in repo.get("fundingLinks") or [] if f and f.get("platform")],
            "discussions": bool(repo.get("hasDiscussionsEnabled")), "contributing": bool(contributing),
            "response_policy": stated_response(contributing),
            "maintainers_listed": len(listed) or None, "code_owners": len(owners) or None}


def read_context(gql, owner: str, name: str) -> dict | None:
    try:
        repo = (gql.query(query(), {"owner": owner, "name": name}).data or {}).get("repository")
    except (GraphQLError, RateLimited):
        return None
    return context_record(repo) if repo else None
