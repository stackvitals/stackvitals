"""Names that imitate a popular package (typosquats): one edit away, or the same letters with other separators. The
popular names are the ones the dependency evidence already covers (the crawl's most-used and most-upgraded packages)."""
import re

MIN_LENGTH = 5  # shorter popular names have too many real neighbours ("chalk", "chai")


def _norm(eco: str, name: str) -> str:
    name = name.lower()
    return re.sub(r"[-_.]+", "-", name) if eco == "pypi" else name


def _one_edit(a: str, b: str) -> bool:
    """True when b is a with one letter added, dropped, changed, or two neighbours swapped."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(short) and short[i] == long_[i]:
        i += 1
    return short[i:] == long_[i + 1:]


def lookalike(eco: str, name: str, popular: dict[str, set[str]]) -> str | None:
    """The popular package `name` imitates, or None (a popular name itself, a scoped one, or nothing close)."""
    names = {_norm(eco, p): p for p in popular.get(eco) or ()}
    mine = _norm(eco, name)
    if not names or mine in names or mine.startswith("@"):
        return None
    bare = re.sub(r"[-_.]", "", mine)
    for norm, original in sorted(names.items()):
        if len(norm) < MIN_LENGTH or norm.startswith("@"):
            continue
        if _one_edit(norm, mine) or (bare == re.sub(r"[-_.]", "", norm) and bare != mine):
            return original
    return None


# On OpenSSF's malicious look-alikes the weekly downloads were 1 to 75; legitimate look-alikes of popular names had
# 823,598 to 192 million (bench/accuracy/deps). Under this, a look-alike is flagged.
LOW_DOWNLOADS = 1000


NPM_STATS, PYPI_STATS = "https://api.npmjs.org", "https://pypistats.org"


def weekly_downloads(eco: str, name: str, client) -> int | None:
    """Last week's downloads from the registry's free stats (npm's API, pypistats for PyPI); None when unknown."""
    import httpx
    url = (f"{NPM_STATS}/downloads/point/last-week/{name}" if eco == "npm"
           else f"{PYPI_STATS}/api/packages/{_norm('pypi', name)}/recent" if eco == "pypi" else None)
    if not url or client is None:
        return None
    try:
        resp = client.get(url)
        body = resp.json() if resp.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return None
    value = body.get("downloads") if eco == "npm" else (body.get("data") or {}).get("last_week")
    return value if isinstance(value, int) else None


def judge(eco: str, name: str, popular: dict[str, set[str]], client) -> dict | None:
    """A verdict for a package a PR adds whose name imitates a popular one and that few people use, else None."""
    target = lookalike(eco, name, popular)
    if not target:
        return None
    downloads = weekly_downloads(eco, name, client)
    if downloads is not None and downloads >= LOW_DOWNLOADS:
        return None
    if downloads is None:
        # Without the download count the name alone false-alarms on real neighbours (preact and react): a note, not an alarm.
        return {"verdict": "monitor", "reasons": [f"Its name is one edit from the popular {target}, and its downloads "
                                                 f"couldn't be checked. Check you meant {target}."]}
    return {"verdict": "investigate", "reasons": [f"Its name is one edit from the popular {target} and it has "
                                                 f"{downloads:,} downloads last week: a common way to slip in a malicious "
                                                 f"package. Check you meant {target}."]}
