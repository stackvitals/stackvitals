"""Five-minute setup: the workflow starts its own first run when the file is pushed, and a compact copy without comments
fits a prefilled GitHub "new file" link (GitHub fails above about 6,500 characters)."""
from urllib.parse import quote

import yaml

from stackvitals.ci.cli import workflow_template


def test_pushing_the_workflow_file_starts_the_first_run():
    for compact in (False, True):
        on = yaml.safe_load(workflow_template(names=["CI", "Tests"], compact=compact))[True]
        assert ".github/workflows/stackvitals.yml" in on["push"]["paths"] and ".github/stackvitals.toml" in on["push"]["paths"]


def test_init_picks_ci_workflows_like_the_wizard():
    from stackvitals.ci.cli import ci_guess
    flask = ["AI Code Review", "Lock inactive closed issues", "pre-commit", "Publish", "Tests",
             "GitHub Actions security analysis with zizmor"]
    assert ci_guess(flask) == ["pre-commit", "Tests"] and ci_guess(["Nightly", "Docs"]) == ["Nightly", "Docs"]


def test_the_compact_file_has_no_comments_and_fits_a_link():
    full, small = workflow_template(names=["CI"]), workflow_template(names=["CI"], compact=True)
    assert "#" in full and not any(line.lstrip().startswith("#") or " # " in line for line in small.splitlines())
    assert yaml.safe_load(small)["jobs"] == yaml.safe_load(full)["jobs"]
    assert yaml.safe_load(small)["permissions"] == yaml.safe_load(full)["permissions"]
    assert len(quote(small, safe="")) < 4500
