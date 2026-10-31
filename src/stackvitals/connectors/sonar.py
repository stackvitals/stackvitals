"""SonarQube or SonarCloud code quality (DevLake's SonarQube plugin): the project's quality gate and its measures (bugs,
vulnerabilities, code smells, coverage, duplication, ratings), read once a day and kept, so the trend shows beside the
delivery numbers. SonarCloud's public projects need no key; a private project or your own SonarQube takes a token."""
import httpx

from stackvitals.connectors.base import ConnectorError, json_of

NAME, TOKEN_ENV = "sonar", "STACKVITALS_SONAR_TOKEN"
METRICS = ("alert_status", "bugs", "vulnerabilities", "code_smells", "security_hotspots", "coverage", "duplicated_lines_density",
           "ncloc", "reliability_rating", "security_rating", "sqale_rating")
KEEP_DAYS = 400

__all__ = ["ConnectorError", "configured", "pull", "summary"]


def configured(env: dict, cfg: dict) -> bool:
    return bool(cfg["connectors"]["sonar"].get("project"))


def _get(client: httpx.Client, url: str, params: dict, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        resp = client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise ConnectorError(f"Sonar could not be reached ({type(exc).__name__}); the next run tries again.") from None
    if resp.status_code in (401, 403):
        raise ConnectorError("Sonar refused the request: a private project needs the SONAR_TOKEN secret.")
    if resp.status_code == 404:
        raise ConnectorError("Sonar has no project with that key: check project under [connectors.sonar].")
    if resp.status_code != 200:
        raise ConnectorError(f"Sonar answered {resp.status_code}; the next run tries again.")
    return json_of(resp, "Sonar")


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def pull(store, env: dict, cfg: dict, now, client: httpx.Client | None = None) -> dict:
    c = cfg["connectors"]["sonar"]
    base, project, token = (c.get("url") or "https://sonarcloud.io").rstrip("/"), c["project"], (env.get(TOKEN_ENV) or "").strip()
    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        got = _get(client, f"{base}/api/measures/component", {"component": project, "metricKeys": ",".join(METRICS)}, token)
        gate = _get(client, f"{base}/api/qualitygates/project_status", {"projectKey": project}, token)
    finally:
        if own:
            client.close()
    measures = {m["metric"]: _number(m.get("value")) for m in (got.get("component") or {}).get("measures") or [] if "value" in m}
    status = (gate.get("projectStatus") or {})
    day = now.date().isoformat()
    row = {"t": "quality", "id": f"sonar:{day}", "day": day, "project": project, "measures": measures,
           "gate": status.get("status"),
           "failing": [x.get("metricKey") for x in status.get("conditions") or [] if x.get("status") == "ERROR"]}
    store.add([row], day)
    return {"read": 1, "complete": True}


def summary(root, now) -> dict | None:
    """The newest reading, the one about 30 days before, and each day's for the charts; None before the first pull."""
    from datetime import timedelta

    from stackvitals.connectors.store import ConnectorStore
    rows = sorted((r for r in ConnectorStore(root, NAME).load().get("quality") or [] if r.get("day")), key=lambda r: r["day"])
    if not rows:
        return None
    newest = rows[-1]
    month = (now - timedelta(days=30)).date().isoformat()
    before = next((r for r in reversed(rows) if r["day"] <= month), None)
    return {"project": newest.get("project"), "day": newest["day"], "gate": newest.get("gate"), "failing": newest.get("failing") or [],
            "measures": newest.get("measures") or {}, "month_ago": (before or {}).get("measures"),
            "days": [{"day": r["day"], **{k: (r.get("measures") or {}).get(k) for k in ("bugs", "vulnerabilities", "code_smells", "coverage")}}
                     for r in rows[-180:]]}
