"""Who owns a flaky test or job: CODEOWNERS (read with GitHub's rules) for the test's file, else for its workflow file.
CODEOWNERS and GitHub's error check are read once a day; the repo's file list at most once a day, for new test ids."""
import re

from stackvitals import codeowners
from stackvitals.ci.analyze import SHOWN
from stackvitals.ci.api import APIError, NotFound, OutOfBudget

SOURCE_EXT = {"py", "js", "jsx", "mjs", "cjs", "ts", "tsx", "rb", "go", "rs", "java", "kt", "kts", "scala", "cs", "php",
              "swift", "ex", "exs", "c", "cc", "cpp", "m", "dart", "lua", "sh"}


def _path_like(part: str) -> bool:
    return "/" in part or ("." in part and part.rsplit(".", 1)[-1] in SOURCE_EXT)


def _one(found: list[str]) -> str | None:
    return found[0] if len(found) == 1 else None


def test_file(tid: str, files: list[str] | None) -> str | None:
    """The repo file a test lives in, confirmed against the repo's files: the path in a pytest-style id (or the one file
    ending with it, for runners started in a subfolder), or the one file matching the dotted class name
    (tests.test_calc -> tests/test_calc.py, com.acme.BarTest -> .../com/acme/BarTest.java). No guess when unsure."""
    if not files:
        return None
    parts = tid.split("::")
    if _path_like(parts[0]):
        if parts[0] in files:
            return parts[0]
        return _one([f for f in files if f.endswith("/" + parts[0])])
    if len(parts) < 2 or " " in parts[0]:
        return None
    names = parts[0].split("$", 1)[0].split(".")
    for n in range(len(names), 0, -1):
        stem = "/".join(names[:n])
        found = [f for f in files if f.rsplit(".", 1)[0] == stem or f.rsplit(".", 1)[0].endswith("/" + stem)]
        if found:
            return _one(found)
    return None


def read_codeowners(api, ref: str | None, store, today: str) -> dict:
    """The CODEOWNERS text GitHub uses (first of its three places), the owners its error check says it ignores, and the
    lines it skips as invalid; read at most once a day. A failed read keeps the last answer and tries again next run."""
    state = store.state()
    kept = state.get("codeowners") or {}
    answer = {"text": kept.get("text"), "unknown": set(kept.get("unknown") or []), "skip": set(kept.get("skip") or [])}
    if kept.get("checked") == today:
        return answer
    text = None
    try:
        for path in codeowners.PATHS:
            try:
                text = api.file(path, ref).decode("utf-8", "replace")
                break
            except NotFound:
                continue  # GitHub only moves on to the next place when a file is missing
    except (APIError, OutOfBudget):
        return answer
    unknown, skip = answer["unknown"], answer["skip"]
    if text:
        try:
            errors = (api._get(f"/repos/{api.repo}/codeowners/errors", {"ref": ref} if ref else None) or {}).get("errors") or []
            unknown = {m.group(1).lower() for e in errors if e.get("kind") == "Unknown owner"
                       and (m := re.search(r"make sure (\S+) exists", e.get("message") or ""))}
            skip = {e["line"] for e in errors if e.get("kind") != "Unknown owner" and isinstance(e.get("line"), int)}
        except (APIError, OutOfBudget):
            pass  # the error check is extra: without it every owner is kept as written
    store.save_state({**state, "codeowners": {"checked": today, "text": text, "unknown": sorted(unknown), "skip": sorted(skip)}})
    return {"text": text, "unknown": unknown, "skip": skip}


def test_files(api, ref: str | None, store, today: str, tids: list[str]) -> dict[str, str]:
    """Each test's file, checked against the repo's file list (one request, at most once a day, only for new ids)."""
    state = store.state()
    known = dict(state.get("test_files") or {})
    missing = [t for t in tids if t not in known]
    if missing and state.get("tree_checked") != today:
        try:
            tree = api._get(f"/repos/{api.repo}/git/trees/{ref}", {"recursive": "1"}) or {}
            files = [e["path"] for e in tree.get("tree") or [] if e.get("type") == "blob"]
            for tid in missing:
                if (path := test_file(tid, files)):
                    known[tid] = path
        except (APIError, OutOfBudget):
            pass
        store.save_state({**store.state(), "test_files": known, "tree_checked": today})
    return {t: known[t] for t in tids if t in known}


def attach_owners(result: dict, co: dict, files: dict[str, str]) -> None:
    """Adds `owners` and `owners_from` (the path they were looked up for) to every test and job the dashboard lists."""
    if not co.get("text"):
        return
    rules, unknown = codeowners.parse(co["text"], co.get("skip") or ()), co.get("unknown") or set()
    for t in result.get("tests") or []:
        if t["state"] in SHOWN:
            path = files.get(t["id"])
            owners = codeowners.owners_for(path, rules, unknown) if path else []
            if not owners and t.get("workflow"):
                path, owners = t["workflow"], codeowners.owners_for(t["workflow"], rules, unknown)
            t["owners"], t["owners_from"] = owners, path
    for j in result.get("jobs") or []:
        if j["state"] in SHOWN and j.get("workflow"):
            j["owners"], j["owners_from"] = codeowners.owners_for(j["workflow"], rules, unknown), j["workflow"]


def owners_line(item: dict, mention: bool = False) -> str:
    """Markdown naming the owners; code-formatted names notify nobody unless mentions are turned on."""
    if not item.get("owners"):
        return ""
    # A path can't close the code format early and slip a live @-mention into the issue.
    where = re.sub(r"[`\r\n]", "", item.get("owners_from") or "")
    names = " ".join(item["owners"]) if mention else ", ".join(f"`{o}`" for o in item["owners"])
    return f"Owners (CODEOWNERS for `{where}`): {names}"
