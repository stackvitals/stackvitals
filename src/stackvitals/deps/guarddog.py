"""Opt-in: DataDog's GuardDog on each npm or PyPI package version a pull request adds or upgrades. It downloads the
package and checks its code for what malware does (install hooks that fetch and run code, obfuscation, data sent out);
on a 2026 npm benchmark it was right on 97% of what it flagged and caught 90% of the malware. Pinned, run through uv."""
import json
import re
import subprocess

VERSION = "3.2.0"
MAX_PACKAGES = 10
ECOSYSTEMS = {"npm": "npm", "pypi": "pypi"}
# A plain npm or PyPI name (npm may have a scope): never an option, a path or a URL, which GuardDog would also take.
NAME = re.compile(r"(@[A-Za-z0-9][\w.-]*/)?[A-Za-z0-9][\w.-]*")


def scan(ecosystem: str, name: str, version: str, timeout: int = 180) -> list[str] | None:
    """The rules GuardDog's scan of one package version matched, or None when it couldn't run."""
    # Names come from a pull request's manifest: options go first and `--` ends them, so a name can't act as one.
    if ecosystem not in ECOSYSTEMS or not NAME.fullmatch(name or "") or not version or version.startswith("-"):
        return None
    try:
        run = subprocess.run(["uvx", "--quiet", "--from", f"guarddog=={VERSION}", "guarddog", ECOSYSTEMS[ecosystem], "scan",
                              f"--version={version}", "--output-format=json", "--", name],
                             capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    try:
        doc = json.loads(run.stdout.decode("utf-8", "replace") or "null")
    except ValueError:
        return None
    if not isinstance(doc, dict):
        return None
    return sorted(rule for rule, hits in (doc.get("results") or {}).items() if hits)
