"""The files the StackVitals app reads, written beside the pages at the end of every job: app.json (what ran and when,
links, the key facts), settings.json (every setting with its default and current value), decisions.json (what people
decided, with the log) and, for public repos, the summary tables, so the app and Explore read everything from Pages
itself rather than raw.githubusercontent.com, which GitHub throttles. Files are rewritten only when they change."""
import json
import shutil
from pathlib import Path

from stackvitals.core import schema
from stackvitals.core.config import FILE, parse
from stackvitals.core.decisions import UNDO, Store
from stackvitals.core.store import published, write_if_changed

# Module, its published file and its page; Portal keeps its catalog outside docs/ (copied in for the app).
MODULES = (("ci", "data.json", "ci.html"), ("flow", "flow.json", "flow.html"), ("delivery", "delivery.json", "delivery.html"),
           ("insights", "insights.json", "insights.html"), ("community", "community.json", "community.html"),
           ("portal", "portal.json", "portal.html"), ("alerts", "alerts.json", None), ("deps", "deps.json", None),
           ("supply", "supply.json", None), ("vulns", "vulns.json", None), ("security", "security.json", None))
LOG_ROWS = 200


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def facts(docs: dict) -> dict:
    """The few numbers a home page, the digest or an org view lead with; None where a module didn't run."""
    data, flow, delivery = docs.get("ci") or {}, docs.get("flow") or {}, docs.get("delivery") or {}
    items = (data.get("tests") or []) + (data.get("jobs") or [])
    phase = lambda name: ((delivery.get("phases") or {}).get(name) or {}).get("p75_h")
    found = (docs.get("insights") or {}).get("findings") or []
    return {
        "ci_first_try": (data.get("pushes") or {}).get("first_try_share") if data else None,
        "ci_flaky": sum(1 for i in items if i.get("state") == "flaky") if data else None,
        "ci_broken": sum(1 for i in items if i.get("state") == "broken") if data else None,
        "open_prs": flow.get("open"), "stale_prs": flow.get("stale"),
        "pickup_p75_h": phase("pickup"), "review_p75_h": phase("review"), "cycle_p75_h": phase("cycle_to_merge"),
        "deployments": (delivery.get("dora") or {}).get("deployments"),
        "change_failure_rate": (delivery.get("dora") or {}).get("change_failure_rate"),
        "newcomers_waiting": (docs.get("community") or {}).get("waiting_total"),
        "findings": sum(1 for f in found if not f.get("decision")) if docs.get("insights") else None,
        "first_review_median_s": ((flow.get("stages") or {}).get("pickup") or {}).get("median_s"),
        "community_score": ((docs.get("community") or {}).get("score") or {}).get("score"),
        "vulns_open": len((docs.get("vulns") or {}).get("open") or []) if docs.get("vulns") else None,
        "vulns_serious": sum(1 for v in (docs.get("vulns") or {}).get("open") or []
                             if v.get("malware") or v.get("severity") in ("critical", "high")) if docs.get("vulns") else None,
    }


def write_app_data(ws) -> None:
    root, now = ws.path, ws.now
    docs_dir = root / "docs"
    if not docs_dir.is_dir():
        return
    info = ws.cache.get("repo_info") or {}
    last = _read(docs_dir / "app.json") or {}
    branch = info.get("default_branch") or last.get("default_branch") or "main"
    # Without the repo's details, the last known visibility holds; never known means private (publish nothing).
    private = bool(info["private"]) if "private" in info else last.get("visibility") != "public"
    if private and info.get("has_pages") and (ws.env.get("STACKVITALS_PAGES_MODE") or "branch") != "artifact":
        # Pages from a private repo are public on most plans: say so on every run until it's changed.
        ws.notes.append("This repo is private but has GitHub Pages turned on; unless your plan keeps Pages private, anyone "
                        "with the address can read the app. Turn Pages off and set pages: artifact, or use stackvitals ui.")
    catalog = _read(root / "portal" / "catalog.json")
    if catalog is not None:
        # The app's copy is packed (each rule named once) and compact: 10,000 repos would be 24 MB as written.
        from stackvitals.portal.scorecard import pack
        write_if_changed(docs_dir / "portal.json", published(pack(catalog)), compact=True)
    docs = {name: _read(docs_dir / file) for name, file, _page in MODULES}
    workflow = (ws.env.get("GITHUB_WORKFLOW_REF") or "").split("@")[0].rsplit("/", 1)[-1] or None
    base = f"https://github.com/{ws.repo}"
    state, log = Store(root).state(now.date()), Store(root).log()
    write_if_changed(docs_dir / "app.json", published({
        "repo": ws.repo, "default_branch": branch, "visibility": "private" if private else "public",
        "modules": {name: {"updated": (docs[name] or {}).get("generated") or (docs[name] or {}).get("built_at"), "file": file,
                           **({"page": page} if page and (docs_dir / page).exists() else {})}
                    for name, file, page in MODULES if docs[name] is not None},
        "pages": sorted(p.name for p in docs_dir.glob("*.html")),
        "facts": {**facts(docs), "decisions": sum(1 for v in state.values() if v.get("kind") != "setting" and v.get("verb") not in UNDO)},
        "links": {"repo": base, "workflow": workflow,
                  "actions": f"{base}/actions/workflows/{workflow}" if workflow else f"{base}/actions",
                  "settings_file": f"{base}/blob/{branch}/{FILE}", "edit_settings": f"{base}/edit/{branch}/{FILE}",
                  "new_issue": f"{base}/issues/new"},
        "summary": "summary/" if not private else None,
    }))
    cfg = ws.cache.get("settings") or parse("")[0]
    write_if_changed(docs_dir / "settings.json", published({
        "file": FILE, "settings": schema.to_json(), "values": cfg, "notes": list(ws.cache.get("settings_notes") or [])}))
    write_if_changed(docs_dir / "decisions.json", published({"state": state, "log": list(reversed(log))[:LOG_ROWS]}))
    _tables(root, private)


def _tables(root: Path, private: bool) -> None:
    """Public repos: the summary tables next to the pages (git keeps one copy of identical files). Private: kept out."""
    src, dst = root / "summary", root / "docs" / "summary"
    if private or not src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        return
    dst.mkdir(parents=True, exist_ok=True)
    names = {p.name for p in src.iterdir() if p.is_file()}
    for p in dst.iterdir():
        if p.is_file() and p.name not in names:
            p.unlink()
    for name in names:
        data = (src / name).read_bytes()
        target = dst / name
        if not target.exists() or target.read_bytes() != data:
            target.write_bytes(data)
