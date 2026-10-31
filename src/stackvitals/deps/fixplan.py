"""Guided fixes (OSV-Scanner's guided remediation, without its resolver): for each finding, the smallest upgrade that
fixes it, how big a jump that is (a major one may break things), and the command that makes it in that ecosystem."""
import re

COMMANDS = {
    "npm": "npm install {name}@{to}",
    "PyPI": "pip install \"{name}>={to}\"  (uv: uv add \"{name}>={to}\")",
    "Go": "go get {name}@v{to}",
    "crates.io": "cargo update -p {name} --precise {to}",
    "RubyGems": "bundle update {name} --conservative",
    "Packagist": "composer require {name}:^{to}",
    "NuGet": "dotnet add package {name} --version {to}",
    "Maven": "set {name} to {to} in the pom or Gradle file",
    "Pub": "dart pub upgrade {name}",
    "Hex": "mix deps.update {name}",
    "GitHub Actions": "use {name}@v{to} (or pin its commit) in the workflow",
}


def _parts(version: str) -> list[int]:
    nums = [int(p) for p in re.findall(r"\d+", str(version).lstrip("v"))[:3]]
    return nums + [0] * (3 - len(nums))


def bump(current: str, to: str) -> str:
    """"major", "minor" or "patch": how far the upgrade moves (0.x minors count as major, as semver treats them)."""
    a, b = _parts(current), _parts(to)
    if b[0] != a[0] or (a[0] == 0 and b[1] != a[1]):
        return "major"
    return "minor" if b[1] != a[1] else "patch"


def plan(finding: dict) -> dict | None:
    """{"to", "bump", "command"} for a finding with a fixed version; None when no fix exists yet."""
    to = finding.get("fixed")
    if not to or finding.get("malware"):
        return None
    eco, name = finding.get("ecosystem") or "", finding.get("package") or ""
    template = COMMANDS.get(eco, "upgrade {name} to {to}")
    return {"to": to, "bump": bump(finding.get("version") or "0", to), "command": template.format(name=name, to=str(to).lstrip("v"))}
