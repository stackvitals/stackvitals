"""Backstage entities for the repos that don't describe themselves: one file of Components (portal/entities.yaml on the
data branch) Backstage can register as a single location, each with its owner from CODEOWNERS, the StackVitals level as
an annotation and a link back to the portal. Repos with their own catalog-info.yaml are left to it."""
import re

import yaml

LIFECYCLE = "production"


def _name(repo: str) -> str:
    # Backstage names: letters, digits and [-_.], at most 63 characters, starting and ending alphanumeric.
    name = re.sub(r"[^A-Za-z0-9._-]", "-", repo.split("/")[-1])[:63].strip("-_.")
    return name or "repo"


def _owner(owners: dict | None) -> str:
    first = next(iter((owners or {}).get("owners") or []), "")
    if first.startswith("@") and "/" in first:
        return "group:" + first.split("/", 1)[1]
    if first.startswith("@"):
        return "user:" + first[1:]
    return "unknown"


def entity(repo: dict, portal_url: str | None) -> dict:
    level = (repo.get("score") or {}).get("level")
    tags = sorted({t.lower() for t in (repo.get("topics") or [])} | ({repo["language"].lower()} if repo.get("language") else set()))
    tags = [re.sub(r"[^a-z0-9+#-]", "-", t)[:63] for t in tags]
    meta = {"name": _name(repo["name"]), "description": repo.get("description") or "",
            "annotations": {"github.com/project-slug": repo["name"], "stackvitals.dev/level": level or "below bronze",
                            "stackvitals.dev/owners": (repo.get("owners") or {}).get("status") or "unknown"},
            "tags": tags}
    if portal_url:
        meta["links"] = [{"url": f"{portal_url.rstrip('/')}/#/portal?tab=repos", "title": "StackVitals portal"}]
    return {"apiVersion": "backstage.io/v1alpha1", "kind": "Component", "metadata": meta,
            "spec": {"type": "service", "lifecycle": LIFECYCLE, "owner": _owner(repo.get("owners"))}}


def entities_yaml(repos: list[dict], portal_url: str | None) -> str:
    live = [r for r in repos if not r.get("archived") and not r.get("fork") and not (r.get("descriptor") or {}).get("present")
            and r["name"].split("/")[-1].lower() != ".github"]
    return yaml.safe_dump_all([entity(r, portal_url) for r in live], sort_keys=False, allow_unicode=True)
