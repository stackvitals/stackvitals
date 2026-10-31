"""Score the Middleware side-by-side (preregistration.md) from out/: headline DORA per repo and per-PR lead time agreement.
StackVitals' per-PR lead times are minutes (dora evidence), Middleware's seconds. Usage: python score.py [out_dir]"""
import json
import statistics
import sys
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("out"))


def load(name):
    p = OUT / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def main():
    rows = {}
    for f in sorted(OUT.glob("svm-*.json")):
        name = f.stem[4:]
        sv, svm = (load(f"sv-{name}.json") or {}).get("delivery") or {}, load(f"svm-{name}.json")["delivery"]
        mw = {k: load(f"mw-{name}-{k}.json") or {} for k in ("deployment_frequency", "lead_time", "change_failure_rate",
                                                              "mean_time_to_recovery", "lead_time_prs")}
        mw_prs = {str(p["number"]): p for p in mw["lead_time_prs"].get("data") or []}
        sv_lead = {str(n): m * 60 for n, _sha, m in svm["dora"]["evidence"]["lead_time"]}
        both = sorted(set(mw_prs) & set(sv_lead), key=int)
        close = [n for n in both if abs(sv_lead[n] - mw_prs[n]["lead_time"]) <= max(300, 0.1 * mw_prs[n]["lead_time"])]
        negative = [n for n, p in mw_prs.items() if (p.get("first_commit_to_open") or 0) < 0]
        rows[name] = {
            "deployments": {"middleware": mw["deployment_frequency"].get("total_deployments"),
                            "stackvitals_merges": svm["dora"].get("deployments"), "stackvitals_default": sv.get("dora", {}).get("deployments"),
                            "stackvitals_default_source": sv.get("deploy_source")},
            "lead_time_hours": {"middleware_mean": round(mw["lead_time"]["lead_time"] / 3600, 2) if mw["lead_time"].get("lead_time") else None,
                                "stackvitals_merges_median": svm["dora"].get("lead_time_hours"),
                                "stackvitals_merges_mean": round(statistics.mean(sv_lead.values()) / 3600, 2) if sv_lead else None,
                                "stackvitals_default_median": sv.get("dora", {}).get("lead_time_hours")},
            "prs": {"middleware": len(mw_prs), "stackvitals": len(sv_lead), "both": len(both), "within_10pct": len(close),
                    "only_stackvitals": sorted(set(sv_lead) - set(mw_prs), key=int),
                    "only_middleware": sorted(set(mw_prs) - set(sv_lead), key=int),
                    "differ": [[n, round(sv_lead[n] / 3600, 2), round(mw_prs[n]["lead_time"] / 3600, 2)] for n in both if n not in close],
                    "middleware_negative_first_commit": sorted(negative, key=int)},
            "change_failure": {"middleware": mw["change_failure_rate"].get("change_failure_rate"),
                               "middleware_failed": mw["change_failure_rate"].get("failed_deployments"),
                               "stackvitals_merges": svm["dora"].get("change_failure_rate"), "stackvitals_merges_failed": svm["dora"].get("failed_deployments"),
                               "stackvitals_default": sv.get("dora", {}).get("change_failure_rate")},
            "recovery_hours": {"middleware_mean": round(mw["mean_time_to_recovery"]["mean_time_to_recovery"] / 3600, 2)
                               if mw["mean_time_to_recovery"].get("mean_time_to_recovery") else None,
                               "middleware_incidents": mw["mean_time_to_recovery"].get("incident_count"),
                               "stackvitals_default": sv.get("dora", {}).get("recovery_hours"),
                               "stackvitals_incidents": len(sv.get("incidents") or [])},
        }
    print(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
