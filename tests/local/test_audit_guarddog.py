"""Pre-launch audit: a package name from a pull request must never be read by GuardDog as an option, path or URL."""
from stackvitals.deps import guarddog


def _capture(monkeypatch):
    seen = []

    class Done:
        stdout = b'{"results": {"npm-install-script": [{"x": 1}], "clean": []}}'
    monkeypatch.setattr(guarddog.subprocess, "run", lambda args, **k: seen.append(args) or Done())
    return seen


def test_options_come_first_and_the_name_follows_a_double_dash(monkeypatch):
    seen = _capture(monkeypatch)
    assert guarddog.scan("npm", "@scope/left-pad", "1.0.0") == ["npm-install-script"]
    args = seen[0]
    assert args[-2:] == ["--", "@scope/left-pad"] and "--version=1.0.0" in args
    assert args.index("--version=1.0.0") < args.index("--")


def test_names_that_look_like_options_paths_or_urls_are_refused(monkeypatch):
    seen = _capture(monkeypatch)
    for name in ("--exit-non-zero-on-finding", "-v", "../../etc", "https://x.example/p.tgz", "s3://b/k", "", "a b"):
        assert guarddog.scan("pypi", name, "1.0") is None, name
    assert guarddog.scan("pypi", "requests", "--help") is None
    assert not seen
    assert guarddog.scan("pypi", "zope.interface", "6.0") is not None and guarddog.scan("pypi", "my_pkg-2", "1") is not None
