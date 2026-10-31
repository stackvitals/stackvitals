"""The light core: one GraphQL query reads ten repos' files at once (CODEOWNERS, catalog-info.yaml, the rule files, the
root and docs/ listings, the community files GitHub resolves, the suite's facts on the data branch), instead of a REST
request per file per repo. The readers in inventory.py and owners.py take what this found and ask REST only for the rest."""
import json

from mergescout.github.graphql import GraphQLError, RateLimited

BATCH = 10
# How a repo runs, from its root folder's names alone (no extra request).
RUNTIMES = (("kubernetes", ("k8s", "kubernetes", "charts", "helm", "chart.yaml", "kustomization.yaml", "skaffold.yaml")),
            ("container", ("dockerfile", "containerfile", "compose.yaml", "docker-compose.yml", "docker-compose.yaml")),
            ("terraform", ("terraform", "main.tf", "infra")), ("serverless", ("serverless.yml", "serverless.yaml", "template.yaml")))
CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
DATA = "stackvitals-data"


def _blob(alias: str, expression: str) -> str:
    return f"{alias}: object(expression: {json.dumps(expression)}) {{ ... on Blob {{ text byteSize }} }}"


def _repo_fields(paths: list[str]) -> str:
    files = [_blob(f"co{i}", f"HEAD:{p}") for i, p in enumerate(CODEOWNERS_PATHS)]
    files += [_blob(f"f{i}", f"HEAD:{p}") for i, p in enumerate(paths)]
    files.append(_blob("desc", "HEAD:catalog-info.yaml"))
    files.append(_blob("app", f"{DATA}:docs/app.json"))
    trees = " ".join(f'{a}: object(expression: "HEAD:{p}") {{ ... on Tree {{ entries {{ name type }} }} }}'
                     for a, p in (("root", ""), ("gh", ".github"), ("docs", "docs")))
    return (" ".join(files) + " " + trees + f' data: ref(qualifiedName: "refs/heads/{DATA}") {{ name }} '
            "licenseInfo { spdxId } codeOfConduct { url } contributingGuidelines { url }")


def query(names: list[str], paths: list[str]) -> str:
    fields = _repo_fields(paths)
    parts = [f"r{i}: repository(owner: {json.dumps(n.split('/')[0])}, name: {json.dumps(n.split('/')[1])}) {{ {fields} }}"
             for i, n in enumerate(names)]
    return "query { rateLimit { cost remaining resetAt } " + " ".join(parts) + " }"


def _text(node) -> str | None:
    return (node or {}).get("text") if isinstance(node, dict) else None


def _names(node) -> list[str]:
    return [e["name"] for e in (node or {}).get("entries") or [] if isinstance(e, dict) and e.get("name")]


def facts(node: dict, owner: str, paths: list[str]) -> dict:
    """What one repo's answer says, in the shape the readers use."""
    codeowners = next(((p, _text(node.get(f"co{i}"))) for i, p in enumerate(CODEOWNERS_PATHS) if _text(node.get(f"co{i}")) is not None),
                      (None, None))
    root, gh, docs = _names(node.get("root")), _names(node.get("gh")), _names(node.get("docs"))
    starts = lambda names, word: any(n.lower().startswith(word) for n in names)  # noqa: E731
    org_default = lambda field: f"/{owner.lower()}/.github/" in (((node.get(field) or {}).get("url")) or "").lower()  # noqa: E731
    files = {"readme": starts(root, "readme") or starts(gh, "readme") or starts(docs, "readme"),
             "license": bool((node.get("licenseInfo") or {}).get("spdxId")) or starts(root, "license") or starts(root, "copying"),
             "contributing": bool(node.get("contributingGuidelines")),
             "code_of_conduct": bool(node.get("codeOfConduct"))}
    files["org_defaults"] = [k for k, field in (("contributing", "contributingGuidelines"), ("code_of_conduct", "codeOfConduct"))
                             if files[k] and org_default(field)]
    lower = {n.lower() for n in root}
    runtime = [kind for kind, marks in RUNTIMES if lower & set(marks)]
    return {"runtime": runtime, "codeowners": codeowners, "descriptor": _text(node.get("desc")), "app": _text(node.get("app")),
            "data_branch": bool(node.get("data")), "files": files, "docs": docs if node.get("docs") else None,
            "rule_files": {p: _text(node.get(f"f{i}")) for i, p in enumerate(paths)}}


def prefetch(gql, repos: list[dict], paths: list[str]) -> dict[str, dict]:
    """Each repo's facts by name; repos a batch couldn't read are left out (their readers fall back to REST)."""
    out = {}
    for i in range(0, len(repos), BATCH):
        batch = repos[i:i + BATCH]
        try:
            data = gql.query(query([r["name"] for r in batch], paths), {}).data or {}
        except (GraphQLError, RateLimited):
            continue
        for j, r in enumerate(batch):
            node = data.get(f"r{j}")
            if isinstance(node, dict):
                out[r["name"]] = facts(node, r["name"].split("/")[0], paths)
    return out
