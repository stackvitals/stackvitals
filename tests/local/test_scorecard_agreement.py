"""Fixes from the Scorecard side-by-side: what counts as a binary and a fuzzer follows Scorecard's evidence, and pinning
covers loose pip and npm installs and Dockerfile base images by tag."""
from stackvitals.security import repo_checks, workflows


def test_binaries_and_fuzzers_as_scorecard_counts_them():
    t = repo_checks.tree_facts(["data/model.bin", "dist/tool.whl", "tests/fuzz/compare.js", "fuzz/fuzz_targets/parse.rs",
                                "src/png_fuzzer.cc", ".clusterfuzzlite/build.sh"])
    assert t["binaries"] == ["dist/tool.whl"]
    assert t["fuzzing"] == [".clusterfuzzlite/build.sh", "fuzz/fuzz_targets/parse.rs", "src/png_fuzzer.cc"]
    go_rust = repo_checks.tree_facts(["go/storage/treefuzz_test.go", "runtime/fuzz/mkvs_node.rs", "tests/fuzz/compare.js"])
    assert go_rust["fuzzing"] == ["go/storage/treefuzz_test.go", "runtime/fuzz/mkvs_node.rs"]


def test_loose_installs_and_unpinned_base_images():
    wf = ("on: push\npermissions:\n  contents: read\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
          "      - run: pip install black\n      - run: pip install -r requirements.txt\n      - run: pip install requests==2.32.0\n"
          "      - run: npm install -g typescript\n      - run: npm i -g pnpm@9.1.0\n")
    details = [f["detail"] for f in workflows.check(".github/workflows/x.yml", wf)]
    assert details == ["pip install black", "npm install -g typescript"]
    df = "FROM golang:1.22 AS build\nFROM build AS test\nFROM gcr.io/distroless/base@sha256:abc\nFROM scratch\n"
    assert [f["detail"] for f in workflows.dockerfile("Dockerfile", df)] == ["FROM golang:1.22"]


def test_branch_tiers_from_the_public_summary_without_admin():
    summary = {"protected": True, "protection": {"enabled": True, "required_status_checks": {"contexts": ["ci"], "checks": [], "enforcement_level": "non_admins"}}}
    got = repo_checks.branch_tiers(None, None, summary)
    assert [t["state"] for t in got["tiers"]] == ["met", "unknown", "met", "unknown", "unknown"] and got["level"] == 1
    off = repo_checks.branch_tiers(None, None, {"protected": False, "protection": {"enabled": False, "required_status_checks": {"enforcement_level": "off"}}})
    assert [t["state"] for t in off["tiers"]][:3] == ["unknown", "unknown", "missing"]


def test_extensionless_executables_are_read_for_their_header():
    entries = [{"type": "blob", "mode": "100755", "path": "npm/bin/tool", "size": 4_000_000, "sha": "a"},
               {"type": "blob", "mode": "100755", "path": "scripts/run.sh", "size": 2000, "sha": "b"},
               {"type": "blob", "mode": "100644", "path": "data/blob", "size": 5000, "sha": "c"}]
    assert [e["path"] for e in repo_checks.sniff_candidates(entries)] == ["npm/bin/tool"]
    assert repo_checks.is_executable(b"\x7fELF\x02\x01") and repo_checks.is_executable(b"MZ\x90\x00")
    assert not repo_checks.is_executable(b"#!/usr/bin/env node")
