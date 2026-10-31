import yaml

from stackvitals.ci.cli import workflow_template


def test_a_passing_ci_run_starts_no_job_on_a_private_repo_unless_the_variable_says_so():
    job = yaml.safe_load(workflow_template("o/a@v0", ["CI"]))["jobs"]["vitals"]
    cond = " ".join(job["if"].split())
    assert ("github.event_name != 'workflow_run' || !github.event.repository.private || "
            "github.event.workflow_run.conclusion != 'success' || vars.STACKVITALS_EVERY_CI_RUN == 'true'") in cond
    # The variable reaches the action, which warns when the verdict check would wait for the 3-hourly run.
    assert job["steps"][0]["env"]["STACKVITALS_EVERY_CI_RUN"] == "${{ vars.STACKVITALS_EVERY_CI_RUN }}"


def test_trimmed_workflows_keep_the_guard():
    for mods in (["ci"], ["deps"], ["ci", "flow"]):
        job = yaml.safe_load(workflow_template("o/a@v0", ["CI"], modules=mods))["jobs"]["vitals"]
        assert "STACKVITALS_EVERY_CI_RUN" in job["if"]
