"""A repo's catalog-info.yaml, Backstage's descriptor format (Port and Cortex read it too): what the repo says it is, who
owns it, which system it belongs to and what it depends on. Read with safe YAML only; problems are listed, never fatal."""
import re

import yaml

FILE = "catalog-info.yaml"
MAX_BYTES = 256_000
MAX_DOCS = 50
KINDS = {k.lower(): k for k in ("Component", "API", "Resource", "System", "Domain", "Group", "User", "Location", "Template")}
# The spec fields Backstage itself requires for these kinds.
NEEDS = {"Component": ("type", "lifecycle", "owner"), "API": ("type", "lifecycle", "owner"), "Resource": ("type", "owner"),
         "System": ("owner",), "Domain": ("owner",)}
REF = re.compile(r"^(?:([A-Za-z][\w-]*):)?(?:([\w.-]+)/)?([\w.-]+)$")


def _text(value, cap: int = 200) -> str | None:
    # Scalars only (str() of a container could expand an alias bomb), and no huge numbers.
    if isinstance(value, bool) or not isinstance(value, (str, int, float)) or isinstance(value, int) and value.bit_length() > 256:
        return None
    return " ".join(str(value).split())[:cap] or None


def _names(value) -> list[str]:
    return [t for x in value[:50] if (t := _text(x))] if isinstance(value, list) else []


def ref(value: str | None, default_kind: str) -> tuple[str, str, str] | None:
    """Backstage's entity reference `[kind:][namespace/]name`, lower-cased, or None."""
    found = REF.match(str(value or "").strip())
    if not found:
        return None
    kind, namespace, name = found.groups()
    return (kind or default_kind).lower(), (namespace or "default").lower(), name.lower()


def _entity(doc: dict) -> dict:
    meta = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    spec = doc.get("spec") if isinstance(doc.get("spec"), dict) else {}
    links = [{"url": str(x["url"])[:300], "title": _text(x.get("title"), 80) or str(x["url"])[:80]}
             for x in (meta.get("links") if isinstance(meta.get("links"), list) else [])[:5]
             if isinstance(x, dict) and re.match(r"https?://", str(x.get("url") or ""))]
    return {"kind": KINDS[str(doc["kind"]).lower()], "name": _text(meta.get("name"), 100), "title": _text(meta.get("title"), 100),
            "description": _text(meta.get("description")), "type": _text(spec.get("type"), 60),
            "lifecycle": _text(spec.get("lifecycle"), 60), "owner": _text(spec.get("owner"), 120),
            "system": _text(spec.get("system"), 120), "domain": _text(spec.get("domain"), 120),
            "part_of": _text(spec.get("subcomponentOf"), 120), "depends_on": _names(spec.get("dependsOn")),
            "provides_apis": _names(spec.get("providesApis")), "consumes_apis": _names(spec.get("consumesApis")),
            "tags": _names(meta.get("tags"))[:10], "links": links}


def parse(text: str) -> tuple[list[dict], list[str]]:
    """The entities a catalog-info.yaml declares and the problems in it, in plain words."""
    if len(text.encode("utf-8", "replace")) > MAX_BYTES:
        return [], [f"{FILE} is over {MAX_BYTES // 1000} KB; not read"]
    try:
        docs = [d for d in yaml.safe_load_all(text)][:MAX_DOCS + 1]
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark is not None else ""
        return [], [f"not valid YAML{where}: {getattr(exc, 'problem', None) or type(exc).__name__}"]
    except Exception as exc:  # deep nesting, impossible dates, numbers too long to convert: the file is the problem
        return [], [f"not valid YAML: {type(exc).__name__}"]
    docs = [d for d in docs if d is not None]
    if not docs:
        return [], [f"{FILE} is empty"]
    entities, problems = [], []
    if len(docs) > MAX_DOCS:
        problems.append(f"only the first {MAX_DOCS} documents were read")
    for i, doc in enumerate(docs[:MAX_DOCS], 1):
        if not isinstance(doc, dict):
            problems.append(f"document {i} is not a mapping")
            continue
        kind = doc.get("kind")
        if not isinstance(kind, str) or kind.lower() not in KINDS:
            problems.append(f"document {i}: {_text(kind, 40) or 'no kind'} is not a Backstage kind")
            continue
        try:
            e = _entity(doc)
        except Exception as exc:  # one odd document never hides the others
            problems.append(f"document {i}: could not be read ({type(exc).__name__})")
            continue
        if not e["name"]:
            problems.append(f"document {i}: no metadata.name")
            continue
        missing = [f for f in NEEDS.get(e["kind"], ()) if not e[f]]
        if missing:
            problems.append(f"{e['kind']} {e['name']}: no {', '.join(missing)}")
        entities.append(e)
    return entities, problems


def owner_check(owner: str | None, codeowners: list[str]) -> tuple[str, str]:
    """pass when the catalog's owner is named in CODEOWNERS (a team as @org/team, a person as @login), fail when not."""
    if not owner:
        return "fail", f"{FILE} names no owner"
    found = ref(owner, "group")
    named = {}
    for o in codeowners:
        if o.startswith("@"):
            named.setdefault(o[1:].split("/")[-1].lower(), o)
    if found and found[2] in named:
        return "pass", f"{found[2]} is {named[found[2]]} in CODEOWNERS"
    listed = [o for o in codeowners if o.startswith("@")]
    return "fail", f"{FILE} names {owner}; CODEOWNERS names {', '.join(listed) or 'nobody'}"
