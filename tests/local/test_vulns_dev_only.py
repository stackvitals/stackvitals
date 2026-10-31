"""Development-only packages, read from the lockfiles that record it, so their advisories can wait behind what ships."""
import json

from stackvitals.deps.vulns import dev_only


def test_npm_pipfile_and_pnpm_dev_packages(tmp_path):
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package-lock.json").write_text(json.dumps({"packages": {
        "": {"name": "app"}, "node_modules/jest": {"version": "29.0.0", "dev": True},
        "node_modules/@babel/core": {"version": "7.0.0", "dev": True}, "node_modules/express": {"version": "4.0.0"}}}))
    (tmp_path / "Pipfile.lock").write_text(json.dumps({"default": {"requests": {}}, "develop": {"pytest": {}, "requests": {}}}))
    (tmp_path / "pnpm-lock.yaml").write_text("packages:\n  /vitest@1.0.0:\n    dev: true\n  /react@18.0.0:\n    dev: false\n")
    got = dev_only(tmp_path)
    assert ("web/package-lock.json", "jest") in got and ("web/package-lock.json", "@babel/core") in got
    assert ("web/package-lock.json", "express") not in got
    assert ("Pipfile.lock", "pytest") in got and ("Pipfile.lock", "requests") not in got
    assert ("pnpm-lock.yaml", "vitest") in got and ("pnpm-lock.yaml", "react") not in got
