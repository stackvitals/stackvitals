"""Collect 45 days of CI runs with their test reports, and the PRs' changed files, for repos whose PR runs upload test
reports; capped per repo and paused between repos, so the crawler's shared token stays within its hourly limit."""
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from stackvitals.ci.api import ActionsAPI, OutOfBudget  # noqa: E402
from stackvitals.ci.collect import collect  # noqa: E402
from stackvitals.ci.store import DataStore  # noqa: E402
from stackvitals.flow.cli import local_gql  # noqa: E402
from stackvitals.flow.collect import collect as flow_collect  # noqa: E402
from stackvitals.flow.store import FlowStore  # noqa: E402

HOME = Path(__file__).with_name("work") / "tia-data"
REPOS = sys.argv[1:] or ["99designs/gqlgen", "shap/shap", "tomkerkhove/promitor", "frankarobotics/franka_ros2",
                         "langchain4j/langchain4j-spring"]
tok = os.environ["GH_TOKEN"]
now = datetime.now(timezone.utc)
for i, repo in enumerate(REPOS):
    key = repo.replace("/", "__")
    api = ActionsAPI(tok, repo, max_requests=600)
    store = DataStore(HOME / "ci" / key)
    try:
        info = api._get(f"/repos/{repo}")
        got = collect(api, store, now, days=45, tests=True)
        store.save_state({**store.state(), "default_branch": info.get("default_branch")})
    except OutOfBudget as exc:
        got = {"stopped": str(exc)}
    owner, name = repo.split("/")
    flow = flow_collect(local_gql(tok), FlowStore(HOME / "flow" / key), owner, name, now, months=2)
    data = store.load()
    print(repo, "runs", len(data.get("runs") or []), "reports", len(data.get("tests") or []), "requests", api.requests,
          "prs", flow.get("prs"), got if isinstance(got, dict) and "stopped" in got else "", flush=True)
    if i < len(REPOS) - 1:
        time.sleep(900)
print("done")
