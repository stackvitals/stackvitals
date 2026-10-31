"""One list of settings: it covers every default the parser knows (and nothing else), the reference page is generated from
it, unknown sections and keys are named instead of silently ignored, and [automation] switches beat the workflow inputs."""
from pathlib import Path

from stackvitals.core import config, schema

ROOT = Path(__file__).resolve().parents[2]


def _leaves(node, prefix=""):
    for key, value in node.items():
        path = f"{prefix}{key}"
        if path in ("ci.mute", "identity.aliases", "identity.teams", "investment.labels", "services", "rules") or not isinstance(value, dict):
            yield path
        else:
            yield from _leaves(value, path + ".")


def test_the_list_covers_every_default_and_nothing_else():
    assert set(_leaves(config.DEFAULTS)) == set(schema.BY_KEY)
    for item in schema.to_json():
        assert item["help"] and item["module"] and "default" in item


def test_the_reference_page_is_generated_from_the_list():
    assert (ROOT / "docs" / "settings.md").read_text(encoding="utf-8") == schema.markdown()


def test_unknown_sections_and_keys_are_named():
    _cfg, notes = config.parse('[flow]\nwindow = 30\n[ci]\nfoo = 1\n[ci.quarantine]\nsometimes = ["a"]\n')
    text = " ".join(notes)
    assert "[flow]" in text and "ci.foo" in text and "ci.quarantine.sometimes" in text


def test_automation_switches_are_read_and_left_unset_by_default():
    cfg, notes = config.parse("[automation]\nissues = true\npr_comments = false\nlabel_stuck = \"yes\"\n")
    assert cfg["automation"]["issues"] is True and cfg["automation"]["pr_comments"] is False
    assert cfg["automation"]["rerun_flaky"] is None and cfg["automation"]["label_stuck"] is None
    assert any("automation.label_stuck" in n for n in notes)
    # Off until turned on (user decision, 2026-10-24); fix requests open issues, so they are too.
    team = {"review_requests", "size_labels", "docs_label", "fix_requests", "fix_by_copilot"}
    auto = config.parse("")[0]["automation"]
    assert all(v is None for k, v in auto.items() if k not in team) and all(auto[k] is False for k in team)


def test_the_settings_file_beats_the_workflow_input():
    from argparse import Namespace

    from stackvitals.ci.cli import switches
    args = Namespace(pr_comments="true", rerun_flaky="false", quarantine="false", issues="false", mention_owners="false",
                     preflight_comments="false", deps_comments="false", label_stuck="true")
    cfg = config.parse("[automation]\npr_comments = false\nissues = true\n")[0]
    got = switches(args, cfg)
    assert got["pr_comments"] is False and got["issues"] is True and got["label_stuck"] is True
    assert got["rerun_flaky"] is False and got["assign_owners"] is False
