"""Each deployment's drill-down: the PRs it shipped, their authors, its median lead time and the incidents blamed on it."""
from stackvitals.core import delivery


def test_each_deployment_lists_what_it_shipped_and_what_it_caused():
    d1 = {"id": "d1", "name": "production", "sha": "a", "finished": "2026-10-02T00:00:00Z"}
    d2 = {"id": "d2", "name": "production", "sha": "b", "finished": "2026-10-05T00:00:00Z"}
    merged = [({"n": 1, "au": "ana"}, {"devlake_cycle_min": 120}, d1), ({"n": 2, "au": "bo"}, {"devlake_cycle_min": 60}, d1),
              ({"n": 3, "au": "ana"}, {"devlake_cycle_min": 30}, d2), ({"n": 4, "au": "bo"}, {"devlake_cycle_min": 5}, None)]
    got = delivery.deployment_list(merged, [d1, d2], [{"number": 9, "deployment": "d1"}], "2026-10-01T00:00:00Z")
    assert [(x["id"], x["prs"], x["authors"], x["lead_hours"], x["incidents"]) for x in got] == \
        [("d2", [3], 1, 0.5, []), ("d1", [1, 2], 2, 2.0, [9])]
