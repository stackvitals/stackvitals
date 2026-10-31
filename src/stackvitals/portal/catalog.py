"""The org catalog: every repo with its settings, owners with evidence and the suite's module results. Repos checked longest
ago go first, so a run that hits its request budget (the built-in token allows 1,000 an hour) keeps earlier results for the
rest and the next run continues."""
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from stackvitals.ci.api import OutOfBudget
from stackvitals.portal import descriptor
from stackvitals.portal.batch import prefetch
from stackvitals.portal.inventory import (branch_protected, branch_rules, custom_properties, descriptor_for, file_facts, list_repos,
                                          module_facts, push_ci, repo_files, review_stats, scorecard_checks)
from stackvitals.portal.owners import owner_status


WORKERS = 6
PER_REPO = 15  # REST requests one repo can take, for deciding when to slow down


def cacheable(path: str) -> bool:
    """Small answers that rarely change, read conditionally: an unchanged one costs nothing from the hourly limit."""
    return any(part in path for part in ("/rules/branches/", "/codeowners/errors", "/teams/", "/protection",
                                         "/properties/values", "/branches/stackvitals-data"))


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _owner_checks(d: dict, owners: dict) -> dict:
    # Each owned entity says whether CODEOWNERS agrees, for the Catalog tab (no rule needed).
    if d.get("present") and owners.get("status") != "none":
        for e in d["entities"]:
            if e["kind"] in descriptor.NEEDS:
                e["owner_check"] = list(descriptor.owner_check(e.get("owner"), owners.get("owners") or []))
    return d


def build_catalog(api, org: str, mode: str, now: datetime, previous: dict | None = None, scorecard_client=None,
                  gql=None, file_rules: list[dict] | None = None) -> dict:
    stamp = _iso(now)
    old = {r["name"]: r for r in (previous or {}).get("repos") or [] if isinstance(r, dict) and r.get("name")}
    repos = list_repos(api, org, mode)
    props = custom_properties(api, org)
    cache, out = {}, {}
    order = sorted(repos, key=lambda r: (old.get(r["name"]) or {}).get("checked") or "")
    # Ten repos' files in one GraphQL query; a repo it couldn't read is asked over REST as before.
    paths = list(dict.fromkeys(x["path"] for x in file_rules or []))
    pre = prefetch(gql, [r for r in order if not (r["archived"] or r["fork"])], paths) if gql is not None else {}
    stop = threading.Event()

    def check(r: dict) -> tuple[str, dict]:
        kept = {**old[r["name"]], **r} if r["name"] in old else {**r, "checked": None}
        # Archived repos and forks are listed, not judged: a fork carries its upstream's CODEOWNERS (astral-sh/peps: 783 errors).
        # The org's .github repo holds shared settings, not a product.
        if r["archived"] or r["fork"] or r["name"].split("/")[-1].lower() == ".github":
            return r["name"], r
        if stop.is_set():
            return r["name"], kept
        try:
            # OpenSSF publishes Scorecard results for public repos only; private repos stay "not available" for those rules.
            openssf = scorecard_checks(scorecard_client, r["name"], (old.get(r["name"]) or {}).get("openssf"), now) \
                if scorecard_client is not None and not r["private"] else None
            mine = pre.get(r["name"])
            modules = module_facts(api, r["name"], mine)
            reviews = review_stats(gql, r["name"], now) if gql is not None and not (modules or {}).get("flow") else None
            rules = branch_rules(api, r["name"], r["default_branch"])
            owners = owner_status(api, org, r, now, cache, members_visible=mode == "private",
                                  reviewers=(reviews or {}).get("reviewers"), pre=mine)
            return r["name"], {**r, "properties": props.get(r["name"]) or {}, "rules": rules,
                               "protected": branch_protected(api, r["name"], r["default_branch"])
                               if isinstance(rules, list) and "pull_request" not in rules else None,
                               "owners": owners, "descriptor": _owner_checks(descriptor_for(api, r, mine), owners),
                               "files": file_facts(api, r, file_rules or [], mine),
                               "modules": modules, "docs": repo_files(api, r, mine),
                               # The docs/ folder's pages, for the catalog's docs index.
                               "doc_pages": (mine or {}).get("docs"),
                               # How it runs (kubernetes, container, terraform, serverless), from its root folder.
                               "runtime": (mine or {}).get("runtime"),
                               # Where CI Health doesn't run, Portal measures push CI itself (one request).
                               "ci": None if (modules or {}).get("ci_first_try")
                               else push_ci(api, r["name"], now, previous=(old.get(r["name"]) or {}).get("ci")),
                               # Likewise first reviews where Team Flow doesn't run (one GraphQL point, a separate budget).
                               "reviews": reviews,
                               "openssf": openssf, "scorecard": (openssf or {}).get("checks"), "checked": stamp}
        except OutOfBudget:
            stop.set()
            return r["name"], kept
        except Exception as exc:  # one repo's surprise keeps its earlier check and never stops the org's catalog
            return r["name"], {**kept, "error": type(exc).__name__}
    # Six repos at a time while the budget is ample (most of a repo's time is waiting on GitHub); one at a time near its
    # end, so the repos checked longest ago still go first.
    budget = getattr(api, "max_requests", None)
    i = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        while i < len(order):
            left = None if budget is None else budget - (api.requests - getattr(api, "unchanged", 0))
            chunk = order[i:i + (1 if left is not None and left < WORKERS * PER_REPO else WORKERS)]
            for name, record in pool.map(check, chunk):
                out[name] = record
            i += len(chunk)
    complete = not stop.is_set()
    return {"org": org, "mode": mode, "built_at": stamp, "complete": complete, "requests": getattr(api, "requests", None),
            "repos": sorted(out.values(), key=lambda r: r["name"].lower())}
