import csv
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench" / "accuracy"))

import labeller  # noqa: E402
from labeller import Cache, Gemini, QuotaStop, compare, prompt_text, run, write_csv  # noqa: E402


class Fake:
    """Answers every item with a fixed label; counts calls; can raise on a given call."""

    def __init__(self, label=None, fail_on=None):
        self.calls, self.sent, self.fail_on = 0, [], fail_on
        self.label = label or {"cause": "network", "caused_by_change": "no", "own_failure": "yes",
                               "confidence": "high", "evidence": "registry 503"}

    def generate(self, system, text, schema):
        self.calls += 1
        if self.fail_on == self.calls:
            raise QuotaStop("429")
        ids = [json.loads(line)["id"] for line in text.splitlines() if line.startswith("{")]
        self.sent.extend(ids)
        return [{"id": i, **self.label} for i in ids], {"in": 100 * len(ids), "out": 20 * len(ids)}


def _items(n, start=1):
    return [{"id": i, "repo": "o/r", "log": "x" * 400} for i in range(start, start + n)]


def _cache(tmp_path):
    return Cache(tmp_path / "cache", "flaky", "m", "hash")


def test_cached_items_are_never_sent_again(tmp_path):
    cache, fake, items = _cache(tmp_path), Fake(), _items(12)
    for i in items[:3]:
        cache.put(i["id"], {"cause": "test"})
    out = run("flaky", items, fake, cache, dry=False, sleep=lambda s: None)
    assert fake.sent == [i["id"] for i in items[3:]] and fake.calls == 1
    assert out["cached"] == 3 and out["sent"] == 9


def test_dry_run_sends_nothing_and_estimates(tmp_path):
    fake = Fake()
    out = run("flaky", _items(25), fake, _cache(tmp_path), dry=True)
    assert fake.calls == 0 and out["estimate"] > 0 and out["batches"] == 3


def test_call_cap_stops_and_keeps_finished_work(tmp_path):
    cache, fake = _cache(tmp_path), Fake()
    out = run("flaky", _items(25), fake, cache, dry=False, max_calls=2, sleep=lambda s: None)
    assert fake.calls == 2 and out["stopped"] == "call cap" and len(cache.all()) == 20


def test_token_cap_stops_before_it_is_passed(tmp_path):
    fake = Fake()
    out = run("flaky", _items(25), fake, _cache(tmp_path), dry=False, max_tokens=500, sleep=lambda s: None)
    assert fake.calls == 0 and out["stopped"] == "token cap"


def test_quota_error_stops_the_run_and_keeps_what_finished(tmp_path):
    cache, fake = _cache(tmp_path), Fake(fail_on=2)
    out = run("flaky", _items(25), fake, cache, dry=False, sleep=lambda s: None)
    assert out["stopped"] == "quota" and len(cache.all()) == 10


def test_labels_outside_the_codebook_are_not_cached(tmp_path):
    cache = _cache(tmp_path)
    bad = Fake(label={"cause": "banana", "caused_by_change": "no", "own_failure": "yes", "confidence": "high"})
    out = run("flaky", _items(4), bad, cache, dry=False, sleep=lambda s: None)
    assert out["invalid"] == 4 and cache.all() == {}


def test_csv_keeps_labels_but_never_the_quoted_evidence(tmp_path):
    cache = _cache(tmp_path)
    run("flaky", _items(3), Fake(), cache, dry=False, sleep=lambda s: None)
    out = tmp_path / "labels-gemini.csv"
    write_csv("flaky", cache, out)
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [r["cause"] for r in rows] == ["network"] * 3
    assert "evidence" not in rows[0] and "registry 503" not in out.read_text(encoding="utf-8")


def test_long_logs_keep_their_start_and_end():
    item = {"id": 1, "log": "START" + "m" * 20_000 + "END"}
    text = prompt_text([item], max_chars=2_000)
    sent = json.loads(text.splitlines()[-1])
    assert sent["log"].startswith("START") and sent["log"].endswith("END") and len(sent["log"]) < 2_100


def test_compare_reports_agreement_and_kappa():
    first = {1: {"cause": "a"}, 2: {"cause": "a"}, 3: {"cause": "b"}, 4: {"cause": "b"}}
    second = {1: {"cause": "a"}, 2: {"cause": "b"}, 3: {"cause": "b"}, 4: {"cause": "b"}, 9: {"cause": "a"}}
    out = compare(first, second, ["cause"])
    assert out["cause"]["n"] == 4 and out["cause"]["agree"] == 0.75
    assert out["cause"]["kappa"] == 0.5 and out["cause"]["disagree"] == [2]


def test_client_sends_the_key_in_a_header_and_reads_usage():
    seen = {}

    def handler(request):
        seen["url"], seen["key"] = str(request.url), request.headers.get("x-goog-api-key")
        body = {"candidates": [{"content": {"parts": [{"text": json.dumps([{"id": 1, "cause": "test"}])}]}}],
                "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 15, "thoughtsTokenCount": 5}}
        return httpx.Response(200, json=body)

    g = Gemini("SECRET", "gemini-x", client=httpx.Client(transport=httpx.MockTransport(handler)))
    labels, usage = g.generate("codebook", '{"id": 1}', {"type": "ARRAY"})
    assert labels == [{"id": 1, "cause": "test"}] and usage == {"in": 120, "out": 20}
    assert seen["key"] == "SECRET" and "SECRET" not in seen["url"] and "gemini-x:generateContent" in seen["url"]


def test_client_turns_a_rate_limit_into_a_stop():
    g = Gemini("k", "m", client=httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}}))))
    with pytest.raises(QuotaStop):
        g.generate("s", "t", {})


def test_usage_log_never_holds_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "SECRET-KEY-123")
    log = tmp_path / "usage.jsonl"
    labeller.log_usage(log, "flaky", "m", {"calls": 1, "tokens_in": 10, "tokens_out": 2, "stopped": None})
    assert "SECRET" not in log.read_text(encoding="utf-8") and json.loads(log.read_text())["calls"] == 1
