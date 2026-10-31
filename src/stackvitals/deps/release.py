"""Signs a new release may be compromised, before any advisory exists: it is only hours old, it adds an install script,
it pulls in new dependencies, or the signed record of where it was built is gone. Compared with the version it
replaces, from the registries' own metadata. A sign is a reason to look first, never a block."""
from datetime import datetime, timedelta
from urllib.parse import quote

NPM = "https://registry.npmjs.org"
PYPI = "https://pypi.org"
DEPS_DEV = "https://api.deps.dev/v3/systems"
HOOKS = ("preinstall", "install", "postinstall")
# 2025-26 compromised releases stayed up from 40 minutes to a few hours; a release younger than this gets a sign.
COOLDOWN = timedelta(hours=48)
MAX_PACKAGES = 30


def _key(version: str) -> list:
    import re
    return [(0, int(p)) if p.isdigit() else (1, p) for p in re.split(r"[.\-+_]", str(version)) if p]


def _get(client, url: str) -> dict | None:
    try:
        r = client.get(url)
    except Exception:  # noqa: BLE001 - a registry hiccup means no sign, never a failed check
        return None
    return r.json() if r.status_code == 200 else None


def _age(published: str | None, now: datetime) -> str | None:
    if not published:
        return None
    when = datetime.fromisoformat(published.replace("Z", "+00:00"))
    hours = (now - when).total_seconds() / 3600
    if 0 <= hours < COOLDOWN.total_seconds() / 3600:
        n = max(1, round(hours))
        return (f"Released {n} hour{'' if n == 1 else 's'} ago: compromised releases are usually found and pulled within hours, "
                "so a few days' wait is safer.")
    return None


def npm_signs(client, name: str, old: str | None, new: str, now: datetime) -> list[str]:
    path = quote(name, safe="@")
    after = _get(client, f"{NPM}/{path}/{quote(new)}")
    if not after:
        return []
    signs = []
    meta = _get(client, f"{DEPS_DEV}/npm/packages/{quote(name, safe='')}/versions/{quote(new, safe='')}") or {}
    if age := _age(meta.get("publishedAt"), now):
        signs.append(age)
    before = _get(client, f"{NPM}/{path}/{quote(old)}") if old else None
    hooks = [h for h in HOOKS if (after.get("scripts") or {}).get(h)]
    if before is not None:
        added = [h for h in hooks if not (before.get("scripts") or {}).get(h)]
        if added:
            signs.append(f"Adds an install script ({', '.join(added)}) that {old} didn't have: it runs when the package installs.")
        new_deps = sorted(set(after.get("dependencies") or {}) - set(before.get("dependencies") or {}))
        if new_deps:
            signs.append(f"New dependencies since {old}: {', '.join(new_deps[:5])}{' and more' if len(new_deps) > 5 else ''}.")
        if (before.get("dist") or {}).get("attestations") and not (after.get("dist") or {}).get("attestations"):
            signs.append(f"{old} carried build provenance (a signed record of where it was built); {new} doesn't.")
    return signs


def _pypi_release(client, name: str, version: str) -> dict | None:
    return _get(client, f"{PYPI}/pypi/{quote(name)}/{quote(version)}/json")


def _pypi_provenance(client, name: str, version: str, doc: dict) -> bool | None:
    files = doc.get("urls") or []
    if not files:
        return None
    try:
        r = client.get(f"{PYPI}/integrity/{quote(name)}/{quote(version)}/{quote(files[0]['filename'])}/provenance")
    except Exception:  # noqa: BLE001
        return None
    return r.status_code == 200


def pypi_signs(client, name: str, old: str | None, new: str, now: datetime) -> list[str]:
    after = _pypi_release(client, name, new)
    if not after:
        return []
    signs = []
    times = sorted(u.get("upload_time_iso_8601") for u in after.get("urls") or [] if u.get("upload_time_iso_8601"))
    if age := _age(times[0] if times else None, now):
        signs.append(age)
    before = _pypi_release(client, name, old) if old else None
    if before is not None:
        def names(doc):
            import re
            return {re.split(r"[\s<>=!~;\[(]", r, 1)[0].lower() for r in (doc.get("info") or {}).get("requires_dist") or []
                    if "extra ==" not in r}
        new_deps = sorted(names(after) - names(before))
        if new_deps:
            signs.append(f"New dependencies since {old}: {', '.join(new_deps[:5])}{' and more' if len(new_deps) > 5 else ''}.")
        if _pypi_provenance(client, name, old, before) and _pypi_provenance(client, name, new, after) is False:
            signs.append(f"{old} carried build provenance (a signed record of where it was built); {new} doesn't.")
    return signs


def release_signs(client, ecosystem: str, name: str, old_versions: list[str], new_versions: list[str],
                  now: datetime) -> list[str]:
    """Signs for the newest version a change installs, against the newest version it replaces."""
    if not new_versions or ecosystem not in ("npm", "pypi"):
        return []
    new = max(new_versions, key=_key)
    old = max(old_versions, key=_key) if old_versions else None
    if old and _key(old) >= _key(new):
        return []  # a downgrade or the same version: nothing new arrived
    return (npm_signs if ecosystem == "npm" else pypi_signs)(client, name, old, new, now)
