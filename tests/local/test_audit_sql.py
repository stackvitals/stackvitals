"""Pre-launch audit: a remote data branch's manifest names become file and table names, so they must not inject SQL or
write outside the temp folder, and the user's query must not reach files."""
import json

from stackvitals.core import sqlcli


def _api(files: dict[str, bytes]):
    class Api:
        def __init__(self, token, repo, **kw):
            pass

        def file(self, path, ref):
            if path == "summary/manifest.json":
                return json.dumps({"files": {n: {} for n in files}}).encode()
            return files[path.split("/", 1)[1]]
    return Api


def test_bad_manifest_names_are_skipped_and_good_ones_still_query(tmp_path, capsys):
    files = {"prs.jsonl": b'{"n": 1}\n{"n": 2}\n',
             'x" AS SELECT 1; COPY (SELECT 1) TO \'pwn.csv\'; --.jsonl': b'{"a": 1}\n',
             "../../escape.jsonl": b'{"a": 1}\n', "Upper.jsonl": b'{"a": 1}\n', "-opt.jsonl": b'{"a": 1}\n'}
    assert sqlcli.main(["--repo", "o/r", "--json", "select count(*) as n from prs"], make_api=_api(files), tok="t") == 0
    out = capsys.readouterr()
    assert json.loads(out.out) == [{"n": 2}]
    assert out.err.count("Skipped") == 4
    assert not list(tmp_path.rglob("pwn.csv")) and not list(tmp_path.parent.rglob("escape.jsonl"))


def test_the_query_cannot_read_write_or_reenable_files(tmp_path, capsys):
    (tmp_path / "summary").mkdir()
    (tmp_path / "summary" / "prs.jsonl").write_text('{"n": 1}\n', encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("hidden\n", encoding="utf-8")
    lit = str(secret).replace("\\", "/")
    for query in (f"select * from read_csv('{lit}')", f"copy prs to '{tmp_path.as_posix()}/out.csv'",
                  "set enable_external_access = true", "reset enable_external_access",
                  f"attach '{tmp_path.as_posix()}/x.db'"):
        assert sqlcli.main(["--dir", str(tmp_path), query]) == 1, query
        assert "SQL error" in capsys.readouterr().err
    assert not (tmp_path / "out.csv").exists() and not (tmp_path / "x.db").exists()
    assert sqlcli.main(["--dir", str(tmp_path), "--json", "select count(*) as n from prs"]) == 0
    assert json.loads(capsys.readouterr().out) == [{"n": 1}]


def test_identifiers_are_quoted():
    assert sqlcli._ident('a"b') == '"a""b"'
