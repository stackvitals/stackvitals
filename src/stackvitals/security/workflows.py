"""Workflow checks (Scorecard's Dangerous-Workflow, Token-Permissions, Pinned-Dependencies, SAST and Packaging), read
from the workflow files themselves. Unlike Scorecard, a checkout of fork code behind a guard (a label, an actor or an
author-association test) is reported as guarded, not as a hole."""
import re

import yaml

# Text an outsider controls; inside a run: script it can run commands (script injection).
UNTRUSTED = re.compile(r"\$\{\{\s*(github\.event\.(issue\.(title|body)|pull_request\.(title|body|head\.ref|head\.label)"
                       r"|comment\.body|review\.body|review_comment\.body|discussion\.(title|body)|head_commit\.(message|author\.(name|email))"
                       r"|commits\[[^\]]*\]\.(message|author\.(name|email))|pages\[[^\]]*\]\.page_name|workflow_run\.(head_branch|display_title|head_commit\.message))"
                       r"|github\.head_ref)\s*\}\}")
FORK_REF = re.compile(r"github\.event\.pull_request\.head\.(sha|ref)|github\.head_ref|github\.event\.workflow_run\.head_(sha|branch)"
                      r"|refs/pull/")
GUARD = re.compile(r"labels|label\.name|github\.actor|author_association|github\.event\.pull_request\.head\.repo\.full_name\s*==|"
                   r"github\.repository_owner|environment")
PIN = re.compile(r"^[0-9a-f]{40}$")
CURL_PIPE = re.compile(r"(curl|wget)\b[^|\n]*\|\s*(sudo\s+)?(ba|z|da)?sh\b")
# Installs that take whatever version is newest (Scorecard's Pinned-Dependencies counts these too): pip without a
# requirements file, a pinned version or hashes, and global npm installs without a version.
PIP_LOOSE = re.compile(r"\bpip3?\s+install\s+(?!.*(-r\s|--requirement|--require-hashes|-e\s|\s\.(\s|$)|==))[^\n]*")
NPM_GLOBAL = re.compile(r"\bnpm\s+(install|i)\s+(-g|--global)\s+(?![^\s@]+@\d)[^\n]*")
FROM_LINE = re.compile(r"(?mi)^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)")
SAST = ("github/codeql-action", "semgrep", "sonarsource/sonarcloud", "snyk/actions", "returntocorp/semgrep")
PUBLISH = re.compile(r"npm publish|pypa/gh-action-pypi-publish|twine upload|goreleaser|docker/build-push-action|cargo publish"
                     r"|gem push|dotnet nuget push|gradle.*publish|mvn.*deploy|uv publish|poetry publish")


def _load(text: str) -> dict | None:
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    return doc if isinstance(doc, dict) else None


def _events(doc: dict) -> set[str]:
    on = doc.get("on", doc.get(True))  # YAML 1.1 reads a bare `on` as true
    if isinstance(on, str):
        return {on}
    return set(on) if isinstance(on, (list, dict)) else set()


def _steps(job: dict) -> list[dict]:
    return [s for s in job.get("steps") or [] if isinstance(s, dict)]


def check(path: str, text: str) -> list[dict]:
    """Findings in one workflow file: {"probe", "path", "job", "line" text, "detail", "guarded"}."""
    doc = _load(text)
    if doc is None:
        return []
    out = []
    events = _events(doc)
    privileged = events & {"pull_request_target", "workflow_run"}
    for name, job in (doc.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        guard = str(job.get("if") or "")
        for step in _steps(job):
            uses, run, with_ = str(step.get("uses") or ""), str(step.get("run") or ""), step.get("with") or {}
            if privileged and uses.startswith("actions/checkout") and FORK_REF.search(str(with_.get("ref") or "")):
                why = GUARD.search(guard + " " + str(step.get("if") or ""))
                out.append({"probe": "hasDangerousWorkflowUntrustedCheckout", "path": path, "job": name,
                            "detail": f"{'/'.join(sorted(privileged))} checks out the pull request's code",
                            "guarded": f"only when `{(guard or step.get('if'))}`" if why else None})
            for m in UNTRUSTED.finditer(run):
                out.append({"probe": "hasDangerousWorkflowScriptInjection", "path": path, "job": name, "detail": m.group(0),
                            "guarded": None})
            if uses and not uses.startswith(("./", "docker://")) and "@" in uses and not PIN.match(uses.rsplit("@", 1)[1]):
                out.append({"probe": "pinsDependencies", "path": path, "job": name, "detail": uses, "guarded": None})
            for rx in (CURL_PIPE, PIP_LOOSE, NPM_GLOBAL):
                if (m := rx.search(run)):
                    out.append({"probe": "pinsDependencies", "path": path, "job": name, "detail": m.group(0).strip()[:120],
                                "guarded": None})
    top = doc.get("permissions")
    if top is None or top == "write-all" or (isinstance(top, dict) and any(v == "write" for v in top.values())):
        jobs_ok = all(isinstance(j, dict) and j.get("permissions") is not None for j in (doc.get("jobs") or {}).values())
        if not (top is None and jobs_ok):
            out.append({"probe": "topLevelPermissions", "path": path, "job": None,
                        "detail": "no top-level permissions (the token gets the repo's default)" if top is None
                        else f"top-level permissions: {top}", "guarded": None})
    return out


def dockerfile(path: str, text: str) -> list[dict]:
    """Base images used by tag rather than digest (FROM image:tag, not image@sha256:...); scratch and earlier build
    stages left out."""
    stages, out = set(), []
    for line in (text or "").splitlines():
        m = FROM_LINE.match(line)
        if not m:
            continue
        image = m.group(1)
        alias = line.split()[-1].lower() if " as " in line.lower() else None
        if image.lower() != "scratch" and image.lower() not in stages and "@sha256:" not in image:
            out.append({"probe": "pinsDependencies", "path": path, "job": None, "detail": f"FROM {image}", "guarded": None})
        if alias:
            stages.add(alias)
    return out


def uses_any(text: str, names) -> bool:
    low = (text or "").lower()
    return any(n in low for n in names)


def facts(files: dict[str, str]) -> dict:
    """What the workflows say about SAST and publishing: {"sast": [paths], "publish": [paths]}."""
    return {"sast": sorted(p for p, t in files.items() if uses_any(t, SAST)),
            "publish": sorted(p for p, t in files.items() if PUBLISH.search(t or ""))}
