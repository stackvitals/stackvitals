"""The security probes, named as OpenSSF Scorecard names them where they overlap (so results can be compared), each
with its risk, what it costs to fix and how; one 0-10 score; SARIF for GitHub's Security tab; and the weekly step."""
import json
from datetime import datetime, timedelta
from pathlib import Path

from stackvitals.ci.api import APIError
from stackvitals.security import repo_checks, workflows

RISK = {"critical": 10, "high": 7.5, "medium": 5, "low": 2.5}
PROBES = {
    "hasDangerousWorkflowUntrustedCheckout": ("critical", "S", "A pull_request_target or workflow_run workflow checks out the pull request's code with secrets in reach.",
                                              "Use pull_request for untrusted code, or check it out only after a maintainer's label or approval gate."),
    "hasDangerousWorkflowScriptInjection": ("critical", "S", "Text an outsider writes (a title, a body, a branch name) is pasted into a run: script.",
                                            "Pass it through env: (FOO: ${{ github.event.issue.title }}) and use \"$FOO\" in the script."),
    "topLevelPermissions": ("high", "S", "A workflow's token gets write access it may not need.",
                            "Add `permissions: contents: read` at the top and grant writes only on the jobs that need them."),
    "pinsDependencies": ("medium", "M", "An action used by tag, or a script piped from the internet, can change under you (as tj-actions/changed-files did).",
                         "Pin each action to its full commit (uses: owner/action@<40-character sha> # v4) and download scripts before running them."),
    "branchProtectionLevel": ("high", "S", "The default branch can be force-pushed or merged into without review or checks.",
                              "Add a ruleset on the default branch: block force pushes and deletion, require a review and the CI checks."),
    "securityPolicyPresent": ("medium", "S", "No SECURITY.md tells people how to report a vulnerability privately.",
                              "Add SECURITY.md with a contact and a disclosure timeline, and turn on private vulnerability reporting."),
    "releasesAreSigned": ("high", "M", "Recent releases carry no signature or provenance file to check them against.",
                          "Sign release assets with Sigstore (actions/attest-build-provenance) or publish .intoto.jsonl provenance."),
    "hasSBOM": ("medium", "S", "No SBOM in the repo or the release assets.", "Attach an SPDX or CycloneDX SBOM to each release (anchore/sbom-action)."),
    "sastToolConfigured": ("medium", "S", "No code scanning (CodeQL, Semgrep, SonarCloud) runs on pull requests.",
                           "Turn on CodeQL's default setup in the repo's Security settings, or add a Semgrep workflow."),
    "hasBinaryArtifacts": ("high", "S", "Compiled files are committed, so nobody can review what they do.", "Build them in CI instead and remove them from the repo."),
    "fuzzed": ("medium", "M", "No fuzzing setup was found.", "Add ClusterFuzzLite, Go native fuzz tests, or join OSS-Fuzz."),
    "hasOpenSSFBadge": ("low", "M", "No OpenSSF Best Practices badge.", "Fill in the questionnaire at bestpractices.dev."),
    "packagedWithAutomatedWorkflow": ("medium", "S", "Releases aren't published by a workflow, so their build can't be traced.",
                                      "Publish from a workflow (with trusted publishing on PyPI and npm)."),
}


def verdicts(found: list[dict], f: dict) -> list[dict]:
    """Every probe's result: "fail" with its findings, "pass", or "unknown" (the token couldn't read it)."""
    by = {}
    for x in found:
        if not x.get("guarded"):
            by.setdefault(x["probe"], []).append(x)
    guarded = [x for x in found if x.get("guarded")]
    tiers = f.get("branch") or {}
    state = {
        "branchProtectionLevel": "unknown" if not tiers.get("readable") else ("pass" if tiers.get("level", 0) >= 2 else "fail"),
        "securityPolicyPresent": "pass" if (f.get("policy") or {}).get("file") else "fail",
        "releasesAreSigned": "unknown" if not (f.get("releases") or {}).get("releases") else ("pass" if f["releases"]["signed"] else "fail"),
        "hasSBOM": "pass" if (f.get("tree") or {}).get("sbom_files") or (f.get("releases") or {}).get("sbom") else "fail",
        "sastToolConfigured": "pass" if (f.get("workflows") or {}).get("sast") else "fail",
        "hasBinaryArtifacts": "fail" if (f.get("tree") or {}).get("binaries") else "pass",
        "fuzzed": "pass" if (f.get("tree") or {}).get("fuzzing") or f.get("oss_fuzz") else "fail",
        "hasOpenSSFBadge": "pass" if f.get("badge") else "fail",
        "packagedWithAutomatedWorkflow": "unknown" if not (f.get("releases") or {}).get("releases") else
        ("pass" if (f.get("workflows") or {}).get("publish") else "fail"),
    }
    out = []
    for probe, (risk, effort, why, fix) in PROBES.items():
        result = ("fail" if by.get(probe) else "pass") if probe not in state else state[probe]
        out.append({"probe": probe, "risk": risk, "effort": effort, "result": result, "why": why, "fix": fix,
                    "findings": by.get(probe, [])[:20],
                    "guarded": [x for x in guarded if x["probe"] == probe][:10]})
    return out


def score(results: list[dict]) -> float | None:
    """0-10: the risk-weighted share of probes passed, among those that could be read."""
    known = [r for r in results if r["result"] != "unknown"]
    total = sum(RISK[r["risk"]] for r in known)
    return round(10 * sum(RISK[r["risk"]] for r in known if r["result"] == "pass") / total, 1) if total else None


def sarif(results: list[dict]) -> dict:
    """The failing workflow findings as SARIF 2.1.0, for github/codeql-action/upload-sarif."""
    rules = [{"id": r["probe"], "shortDescription": {"text": r["why"]}, "help": {"text": r["fix"]},
              "properties": {"security-severity": str(RISK[r["risk"]])}} for r in results if r["findings"]]
    def text(x: dict) -> str:
        return f"{x['detail']} (job {x['job']})" if x.get("job") else x["detail"]
    hits = [{"ruleId": r["probe"], "level": "error" if r["risk"] in ("critical", "high") else "warning",
             "message": {"text": text(x)},
             "locations": [{"physicalLocation": {"artifactLocation": {"uri": x["path"]}}}]}
            for r in results for x in r["findings"] if x.get("path")]
    return {"version": "2.1.0", "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "runs": [{"tool": {"driver": {"name": "StackVitals", "rules": rules}}, "results": hits}]}


def collect(api, repo: str, branch: str, get_json=None) -> tuple[list[dict], dict]:
    """(findings, facts) read through the API: workflow files, the tree, protection, policy, releases, fuzzing, badge."""
    owner, name = repo.split("/", 1)
    files = {}
    listing = repo_checks._try(api, f"/repos/{repo}/contents/.github/workflows") or []
    for item in listing if isinstance(listing, list) else []:
        if str(item.get("name", "")).endswith((".yml", ".yaml")):
            try:
                files[item["path"]] = api.file(item["path"], branch).decode("utf-8", "replace")
            except APIError:
                pass
    found = [x for path, text in files.items() for x in workflows.check(path, text)]
    tree = repo_checks._try(api, f"/repos/{repo}/git/trees/{branch}", {"recursive": "1"}) or {}
    paths = [t["path"] for t in tree.get("tree") or [] if t.get("type") == "blob"]
    # Compiled files with no telling name: executable-mode files without an extension, read to check their header.
    sniffed = []
    for e in repo_checks.sniff_candidates(tree.get("tree") or []):
        try:
            import base64
            blob = api._get(f"/repos/{repo}/git/blobs/{e['sha']}")
            if repo_checks.is_executable(base64.b64decode((blob or {}).get("content") or "")[:8]):
                sniffed.append(e["path"])
        except (APIError, ValueError):
            pass
    # Dockerfiles' base images, pinned by digest or not (a few files; vendored and test ones left out).
    for path in [p for p in paths if p.rsplit("/", 1)[-1].startswith("Dockerfile")
                 and not any(s in p for s in ("test", "example", "vendor"))][:5]:
        try:
            found += workflows.dockerfile(path, api.file(path, branch).decode("utf-8", "replace"))
        except APIError:
            pass
    rules = repo_checks._try(api, f"/repos/{repo}/rules/branches/{branch}")
    facts = {"workflows": {**workflows.facts(files), "files": len(files)},
             "tree": {**(tf := repo_checks.tree_facts(paths)), "binaries": sorted(set(tf["binaries"]) | set(sniffed))[:50]},
             "branch": repo_checks.branch_tiers(repo_checks._try(api, f"/repos/{repo}/branches/{branch}/protection"),
                                                rules if isinstance(rules, list) else None,
                                                repo_checks._try(api, f"/repos/{repo}/branches/{branch}")),
             "policy": repo_checks.policy(api, repo, owner),
             "releases": repo_checks.releases(repo_checks._try(api, f"/repos/{repo}/releases", {"per_page": 10}) or []),
             "oss_fuzz": bool(repo_checks._try(api, f"/repos/google/oss-fuzz/contents/projects/{name.lower()}")),
             "badge": repo_checks.badge(get_json, f"https://github.com/{repo}") if get_json else None}
    return found, facts


def security_step(ws, env: dict, now: datetime, make_api=None, get_json=None) -> dict:
    """Weekly: run the probes, write docs/security.json and docs/security.sarif, and keep each week's score."""
    from stackvitals.ci.api import ActionsAPI
    path = Path(ws.path) / "docs" / "security.json"
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    if old.get("generated", "")[:10] > (now - timedelta(days=7)).date().isoformat():
        return {"skipped": "read this week"}
    api = (make_api or ActionsAPI)(env.get("GITHUB_TOKEN"), ws.repo)
    info = ws.cache.get("repo_info") or {}
    found, facts = collect(api, ws.repo, info.get("default_branch") or "main", get_json)
    results = verdicts(found, facts)
    level, before = facts["branch"].get("level"), (old.get("facts") or {}).get("branch", {}).get("level")
    history = (old.get("history") or [])[-51:] + [[now.date().isoformat(), score(results)]]
    out = {"schema": 1, "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "score": score(results), "probes": results,
           "facts": facts, "history": history,
           # Protection that got weaker since last week is said out loud; nobody else tracks the change.
           "weakened": before is not None and level is not None and level < before}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    (path.parent / "security.sarif").write_text(json.dumps(sarif(results), indent=1), encoding="utf-8")
    return {"score": out["score"], "failing": sum(r["result"] == "fail" for r in results)}
