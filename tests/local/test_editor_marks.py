import json
import shutil
import subprocess
from pathlib import Path

import pytest

MARKS = Path(__file__).resolve().parents[2] / "src" / "stackvitals" / "editors" / "vscode" / "marks.js"
# The installed folder carries the extension's own version.
OURS = "stackvitals.stackvitals-flaky-tests-" + json.loads((MARKS.parent / "package.json").read_text())["version"]
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="needs node")


def marks(text: str, rel: str, tests: list[dict]) -> list[dict]:
    script = ("const m = require(process.argv[1]); const a = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
              "console.log(JSON.stringify(m.findMarks(a.text, a.rel, a.tests).map(x => ({line: x.line, col: x.col,"
              " length: x.length, id: x.test.id, says: m.describe(x.test)}))));")
    out = subprocess.run(["node", "-e", script, str(MARKS)], input=json.dumps({"text": text, "rel": rel, "tests": tests}),
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def flaky(tid: str, **extra) -> dict:
    return {"id": tid, "state": "flaky", "flake_events": 3, "runs": 40, "last_flake": "2026-10-20T10:00:00Z", **extra}


def test_python_test_found_by_module_and_name():
    text = "import x\n\nclass TestApi:\n    def test_login(self):\n        pass\n\ndef test_logout():\n    pass\n"
    got = marks(text, "tests/test_api.py", [flaky("tests.test_api.TestApi::test_login[chrome]"),
                                           flaky("tests.test_other::test_logout")])
    assert [(g["line"], g["col"], g["id"]) for g in got] == [(3, 8, "tests.test_api.TestApi::test_login[chrome]")]
    assert got[0]["length"] == len("test_login")


def test_go_subtest_marks_its_parent_function():
    text = "package foo\n\nfunc TestParse(t *testing.T) {\n}\n\nfunc (s *Suite) TestRun() {}\n"
    got = marks(text, "internal/foo/parse_test.go",
                [flaky("github.com/o/r/internal/foo::TestParse/empty"), flaky("github.com/o/r/internal/foo::TestRun")])
    assert [(g["line"], g["id"].rsplit("::", 1)[1]) for g in got] == [(2, "TestParse/empty"), (5, "TestRun")]


def test_jest_title_matches_the_end_of_the_full_name():
    text = "describe('cart', () => {\n  it(\"adds an item\", () => {});\n  it('adds', () => {});\n});\n"
    got = marks(text, "src/cart.test.ts", [flaky("src/cart.test.ts::cart adds an item")])
    assert [(g["line"], g["col"]) for g in got] == [(1, 6)]


def test_java_and_csharp_methods():
    java = "class FooTest {\n  @Test\n  void savesUser() {}\n}\n"
    cs = "public class FooTests {\n  [Fact]\n  public async Task Saves_user() {}\n}\n"
    assert marks(java, "src/test/java/FooTest.java", [flaky("com.acme.FooTest::savesUser")])[0]["line"] == 2
    assert marks(cs, "tests/FooTests.cs", [flaky("Acme.FooTests.Saves_user")])[0]["line"] == 2


def test_same_name_in_another_file_is_not_marked():
    text = "def test_login():\n    pass\n"
    assert marks(text, "tests/test_web.py", [flaky("tests.test_api::test_login")]) == []


def test_healthy_tests_are_not_marked_and_broken_ones_are():
    text = "def test_a():\n    pass\ndef test_b():\n    pass\n"
    got = marks(text, "tests/test_x.py", [{"id": "tests.test_x::test_a", "state": "healthy"},
                                         {"id": "tests.test_x::test_b", "state": "broken", "failures": 9, "runs": 9}])
    assert [g["id"] for g in got] == ["tests.test_x::test_b"]
    assert "failed in 9 of the last 9 runs" in got[0]["says"]


def test_message_names_the_evidence():
    got = marks("def test_a():\n    pass\n", "tests/test_x.py",
                [flaky("tests.test_x::test_a", flake="timing", message="TimeoutError: waited 5s")])
    says = got[0]["says"]
    assert "3 times in 40 runs" in says and "2026-10-20" in says
    assert "timing" in says and "TimeoutError: waited 5s" in says


def test_untrusted_ids_never_break_matching():
    text = "def test_a():\n    pass\n"
    weird = [{"id": "(((", "state": "flaky"}, {"id": "", "state": "flaky"}, {"id": None, "state": "flaky"}, {"state": "flaky"},
             flaky("tests.test_x::test_a")]
    assert [g["id"] for g in marks(text, "tests/test_x.py", weird)] == ["tests.test_x::test_a"]


def test_install_replaces_only_our_older_copies(tmp_path):
    from stackvitals.editors import install
    (tmp_path / "stackvitals.stackvitals-flaky-tests-0.0.1").mkdir()
    (tmp_path / "someone.else-1.0.0").mkdir()
    dest = install(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["someone.else-1.0.0", OURS]
    assert sorted(p.name for p in dest.iterdir()) == ["extension.js", "marks.js", "package.json"]


def test_cli_installs_into_the_given_folder(tmp_path, capsys):
    from stackvitals.cli import main
    assert main(["editor", "cursor", "--dir", str(tmp_path)]) == 0
    assert (tmp_path / OURS / "extension.js").exists()
    assert "Reload the editor" in capsys.readouterr().out


def test_a_parametrised_id_with_dots_still_finds_its_test():
    got = marks("def test_rate():\n    pass\n", "tests/test_x.py", [flaky("tests.test_x::test_rate[1.5]")])
    assert [g["line"] for g in got] == [0]
