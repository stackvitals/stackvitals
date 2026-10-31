from stackvitals.deps.imports import imported, scan


def test_the_code_s_imports_are_read_and_tests_and_vendored_code_left_out(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("import yaml, os\nfrom requests.adapters import HTTPAdapter\nfrom . import local\n")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "a.ts").write_text("import axios from 'axios'\nconst x = require('@scope/pkg/sub')\nimport './rel'\nimport fs from 'node:fs'\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("import pytest\n")
    (tmp_path / "node_modules" / "lib").mkdir(parents=True)
    (tmp_path / "node_modules" / "lib" / "i.js").write_text("require('lodash')\n")
    doc = scan(tmp_path)
    assert set(doc["pypi"]) >= {"yaml", "os", "requests.adapters"} and "pytest" not in doc["pypi"]
    assert set(doc["npm"]) == {"axios", "@scope/pkg"}
    assert imported(doc, "PyPI", "PyYAML") is True and imported(doc, "PyPI", "requests") is True
    assert imported(doc, "PyPI", "urllib3") is False and imported(doc, "npm", "lodash") is False
    assert imported(doc, "npm", "@scope/pkg") is True and imported(doc, "Go", "x") is None and imported(None, "npm", "a") is None


def test_rust_crates_used_by_the_code_count_and_hyphens_match_underscores(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.rs").write_text("use serde_json::Value;\nuse std::io;\nextern crate libc;\n"
                                              "use crate::local;\nfn f() { let _ = tokio::spawn(x); }\n")
    (tmp_path / "target" / "debug").mkdir(parents=True)
    (tmp_path / "target" / "debug" / "gen.rs").write_text("use openssl::ssl;\n")
    doc = scan(tmp_path)
    assert {"serde_json", "libc", "tokio"} <= set(doc["crates.io"]) and "crate" not in doc["crates.io"]
    assert "openssl" not in doc["crates.io"] and "std" not in doc["crates.io"]
    assert imported(doc, "crates.io", "serde-json") is True and imported(doc, "crates.io", "openssl") is False


def test_known_renames_unknown_hyphenated_names_and_more_file_kinds(tmp_path):
    (tmp_path / "app.py").write_text("import attrs, git as g, grpc\nimport psycopg2 as pg, OpenSSL\nfrom google.auth import x\n")
    (tmp_path / "App.vue").write_text("<script>import { ref } from 'vue'\n</script>\n")
    (tmp_path / "lib.rs").write_text("use serde_json;\nuse rand as r;\n")
    doc = scan(tmp_path)
    for pkg in ("attrs", "GitPython", "grpcio", "psycopg2-binary", "pyOpenSSL"):
        assert imported(doc, "PyPI", pkg) is True, pkg
    assert imported(doc, "PyPI", "google-cloud-storage") is False  # another google package isn't this one
    assert imported(doc, "PyPI", "some-odd-dist") is None and imported(doc, "PyPI", "urllib3") is False
    assert imported(doc, "npm", "vue") is True and {"serde_json", "rand"} <= set(doc["crates.io"])
    assert imported([], "npm", "x") is None and imported(doc, None, "x") is None
