"""Reachability from govulncheck (Go's own free scanner, run in the team's workflow): for each advisory, whether the code
only requires the module, imports the vulnerable package, or calls the vulnerable function, with the call path."""
import json

LEVELS = ("required", "imported", "called")


def _short(frame: dict) -> str:
    # "example.com/app/web" + "render" reads as "web.render"; the program's entry stays "main".
    fn = frame.get("function") or ""
    pkg = (frame.get("package") or "").rsplit("/", 1)[-1]
    if frame.get("receiver"):
        fn = f"{frame['receiver'].lstrip('*')}.{fn}"
    return fn if fn == "main" or not pkg else f"{pkg}.{fn}"


def read_govulncheck(text: str) -> dict:
    """govulncheck -format json output: each advisory's deepest reach, its fixing version, aliases and call path."""
    osv, found, scanner = {}, {}, None
    for line in _objects(text):
        if isinstance(line.get("config"), dict):
            c = line["config"]
            scanner = f"{c.get('scanner_name', 'govulncheck')} {c.get('scanner_version', '')}".strip()
        elif isinstance(line.get("osv"), dict) and line["osv"].get("id"):
            osv[line["osv"]["id"]] = line["osv"]
        elif isinstance(line.get("finding"), dict) and line["finding"].get("osv"):
            f = line["finding"]
            trace = [t for t in f.get("trace") or [] if isinstance(t, dict)]
            top = trace[0] if trace else {}
            reach = "called" if top.get("function") else "imported" if top.get("package") else "required"
            mine = found.setdefault(f["osv"], {"id": f["osv"], "reach": reach, "fixed": f.get("fixed_version"),
                                                "module": top.get("module"), "version": top.get("version"), "path": []})
            if LEVELS.index(reach) >= LEVELS.index(mine["reach"]):
                mine["reach"] = reach
                if reach == "called":
                    mine["path"] = [_short(t) for t in reversed(trace) if t.get("function")]
    findings = []
    for i, f in sorted(found.items()):
        o = osv.get(i) or {}
        findings.append({**f, "aliases": list(o.get("aliases") or []), "summary": str(o.get("summary") or "")[:200]})
    return {"scanner": scanner, "findings": findings,
            "counts": {level: sum(1 for f in findings if f["reach"] == level) for level in LEVELS}}


def _objects(text: str):
    # govulncheck writes indented JSON objects one after another; read them whole, skipping anything else.
    decoder, at = json.JSONDecoder(), 0
    while at < len(text):
        start = text.find("{", at)
        if start < 0:
            return
        try:
            obj, end = decoder.raw_decode(text, start)
        except ValueError:
            at = start + 1
            continue
        at = end
        if isinstance(obj, dict):
            yield obj
