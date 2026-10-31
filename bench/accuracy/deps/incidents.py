"""Release signs and the malware lane on known npm attacks: how soon GitHub's malware advisory followed the bad release
(npm keeps every version's publish time, even for removed versions), and which release sign the attack would have set
off, where the advisory says what the bad version changed. The bad versions' own package files are gone from npm, so
the signs are judged from the advisory's own words, quoted in the result, not from the package.

    GH_TOKEN=... python bench/accuracy/deps/incidents.py     # writes incidents-results.json beside this script
"""
import json
import os
from datetime import datetime
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
# package, bad version, the advisory, and what the advisory itself says the bad version changed.
INCIDENTS = [
    ("event-stream", "3.3.6", "GHSA-mh6f-8j2x-4483", "new dependency",
     "A malicious actor added this package as a dependency to the NPM event-stream package in version 3.3.6"),
    ("ua-parser-js", "0.7.29", "GHSA-pjwm-rvh2-c87w", None, None),
    ("eslint-config-prettier", "8.10.1", "GHSA-f29h-pxvx-f335", "install script",
     "Installing an affected package executes an install.js file"),
    ("nx", "21.5.0", "GHSA-cxm3-wv7p-598c", None, None),
    ("chalk", "5.6.1", "GHSA-2v46-p5h4-248w", "code only",
     "a browser-based interceptor that hijacks network traffic and application APIs"),
    ("debug", "4.4.2", "GHSA-4x49-vf9v-38px", "code only",
     "a browser-based interceptor that hijacks network traffic and application APIs"),
    ("@ctrl/tinycolor", "4.1.1", "GHSA-qjqf-7j6f-82c4", None, None),
]
# What StackVitals' release signs look at: an install script or new dependencies make it "look first"; a release
# under 48 hours old is only a note.
SIGNS = {"new dependency": "look first (new dependencies)", "install script": "look first (new install script)",
         "code only": "a note only (released under 48 hours ago); no sign looks at code"}


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main() -> int:
    gh = httpx.Client(timeout=30, headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                                           "Accept": "application/vnd.github+json"})
    npm = httpx.Client(timeout=30, headers={"User-Agent": "stackvitals-bench"})
    rows = []
    for name, version, ghsa, change, quote in INCIDENTS:
        published = (npm.get(f"https://registry.npmjs.org/{name.replace('/', '%2F')}").json().get("time") or {}).get(version)
        adv = gh.get(f"https://api.github.com/advisories/{ghsa}").json()
        listed = adv.get("published_at")
        hours = round((_t(listed) - _t(published)).total_seconds() / 3600, 1) if published and listed else None
        rows.append({"package": name, "version": version, "advisory": ghsa, "type": adv.get("type"),
                     "released": published, "advisory_published": listed, "hours_to_advisory": hours,
                     "what_changed": change or "not stated in the advisory", "advisory_says": quote,
                     "release_sign": SIGNS.get(change, "can't tell from the advisory")})
    out = {"incidents": rows, "read": datetime.now().strftime("%Y-%m-%d"),
           "note": "Release signs judged from the advisory's words; the bad versions' package files are gone from npm."}
    (HERE / "incidents-results.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
