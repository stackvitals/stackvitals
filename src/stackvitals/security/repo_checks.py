"""Repo-level checks (Scorecard's Branch-Protection in tiers, Security-Policy, Signed-Releases and SBOM, Binary-Artifacts,
Fuzzing and the Best Practices badge), each from what GitHub says; what the token can't read is "unknown", never a pass."""
import re

from stackvitals.ci.api import APIError

# Scorecard's own list (checks/raw/binary_artifact.go), so the two agree on what a binary is.
BINARY = re.compile(r"\.(crx|deb|dex|dey|elf|o|a|so|macho|iso|class|jar|bundle|dylib|lib|msi|dll|drv|efi|exe|ocx|pyc|pyo"
                    r"|par|rpm|wasm|whl)$", re.I)
GRADLE_WRAPPER = "gradle/wrapper/gradle-wrapper.jar"
SIGNED = re.compile(r"\.(sig|asc|minisig|sigstore|sigstore\.json|intoto\.jsonl|pem)$", re.I)
SBOM = re.compile(r"(sbom|\.spdx(\.json)?$|\.cdx\.(json|xml)$|cyclonedx|bom\.(json|xml)$)", re.I)
BADGE_API = "https://www.bestpractices.dev/projects.json"
POLICY = ("SECURITY.md", ".github/SECURITY.md", "docs/SECURITY.md", "SECURITY.rst", ".github/SECURITY.rst")
# Real fuzzers only: ClusterFuzzLite, cargo-fuzz targets, libFuzzer sources. A folder merely named "fuzz" (scripts that
# compare outputs) isn't one, as a side-by-side with Scorecard showed.
FUZZ_PATHS = re.compile(r"(^|/)\.clusterfuzzlite/|(^|/)fuzz/(fuzz_targets/)?[^/]+\.rs$|_fuzzer\.(c|cc|cpp)$"
                        r"|(^|/)fuzzers?/[^/]+_fuzzer\.(c|cc|cpp|go|py)$|fuzz[^/]*_test\.go$|(^|/)hfuzz_", re.I)


def _try(api, path: str, params: dict | None = None):
    try:
        return api._get(path, params)
    except APIError:
        return None


def branch_tiers(protection: dict | None, rules: list[dict] | None, summary: dict | None = None) -> dict:
    """Scorecard's five tiers, each "met", "missing" or "unknown". Classic protection needs an admin token to read in
    full; rulesets are readable by anyone who can read the repo; and the branch's public summary (GET branches/{b}) says
    whether classic protection is on and which checks it requires, so without admin those two tiers are still known,
    where Scorecard counts what it can't read as met."""
    kinds = {r.get("type"): r.get("parameters") or {} for r in rules or [] if isinstance(r, dict)}
    p = protection or {}
    pr_rule = kinds.get("pull_request") or {}
    classic_reviews = p.get("required_pull_request_reviews") or {}
    count = classic_reviews.get("required_approving_review_count") or pr_rule.get("required_approving_review_count") or 0
    owners = classic_reviews.get("require_code_owner_reviews") or pr_rule.get("require_code_owner_review")
    stale = classic_reviews.get("dismiss_stale_reviews") or pr_rule.get("dismiss_stale_reviews_on_push")
    full = protection is not None
    s = ((summary or {}).get("protection") or {}) if summary else {}
    classic_on = bool(s.get("enabled"))
    checks = (s.get("required_status_checks") or {})
    required = bool(checks.get("contexts") or checks.get("checks")) and checks.get("enforcement_level") != "off"

    def tier(ok_full, ok_rules, ok_summary=None):
        # Full classic settings decide; else rulesets; else the public summary; else nothing is known.
        if full:
            return "met" if ok_full else "missing"
        if ok_rules:
            return "met"
        if ok_summary is not None:
            return "met" if ok_summary else "missing"
        # Classic protection is on but unreadable without admin: it may hold this rule, so it isn't called missing.
        return "missing" if rules and not classic_on else "unknown"
    tiers = [
        ("no force pushes or deletion", tier(not (p.get("allow_force_pushes") or {}).get("enabled", True)
                                             and not (p.get("allow_deletions") or {}).get("enabled", True),
                                             "non_fast_forward" in kinds and "deletion" in kinds,
                                             # Classic protection blocks both unless an admin allowed them.
                                             True if classic_on else None)),
        ("reviews required", tier(bool(classic_reviews) and count >= 1, bool(pr_rule) and count >= 1)),
        ("status checks required", tier(bool(p.get("required_status_checks")), "required_status_checks" in kinds,
                                        required if summary else None)),
        ("two reviewers and code owners", tier(count >= 2 and bool(owners), count >= 2 and bool(owners))),
        ("stale reviews dismissed, admins included", tier(bool(stale) and (p.get("enforce_admins") or {}).get("enabled"),
                                                          bool(stale) and bool(rules))),
    ]
    known = full or bool(rules) or classic_on
    out = [{"tier": i + 1, "rule": name, "state": state} for i, (name, state) in enumerate(tiers)]
    met = 0
    for t in out:
        if t["state"] != "met":
            break
        met += 1
    return {"tiers": out, "level": met, "readable": known}


def policy(api, repo: str, owner: str) -> dict:
    """SECURITY.md in the repo or the owner's .github repo, its contact and disclosure words; private reporting on."""
    text, where = None, None
    for repo_name, path in [(repo, p) for p in POLICY] + [(f"{owner}/.github", "SECURITY.md")]:
        got = _try(api, f"/repos/{repo_name}/contents/{path}")
        if isinstance(got, dict) and got.get("content"):
            import base64
            text, where = base64.b64decode(got["content"]).decode("utf-8", "replace"), f"{repo_name}:{path}"
            break
    reporting = _try(api, f"/repos/{repo}/private-vulnerability-reporting")
    low = (text or "").lower()
    return {"file": where, "contact": bool(re.search(r"@|https?://|security advisor", low)),
            "disclosure": bool(re.search(r"disclos|vulnerab|days|report", low)),
            "private_reporting": (reporting or {}).get("enabled") if isinstance(reporting, dict) else None}


def releases(rels: list[dict]) -> dict:
    """The last five releases' assets: signed or attested ones, and an SBOM among them."""
    last = [r for r in rels or [] if not r.get("draft")][:5]
    signed = [r.get("tag_name") for r in last if any(SIGNED.search(a.get("name") or "") for a in r.get("assets") or [])]
    sbom = [r.get("tag_name") for r in last if any(SBOM.search(a.get("name") or "") for a in r.get("assets") or [])]
    return {"releases": len(last), "signed": signed, "sbom": sbom}


def tree_facts(paths: list[str]) -> dict:
    """Committed binaries (Gradle's wrapper jar left out, as Scorecard leaves it), SBOM files and fuzzing setups."""
    return {"binaries": sorted(p for p in paths if BINARY.search(p) and not p.endswith(GRADLE_WRAPPER))[:50],
            "sbom_files": sorted(p for p in paths if SBOM.search(p.rsplit("/", 1)[-1]))[:10],
            "fuzzing": sorted({p for p in paths if FUZZ_PATHS.search(p)})[:10]}


# Executable file headers: ELF, Mach-O (both byte orders, fat), Windows PE.
MAGIC = (b"\x7f\x45\x4c\x46", b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"MZ")
MAX_SNIFF, SNIFF_BYTES = 10, 20_000_000


def sniff_candidates(entries: list[dict]) -> list[dict]:
    """Executable-mode files with no extension (where Scorecard's name list sees nothing), small enough to read."""
    return [e for e in entries if e.get("type") == "blob" and e.get("mode") == "100755"
            and "." not in e["path"].rsplit("/", 1)[-1] and 1024 <= (e.get("size") or 0) <= SNIFF_BYTES][:MAX_SNIFF]


def is_executable(head: bytes) -> bool:
    """Whether a file's first bytes are an executable's (a script starting with #! is not)."""
    return any(head.startswith(m) for m in MAGIC)


def badge(get_json, repo_url: str) -> str | None:
    """The OpenSSF Best Practices badge level (passing, silver, gold) from bestpractices.dev, else None."""
    try:
        found = get_json(f"{BADGE_API}?url={repo_url}") or []
    except Exception:  # noqa: BLE001 - a lookup that fails says nothing either way
        return None
    return (found[0] or {}).get("badge_level") if isinstance(found, list) and found else None
