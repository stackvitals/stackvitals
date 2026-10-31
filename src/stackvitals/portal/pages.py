"""Markdown pages in the portal repo, which GitHub shows only to people who can read that repo. Private repos never reach
a page anyone else can open."""
from stackvitals.flow.report import _md


def publishable(repos: list[dict], destination_private: bool) -> list[dict]:
    # The guard: a public destination gets public repos only, whatever the token could read.
    return list(repos) if destination_private else [r for r in repos if not r.get("private")]


def _cell(text) -> str:
    return _md(" ".join(str(text).split())).replace("@", "@​")


def _owners(r: dict) -> tuple[str, str]:
    o = r.get("owners") or {}
    why = "; ".join((o.get("reasons") or []) + (o.get("notes") or []))
    if o.get("suggested"):
        why += ("; " if why else "") + f"suggested from {o.get('suggested_from') or 'recent commits'}: " + ", ".join(o["suggested"])
    return o.get("status") or "-", why


CATALOG_ROWS = 200


def catalog_entities(active: list[dict]) -> tuple[list[dict], list[tuple[str, str]], int]:
    """Every entity the active repos' catalog-info.yaml files declare (with its repo), their problems, and how many
    repos have a file."""
    entities, problems, files = [], [], 0
    for r in active:
        d = r.get("descriptor") or {}
        if d.get("present"):
            files += 1
            entities += [{**e, "repo": r["name"]} for e in d.get("entities") or []]
            problems += [(r["name"], p) for p in d.get("problems") or []]
    return entities, problems, files


def _owner_cell(e: dict) -> str:
    check = e.get("owner_check") or []
    note = {"pass": "", "fail": " (not in CODEOWNERS)"}.get(check[0] if check else "", "")
    return f"{e.get('owner') or '-'}{note}"


def _catalog_lines(active: list[dict]) -> list[str]:
    entities, problems, files = catalog_entities(active)
    if not files:
        return []
    off = sum(1 for e in entities if (e.get("owner_check") or [""])[0] == "fail")
    out = ["## Catalog", "", f"{len(entities)} entities from {files} of {len(active)} active repos' catalog-info.yaml files"
           + (f"; {off} owner{'' if off == 1 else 's'} not in CODEOWNERS" if off else "") + ".", "",
           "| Entity | Kind | Type | Lifecycle | Owner | System | Repo |", "|---|---|---|---|---|---|---|"]
    for e in entities[:CATALOG_ROWS]:
        out.append(f"| {_cell(e['name'])} | {e['kind']} | {_cell(e.get('type') or '-')} | {_cell(e.get('lifecycle') or '-')} | "
                   f"{_cell(_owner_cell(e))} | {_cell(e.get('system') or '-')} | {_cell(e['repo'])} |")
    if problems:
        out += ["", "Problems: " + "; ".join(f"{_cell(repo)}: {_cell(p)}" for repo, p in problems[:20]) + "."]
    return out + [""]


def render_catalog(catalog: dict, destination_private: bool) -> str:
    """The catalog page: owner status counts, then one row per active repo with the evidence."""
    repos = publishable(catalog["repos"], destination_private)
    active = [r for r in repos if not r.get("archived") and not r.get("fork")]
    counts = {s: sum(1 for r in active if (r.get("owners") or {}).get("status") == s) for s in ("valid", "weak", "none")}
    archived, forks = sum(1 for r in repos if r.get("archived")), sum(1 for r in repos if r.get("fork") and not r.get("archived"))
    out = [f"# Portal: {_cell(catalog['org'])}", "",
           f"{len(repos)} repos ({len(active)} active, {archived} archived, {forks} forks), updated {catalog['built_at'][:16]} UTC.",
           "", f"Owners: {counts['valid']} valid, {counts['weak']} weak, {counts['none']} without a CODEOWNERS file.", ""]
    if len(repos) < len(catalog["repos"]):
        out += ["Private repos are left out of this page because the portal repo is public.", ""]
    if not catalog.get("complete", True):
        out += ["Some repos keep an earlier check (GitHub's hourly limit); the next run continues with them.", ""]
    scored = [r for r in active if r.get("score")]
    if scored:
        n = {lvl: sum(1 for r in scored if r["score"]["level"] == lvl) for lvl in ("gold", "silver", "bronze", None)}
        out += [f"Levels: {n['gold']} gold, {n['silver']} silver, {n['bronze']} bronze, {n[None]} below bronze.", ""]
        failed = {}
        for r in scored:
            for res in r["score"]["results"]:
                if res["result"] == "fail":
                    failed[res["id"]] = failed.get(res["id"], 0) + 1
        if failed:
            top = sorted(failed.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            out += ["Most failed rules: " + ", ".join(f"{_cell(k)} ({v} repo{'' if v == 1 else 's'})" for k, v in top) + ".", ""]
    for c in catalog.get("campaigns") or []:
        left = f"; {c['days_left']} days left (until {c['until']})" if c.get("days_left") is not None else ""
        out += [f"## Campaign: {_cell(c['title'])}", "",
                f"{c['passing']} of {c['targets']} repos pass ({', '.join(_cell(r) for r in c['rules'])}){left}."]
        if c["failing"]:
            out.append("Still failing: " + ", ".join(_cell(n) for n in c["failing"][:30])
                       + (f" and {len(c['failing']) - 30} more" if len(c["failing"]) > 30 else "") + ".")
        if len(c["burn_down"]) > 1:
            out.append("Failing over time: " + " → ".join(f"{d} {n}" for d, n in c["burn_down"][-8:]) + ".")
        out.append("")
    out += _catalog_lines(active)
    out += ["## Repos", "", "| Repo | Level | Owners | Why | Language | Last push | CI first try | Community | Branch rules |",
            "|---|---|---|---|---|---|---|---|---|"]
    for r in active:
        status, why = _owners(r)
        m = r.get("modules") or {}
        rules = r.get("rules")
        level = ((r.get("score") or {}).get("level") or "below bronze") if r.get("score") else "-"
        when = r.get("since") or {}
        if when.get("owners") and status != "-":
            status = f"{status} since {when['owners']}"
        if when.get("level") and r.get("score"):
            level = f"{level} since {when['level']}"
        out.append(f"| {_cell(r['name'])} | {level} | {status} | {_cell(why) or '-'} | {_cell(r.get('language') or '-')} | "
                   f"{(r.get('pushed') or '-')[:10]} | {_cell(m.get('ci_first_try') or '-')} | {_cell(m.get('community_score') or '-')} | "
                   f"{len(rules) if isinstance(rules, list) else 'not available'} |")
    return "\n".join(out) + "\n"


def render_catalog_html(catalog: dict, destination_private: bool, pages=()) -> str:
    """The same catalog as a page in the shared header (docs/portal.html), under the same guard as the Markdown."""
    import html

    from stackvitals import shell
    e = html.escape
    repos = publishable(catalog["repos"], destination_private)
    active = [r for r in repos if not r.get("archived") and not r.get("fork")]
    counts = {s: sum(1 for r in active if (r.get("owners") or {}).get("status") == s) for s in ("valid", "weak", "none")}
    body = [f"<p>{len(repos)} repos ({len(active)} active). Owners: {counts['valid']} valid, {counts['weak']} weak, "
            f"{counts['none']} without a CODEOWNERS file.</p>"]
    if len(repos) < len(catalog["repos"]):
        body.append("<p class=mut>Private repos are left out of this page because the portal repo is public.</p>")
    for c in catalog.get("campaigns") or []:
        body.append(f"<h2>Campaign: {e(c['title'])}</h2><p>{c['passing']} of {c['targets']} repos pass "
                    f"({e(', '.join(c['rules']))}).</p>")
    entities, problems, files = catalog_entities(active)
    if files:
        body.append(f"<h2>Catalog</h2><p>{len(entities)} entities from {files} of {len(active)} active repos' catalog-info.yaml "
                    "files.</p><div class=tbl><table class=find><tr><th>Entity</th><th data-filter>Kind</th><th data-filter>Type</th>"
                    "<th data-filter>Lifecycle</th><th>Owner</th><th data-filter>System</th><th>Repo</th></tr>")
        body += [f"<tr><td>{e(x['name'])}</td><td>{e(x['kind'])}</td><td>{e(x.get('type') or '-')}</td>"
                 f"<td>{e(x.get('lifecycle') or '-')}</td><td>{e(_owner_cell(x))}</td><td>{e(x.get('system') or '-')}</td>"
                 f"<td>{e(x['repo'])}</td></tr>" for x in entities[:CATALOG_ROWS]]
        body.append("</table></div>")
        if problems:
            body.append("<p class=mut>Problems: " + "; ".join(f"{e(repo)}: {e(p)}" for repo, p in problems[:20]) + ".</p>")
    body.append("<h2>Repos</h2><div class=tbl><table class=find><tr><th data-filter>Level</th><th>Repo</th>"
                "<th data-filter>Owners</th><th>Why</th><th data-filter>Language</th><th>Last push</th><th>CI first try</th>"
                "<th>Community</th></tr>")
    for r in active:
        status, why = _owners(r)
        m = r.get("modules") or {}
        level = ((r.get("score") or {}).get("level") or "below bronze") if r.get("score") else "-"
        body.append(f"<tr><td>{e(level)}</td><td>{e(str(r['name']))}</td><td>{e(status)}</td><td class=mut>{e(why) or '-'}</td>"
                    f"<td>{e(str(r.get('language') or '-'))}</td><td>{e((r.get('pushed') or '-')[:10])}</td>"
                    f"<td>{e(str(m.get('ci_first_try') or '-'))}</td><td>{e(str(m.get('community_score') or '-'))}</td></tr>")
    body.append("</table></div>")
    return shell.page("Portal", catalog["org"], "portal.html", f"Updated {e(catalog['built_at'][:16])} UTC.", "".join(body), pages)
