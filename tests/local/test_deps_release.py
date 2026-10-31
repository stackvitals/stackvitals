from datetime import datetime, timezone

from stackvitals.deps import release

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


class Registry:
    def __init__(self, docs):
        self.docs, self.asked = docs, []

    def get(self, url):
        self.asked.append(url)
        doc = next((d for k, d in self.docs.items() if url.endswith(k)), None)

        class R:
            status_code = 200 if doc is not None else 404

            def json(self):
                return doc
        return R()


def test_a_compromised_looking_npm_release_gets_every_sign():
    reg = Registry({"/axios/1.14.0": {"scripts": {"test": "x"}, "dependencies": {"form-data": "1"}, "dist": {"attestations": {"url": "u"}}},
                    "/axios/1.14.1": {"scripts": {"postinstall": "node setup.js"}, "dependencies": {"form-data": "1", "plain-crypto-js": "4"},
                                      "dist": {}},
                    "/versions/1.14.1": {"publishedAt": "2026-10-23T09:00:00Z"}})
    signs = release.release_signs(reg, "npm", "axios", ["1.14.0"], ["1.14.1"], NOW)
    text = " ".join(signs)
    assert "Released 3 hours ago" in text and "postinstall" in text and "plain-crypto-js" in text and "provenance" in text


def test_a_normal_upgrade_a_downgrade_and_other_ecosystems_get_nothing():
    reg = Registry({"/lib/1.0.0": {"scripts": {"postinstall": "x"}, "dependencies": {"a": "1"}, "dist": {"attestations": {}}},
                    "/lib/1.1.0": {"scripts": {"postinstall": "x"}, "dependencies": {"a": "1"}, "dist": {"attestations": {}}},
                    "/versions/1.1.0": {"publishedAt": "2026-09-01T00:00:00Z"}})
    assert release.release_signs(reg, "npm", "lib", ["1.0.0"], ["1.1.0"], NOW) == []
    assert release.release_signs(reg, "npm", "lib", ["1.1.0"], ["1.0.0"], NOW) == []
    assert release.release_signs(reg, "cargo", "lib", ["1"], ["2"], NOW) == [] and not reg.asked[3:]


def test_pypi_new_dependencies_and_lost_provenance_are_signs():
    reg = Registry({"/pypi/litellm/1.106.0/json": {"info": {"requires_dist": ["httpx>=0.23", "rich; extra == 'cli'"]},
                                                   "urls": [{"filename": "a.whl", "upload_time_iso_8601": "2026-10-01T00:00:00Z"}]},
                    "/pypi/litellm/1.107.0/json": {"info": {"requires_dist": ["httpx>=0.23", "evil-helper"]},
                                                   "urls": [{"filename": "b.whl", "upload_time_iso_8601": "2026-10-23T11:00:00Z"}]},
                    "/litellm/1.106.0/a.whl/provenance": {"ok": True}})
    signs = release.release_signs(reg, "pypi", "litellm", ["1.106.0"], ["1.107.0"], NOW)
    assert any("1 hour ago" in s for s in signs) and any("evil-helper" in s for s in signs) and any("provenance" in s for s in signs)


def test_guarddog_findings_make_a_package_look_first_and_only_when_switched_on(tmp_path, monkeypatch):
    import json
    from stackvitals.deps import action, guarddog
    calls = []
    monkeypatch.setattr(guarddog, "scan", lambda eco, name, v, timeout=180: calls.append((eco, name, v)) or ["npm-install-script", "npm-exfiltrate-sensitive-data"])
    head = json.dumps({"lockfileVersion": 3, "packages": {"": {}, "node_modules/evil": {"version": "1.0.1"}}})
    base = json.dumps({"lockfileVersion": 3, "packages": {"": {}, "node_modules/evil": {"version": "1.0.0"}}})

    class API:
        def __init__(self, *a, **k):
            pass

        def _get(self, path, params=None):
            return [{"filename": "package-lock.json", "status": "modified"}] if path.endswith("/files") else []

        def file(self, path, ref):
            return (head if ref == "h" else base).encode()
    event = tmp_path / "e.json"
    event.write_text(json.dumps({"pull_request": {"number": 1, "base": {"sha": "b"}, "head": {"sha": "h", "repo": {"full_name": "o/r"}}}}))
    env = {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_EVENT_PATH": str(event), "GITHUB_REPOSITORY": "o/r", "GITHUB_TOKEN": "t"}
    off = action.run_deps_action(env, make_api=API, evidence=None, registry=Registry({}))
    on = action.run_deps_action(env, make_api=API, evidence=None, registry=Registry({}), deep=True)
    assert off["monitor"] == 0 and on["monitor"] == 1 and calls == [("npm", "evil", "1.0.1")]


def test_release_age_alone_is_a_note_and_a_stronger_sign_makes_it_a_look(tmp_path, monkeypatch):
    import json
    from stackvitals.deps import action
    head = json.dumps({"lockfileVersion": 3, "packages": {"": {}, "node_modules/lib": {"version": "1.0.1"}}})
    base = json.dumps({"lockfileVersion": 3, "packages": {"": {}, "node_modules/lib": {"version": "1.0.0"}}})

    class API:
        def __init__(self, *a, **k):
            pass

        def _get(self, path, params=None):
            return [{"filename": "package-lock.json", "status": "modified"}] if path.endswith("/files") else []

        def file(self, path, ref):
            return (head if ref == "h" else base).encode()
    event = tmp_path / "e.json"
    event.write_text(json.dumps({"pull_request": {"number": 1, "base": {"sha": "b"}, "head": {"sha": "h", "repo": {"full_name": "o/r"}}}}))
    env = {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_EVENT_PATH": str(event), "GITHUB_REPOSITORY": "o/r", "GITHUB_TOKEN": "t",
           "GITHUB_STEP_SUMMARY": str(tmp_path / "s.md")}
    monkeypatch.setattr(action.release, "release_signs", lambda *a: ["Released 3 hours ago: x."])
    assert action.run_deps_action(env, make_api=API, evidence=None, registry=Registry({}))["monitor"] == 0
    assert "Released 3 hours ago" in (tmp_path / "s.md").read_text(encoding="utf-8")
    monkeypatch.setattr(action.release, "release_signs", lambda *a: ["Released 3 hours ago: x.", "Adds an install script (postinstall)."])
    assert action.run_deps_action(env, make_api=API, evidence=None, registry=Registry({}))["monitor"] == 1
