"""Pre-launch audit: the private data jobs stay in the private repo, the public benchmark copy is skipped without its
token, the crawl's input goes through env, and the GitLab template pins uv."""
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
ROOT = Path(__file__).parents[2]


def _load(rel):
    return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))


def test_daily_and_prospective_run_only_in_the_private_repo():
    for rel, job in ((".github/workflows/daily.yml", "daily"), (".github/workflows/prospective.yml", "score")):
        assert _load(rel)["jobs"][job]["if"] == "github.repository == 'kaushik-yadav/merge-scout'"


def test_the_public_benchmark_copy_comes_after_publishing_and_is_skipped_without_its_token():
    steps = _load(".github/workflows/daily.yml")["jobs"]["daily"]["steps"]
    names = [s.get("name") or "" for s in steps]
    publish = next(i for i, n in enumerate(names) if n.startswith("Publish the review-flow benchmarks"))
    check, copy = names.index("Check for the public benchmark token"), names.index("Copy the CI and shared benchmarks to the public release")
    assert publish < check < copy
    assert steps[copy]["if"] == "always() && steps.public_bench.outputs.set == 'true'" and steps[copy]["continue-on-error"]
    assert 'set=true' in steps[check]["run"] and '[ -n "$PUBLIC_BENCH_TOKEN" ]' in steps[check]["run"]
    run = steps[copy]["run"]
    assert "ci-benchmarks.json shared-benchmarks.json" in run and "-R stackvitals/stackvitals --clobber" in run
    assert "gh release create bench-latest -R stackvitals/stackvitals" in run
    # The secret reaches only these two steps.
    holders = [n for n, s in zip(names, steps) if "PUBLIC_BENCH_TOKEN" in str(s.get("env"))]
    assert holders == [names[check], names[copy]]
    assert "PUBLIC_BENCH_TOKEN" not in str(_load(".github/workflows/daily.yml")["jobs"]["daily"].get("env"))


def test_the_crawl_minutes_input_goes_through_env():
    text = (ROOT / "deploy/crawler/workflows/crawl.yml").read_text(encoding="utf-8")
    assert '--minutes "$CRAWL_MINUTES"' in text and "CRAWL_MINUTES: ${{ inputs.minutes || '40' }}" in text
    assert "run: python -m mergescout.crawl run --minutes \"${{" not in text


def test_the_gitlab_template_pins_uv_and_explains_pinning_the_ref():
    text = (ROOT / "templates/gitlab/stackvitals.yml").read_text(encoding="utf-8")
    script = _load("templates/gitlab/stackvitals.yml")["stackvitals"]["before_script"]
    assert "pip install -q uv==0.10.2" in script
    assert "STACKVITALS_REF to a full commit SHA" in text
