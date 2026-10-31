"""GitHub Enterprise Server: Actions names the API and GraphQL endpoints in every job, and every client follows them."""
import os
import subprocess
import sys


def test_the_clients_follow_the_job_s_github_host():
    code = ("import stackvitals.ci.api as a, mergescout.github.graphql as g, stackvitals.connectors.copilot as c;"
            "print(a.API, a.GRAPHQL, g.GitHubGraphQL.URL, c.API)")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path),
           "GITHUB_API_URL": "https://ghe.acme.dev/api/v3/", "GITHUB_GRAPHQL_URL": "https://ghe.acme.dev/api/graphql"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True).stdout.split()
    assert out == ["https://ghe.acme.dev/api/v3", "https://ghe.acme.dev/api/graphql", "https://ghe.acme.dev/api/graphql",
                   "https://ghe.acme.dev/api/v3"]


def test_without_them_it_is_github_com():
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_API_URL", "GITHUB_GRAPHQL_URL")}
    env["PYTHONPATH"] = os.pathsep.join(sys.path)
    out = subprocess.run([sys.executable, "-c", "import stackvitals.ci.api as a; print(a.API, a.GRAPHQL)"],
                         capture_output=True, text=True, env=env, check=True).stdout.split()
    assert out == ["https://api.github.com", "https://api.github.com/graphql"]
