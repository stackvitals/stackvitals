"""Golden paths (opt-in): the portal repo's portal.toml names templates people can run from the app or a request, and
the Portal's org App carries them out: a new repo from a template repo, or a pull request that adds a folder of the
portal repo's files (a standard CI workflow, a CODEOWNERS, a catalog-info.yaml) to an existing repo. Only people with
write access to the portal repo can run one, each run is recorded as a decision, and nothing runs without the App."""
import base64
import re
import tomllib

from stackvitals.ci.api import APIError

NAME = re.compile(r"[A-Za-z0-9._-]{1,100}")
KINDS = ("repo", "files")


class GoldenError(Exception):
    """A golden path that can't run as asked; the message says why."""


def load_paths(text: str | None) -> dict[str, dict]:
    """Each [[golden_path]]: id, title, kind ("repo" with a template, or "files" with a folder of the portal repo)."""
    doc = tomllib.loads(text or "")
    out = {}
    for g in doc.get("golden_path") or []:
        if not isinstance(g, dict) or not NAME.fullmatch(str(g.get("id") or "")) or g.get("kind") not in KINDS:
            raise GoldenError("Each [[golden_path]] needs an id and a kind (repo or files).")
        if g["kind"] == "repo" and not re.fullmatch(r"[\w.-]+/[\w.-]+", str(g.get("template") or "")):
            raise GoldenError(f"Golden path {g['id']} needs template = \"owner/template-repo\".")
        if g["kind"] == "files" and not str(g.get("folder") or "").strip("/"):
            raise GoldenError(f"Golden path {g['id']} needs folder = \"golden/{g['id']}\" in the portal repo.")
        if g.get("approvals", 0) not in (0, 1):
            raise GoldenError(f"Golden path {g['id']}: approvals is 0 or 1 (someone other than the requester approves).")
        out[g["id"]] = {"id": g["id"], "title": str(g.get("title") or g["id"]), "kind": g["kind"],
                        "template": g.get("template"), "folder": str(g.get("folder") or "").strip("/"),
                        "private": bool(g.get("private", True)), "description": str(g.get("description") or ""),
                        "approvals": int(g.get("approvals", 0))}
    return out


def _new_repo(app, org: str, path: dict, inputs: dict) -> tuple[str, str]:
    name = str(inputs.get("name") or "")
    if not NAME.fullmatch(name) or name.startswith("."):
        raise GoldenError("The new repo's name may hold letters, digits, dots, dashes and underscores only.")
    made = app.send("POST", f"/repos/{path['template']}/generate",
                    {"owner": org, "name": name, "description": str(inputs.get("description") or "")[:300],
                     "private": path["private"]})
    url = made.get("html_url") or f"https://github.com/{org}/{name}"
    return f"Created {org}/{name} from {path['template']} ({'private' if path['private'] else 'public'}).", url


def _files_pr(app, portal_api, portal_repo: str, org: str, path: dict, inputs: dict, requester: str) -> tuple[str, str]:
    target = str(inputs.get("repo") or "")
    owner, _, name = target.partition("/")
    if owner.lower() != org.lower() or not NAME.fullmatch(name):
        raise GoldenError(f"Golden paths only change repos in {org}; say which one as repo = \"{org}/<name>\".")
    # Write access to the portal repo isn't write access to every repo: the requester must be able to push to the target.
    try:
        level = app._get(f"/repos/{target}/collaborators/{requester}/permission").get("permission")
    except APIError:
        level = None
    if level not in ("admin", "maintain", "write"):
        raise GoldenError(f"{requester} can't write to {target}, so this golden path won't open a pull request there.")
    prefix = path["folder"] + "/"
    tree = portal_api._get(f"/repos/{portal_repo}/git/trees/HEAD", {"recursive": "1"}).get("tree") or []
    files = [t["path"] for t in tree if t.get("type") == "blob" and t["path"].startswith(prefix)]
    if not files:
        raise GoldenError(f"The portal repo has no files under {prefix}.")
    base = app._get(f"/repos/{target}").get("default_branch") or "main"
    sha = app._get(f"/repos/{target}/git/ref/heads/{base}")["object"]["sha"]
    branch = f"stackvitals/golden-{path['id']}"
    try:
        app.send("POST", f"/repos/{target}/git/refs", {"ref": f"refs/heads/{branch}", "sha": sha})
    except APIError as exc:
        if "HTTP 422" not in str(exc):  # the branch is there from an earlier try: carry on with it
            raise
    for f in files:
        content, dest = portal_api.file(f, None, repo=portal_repo), f[len(prefix):]
        # A file that already exists (a CODEOWNERS being replaced) is updated, which needs its current sha.
        try:
            current = app._get(f"/repos/{target}/contents/{dest}", {"ref": branch}).get("sha")
        except APIError:
            current = None
        app.send("PUT", f"/repos/{target}/contents/{dest}",
                 {"message": f"Add {path['title']} (StackVitals golden path)", "branch": branch,
                  "content": base64.b64encode(content).decode(), **({"sha": current} if current else {})})
    pr = app.send("POST", f"/repos/{target}/pulls",
                  {"title": f"Add {path['title']}", "head": branch, "base": base,
                   "body": f"Golden path `{path['id']}` from {portal_repo}: {len(files)} file(s). Review and merge as usual."})
    return f"Opened a pull request in {target} adding {len(files)} file(s).", pr.get("html_url") or ""


def run(app, portal_api, portal_repo: str, org: str, path: dict, inputs: dict, requester: str) -> tuple[str, str]:
    """Carries out one golden path for `requester`; returns what happened and a link to it."""
    if path["kind"] == "repo":
        return _new_repo(app, org, path, inputs)
    return _files_pr(app, portal_api, portal_repo, org, path, inputs, requester)
