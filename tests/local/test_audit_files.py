import importlib.util
import random
import re
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('audit', Path(__file__).resolve().parents[2] / 'bench' / 'accuracy' / 'audit.py')


@pytest.mark.skipif(not (Path(__file__).resolve().parents[2] / "bench" / "accuracy" / ".work" / "flaky").exists(),
                    reason="needs the labelled evidence (bench/accuracy/.work), which isn't in the repo")
def test_answers_round_trip_and_problems_are_named(tmp_path, monkeypatch):
    a = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(a)
    monkeypatch.setattr(a, "OUT", tmp_path / "audit")
    a.make(3)
    text = (tmp_path / "audit" / "team-review-person-B.txt").read_text(encoding="utf-8")
    # Options and questions never name a model or use jargon.
    assert not re.search(r"(?i)flak|claude|gemini|labeller", "".join(a.OPTIONS["ci"] + a.OPTIONS["comment"]) + a.HEADER)
    rng = random.Random(1)
    blocks = re.split(r"(?m)^(Answer \([^)]*\): )\n", text)
    filled = blocks[0]
    for i in range(1, len(blocks), 2):
        head, b, n = blocks[i], blocks[i + 1], i // 2
        ans = "" if n == 3 else ("A, C" if n == 5 else rng.choice("ABCDE"))
        filled += f"{head}{ans}\n" + b.replace("Note (optional): \n", "Note (optional): because the log says so\n", 1)
    filled = filled.replace("Your role (for example backend developer, maintainer, SRE):", "Your role (for example backend developer, maintainer, SRE): maintainer", 1)
    back = tmp_path / "back"
    back.mkdir()
    (back / "team-review-person-B.txt").write_text(filled, encoding="utf-8")
    out = a.read(back)
    assert out["answers"] == (len(blocks) - 1) // 2 - 1
    assert any("no answer" in p for p in out["problems"])
    rows = (tmp_path / "audit" / "answers.csv").read_text(encoding="utf-8")
    assert "maintainer" in rows and "because the log says so" in rows
