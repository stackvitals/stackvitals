from stackvitals.deps import runtimes

CYCLES = {"php": [{"cycle": "8.3", "eol": "2027-12-31", "latest": "8.3.36", "latestReleaseDate": "2026-10-21"},
                  {"cycle": "7.4", "eol": "2022-11-28", "latest": "7.4.33"}],
          "nodejs": [{"cycle": "20", "eol": "2026-04-30", "latest": "20.19.5"}, {"cycle": "22", "eol": "2027-04-30", "latest": "22.21.0"}],
          "python": [{"cycle": "3.12", "eol": "2028-10-31", "latest": "3.12.11"}],
          "go": [{"cycle": "1.24", "eol": False, "latest": "1.24.9"}]}


def test_versions_are_read_from_version_files_dockerfiles_workflows_and_go_mod():
    files = {".nvmrc": "v20\n", ".python-version": "3.12.4\n", "Dockerfile": "FROM php:8.3.10-fpm\nRUN x",
             ".github/workflows/ci.yml": "      - uses: actions/setup-node@x\n        with:\n          node-version: '22'\n",
             "go.mod": "module x\n\ngo 1.24.2\n", "package.json": '{"engines": {"node": ">=18"}}', ".tool-versions": "php 7.4.30\n"}
    got = {(f["runtime"], f["version"], f["file"]) for f in runtimes.detect(files)}
    assert all(f["use"] == "runs" for f in runtimes.detect(files))
    assert got == {("node", "20", ".nvmrc"), ("python", "3.12.4", ".python-version"), ("php", "8.3.10", "Dockerfile"),
                   ("node", "22", ".github/workflows/ci.yml"), ("go", "1.24.2", "go.mod"), ("php", "7.4.30", ".tool-versions")}


def test_an_ended_line_and_an_old_patch_are_named_and_a_bare_line_is_just_supported():
    found = [{"runtime": "php", "version": "8.3.10", "file": "Dockerfile"}, {"runtime": "php", "version": "7.4.30", "file": "t"},
             {"runtime": "node", "version": "20", "file": ".nvmrc"}, {"runtime": "node", "version": "22", "file": "ci"},
             {"runtime": "python", "version": "3.9", "file": "x"}]
    by = {(j["runtime"], j["version"]): j for j in runtimes.judge(found, CYCLES, "2026-10-23")}
    assert by[("php", "8.3.10")]["status"] == "behind the newest patch" and by[("php", "8.3.10")]["latest"] == "8.3.36"
    assert by[("php", "7.4.30")]["status"] == "end of life" and by[("node", "20")]["status"] == "end of life"
    assert by[("node", "22")]["status"] == "supported" and by[("python", "3.9")]["status"] == "unknown"


def test_matrix_lists_inline_and_as_blocks_are_read():
    wf = ("    strategy:\n      matrix:\n        php: [8.2, 8.3, '8.4']\n        python:\n          - '3.12'\n          - \"3.13\"\n"
          "        os: [ubuntu-latest]\n")
    got = sorted((f["runtime"], f["version"]) for f in runtimes.detect({".github/workflows/t.yml": wf}))
    assert got == [("php", "8.2"), ("php", "8.3"), ("php", "8.4"), ("python", "3.12"), ("python", "3.13")]
    assert {f["use"] for f in runtimes.detect({".github/workflows/t.yml": wf})} == {"tests"}
