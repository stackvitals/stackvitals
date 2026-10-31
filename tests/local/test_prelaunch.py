"""The pre-launch runner's pure helpers: links and anchors, command lines, secrets, pins, CSP, schema."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("prelaunch", ROOT / "scripts" / "prelaunch.py")
pl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pl)


def test_anchors_follow_github_and_ignore_headings_in_code():
    md = "# Release signs (`incidents.py`)\n## Q&A: why?\n## Q&A: why?\n```sh\n# not a heading\n```\n<a name=\"custom\"></a>\n"
    got = pl.anchors(md)
    assert {"release-signs-incidentspy", "qa-why", "qa-why-1", "custom"} <= got
    assert "not-a-heading" not in got


def test_broken_links_finds_missing_files_and_anchors_only(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "b.md").write_text("# Real heading\n", encoding="utf-8")
    a = tmp_path / "docs" / "a.md"
    a.write_text("[ok](b.md#real-heading) [web](https://x.io/y#z) [self](#top)\n# Top\n[gone](c.md) [bad](b.md#nope)\n"
                 "`[code](missing.md)`\n```\n[fenced](missing.md)\n```\n", encoding="utf-8")
    assert pl.broken_links(tmp_path, [a]) == ["docs/a.md -> c.md", "docs/a.md -> b.md#nope"]


def test_command_lines_reads_code_only_and_cuts_at_placeholders():
    md = ("Run `stackvitals ci report owner/repo --days 14`.\n\nstackvitals prose is ignored\n\n"
          "```sh\npip install stackvitals\nstackvitals flow triage ${repo} --pr 1\nstackvitals ci burn-in --times 5 -- pytest\n```\n")
    assert pl.command_lines(md, markdown=True) == [["flow", "triage"], ["ci", "burn-in", "--times", "5"],
                                                   ["ci", "report", "owner/repo", "--days", "14"]]


def test_command_lines_in_source_skips_comments_and_package_names():
    ts = ('// the stackvitals ci commands it runs\nconst a = `claude mcp add stackvitals -- uvx stackvitals serve --tools all`;\n'
          'const b = "pip install stackvitals first";\nconst c = "x\\nstackvitals delivery owner/repo --gitlab";\n'
          'const u = "https://example.com"; // stackvitals unexpanded\n')
    assert pl.command_lines(ts) == [["serve", "--tools", "all"], ["delivery", "owner/repo", "--gitlab"]]


TREE = {"flags": {"-h", "--help"}, "subs": {
    "ci": {"flags": {"-h"}, "subs": {"report": {"flags": {"-h", "--days"}, "subs": {}}}},
    "serve": {"flags": {"-h", "--tools"}, "subs": {}}}}


def test_check_command_names_the_missing_command_or_flag():
    assert pl.check_command(["ci", "report", "o/r", "--days=14"], TREE) is None
    assert pl.check_command(["serve", "--tools", "all"], TREE) is None
    assert pl.check_command(["ci", "report", "--weeks", "2"], TREE) == "`stackvitals ci report` has no --weeks"
    assert pl.check_command(["quarantine"], TREE) == "`stackvitals` has no command `quarantine`"


def test_check_command_asks_about_commands_hidden_from_help():
    asked = []

    def discover(path):
        asked.append(path)
        return {"flags": {"--sha"}, "subs": {}} if path == ["ci", "upload"] else None
    assert pl.check_command(["ci", "upload", "--sha", "abc"], TREE, discover) is None
    assert pl.check_command(["ci", "nope"], TREE, discover) == "`stackvitals ci` has no command `nope`"
    assert asked == [["ci", "upload"], ["ci", "nope"]]


def test_parse_help_reads_subcommands_and_flags_but_not_choices():
    top = ("usage: stackvitals [-h]\n                   {ci,flow,deps} ...\n\npositional arguments:\n  {ci,flow,deps}\n"
           "    ci   CI health (`stackvitals ci report owner/repo --html`)\n\noptions:\n  -h, --help  show this help\n")
    assert pl.parse_help(top) == (["ci", "flow", "deps"], {"-h", "--help"})
    leaf = ("usage: stackvitals editor [-h] [--days DAYS] {vscode,cursor}\n\noptions:\n  -h, --help   show\n"
            "  --days DAYS  how many (see --other)\n  -n N, --count N\n")
    assert pl.parse_help(leaf) == ([], {"-h", "--help", "--days", "-n", "--count"})


def test_secret_scan_flags_real_shapes_and_allows_listed_fakes():
    key = "AKIA" + "IOSFODNN7EXAMPLE"
    gh = "ghp_" + "a1B2" * 9
    pem = "-----BEGIN OPENSSH " + "PRIVATE KEY-----"
    text = f"aws = '{key}'\ntoken = '{gh}'\n{pem}\n"
    hits = pl.find_secrets("src/x.py", text, allow=[])
    assert [h.split(": ")[1].rsplit(" ", 1)[0] for h in hits] == ["GitHub token", "AWS key", "Private key"]
    allow = [("tests/*.py", key, "AWS's documented example")]
    assert len(pl.find_secrets("tests/t.py", text, allow=allow)) == 2
    assert len(pl.find_secrets("src/x.py", text, allow=allow)) == 3
    assert pl.find_secrets("a.py", "sk-short and ghp_tooShort", allow=[]) == []


def test_private_files_by_name_and_place():
    assert pl.is_private("CLAUDE.md") and pl.is_private("web/CLAUDE.md") and pl.is_private("plans/phase-1.md")
    assert pl.is_private("agent_analysis.md") and pl.is_private("updates.md") and pl.is_private(".env")
    assert not pl.is_private("src/stackvitals/core/agent_ledger.py") and not pl.is_private(".env.example")
    assert not pl.is_private("docs/plans/x.md") and not pl.is_private("bench/updates.md")


def test_loose_uses_allows_shas_local_actions_and_our_own_ref():
    yml = ("steps:\n  - uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5.1.0\n  - uses: ./local\n"
           "  - uses: stackvitals/stackvitals@v0\n  - uses: actions/cache@v4\n  - {uses: 'o/a@main', with: {}}\n"
           "  - uses: docker://alpine@sha256:" + "a" * 64 + "\n")
    assert pl.loose_uses(yml, "stackvitals/stackvitals@v0") == ["actions/cache@v4", "o/a@main"]


def test_csp_needs_self_scripts_and_no_inline_script():
    good = ("<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'self'; script-src 'self'; object-src 'none'\">"
            "<script type=\"module\" src=\"app/main.js\"></script>")
    assert pl.csp_problems(good) == []
    loose = good.replace("script-src 'self'", "script-src 'self' 'unsafe-inline'") + "<script>alert(1)</script>"
    assert pl.csp_problems(loose) == ["script-src is 'self' 'unsafe-inline', not 'self'", "an inline <script> (blocked by the CSP)"]
    assert pl.csp_problems("<html></html>") == ["no Content-Security-Policy meta"]


def test_small_schema_check_covers_refs_required_and_patterns():
    schema = {"type": "object", "required": ["name", "packages"], "$defs": {"pkg": {"type": "object", "required": ["version"],
              "properties": {"version": {"type": "string", "pattern": r"^\d+\.\d+\.\d+$"}}}},
              "properties": {"name": {"type": "string", "maxLength": 5}, "packages": {"type": "array", "items": {"$ref": "#/$defs/pkg"}}}}
    assert pl.validate_schema({"name": "sv", "packages": [{"version": "0.1.0"}]}, schema) == []
    errs = pl.validate_schema({"name": "toolong", "packages": [{"version": "v1"}, {}]}, schema)
    assert errs == ["$.name: length 7 out of range", "$.packages[0].version: doesn't match ^\\d+\\.\\d+\\.\\d+$", "$.packages[1]: missing version"]
