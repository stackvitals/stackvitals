"""A source repo whose outside pull requests stopped is a fact to say, not a silence (real data, httpx, 2026-10-21)."""
from stackvitals.deps.dossier import _trend_lines

HTTPX = {"direction": {"first_response_hours": None, "outside_merge_rate": None}, "peers": {}, "stars": 15610,
         "quarters": [{"quarter": "2025Q4", "outside_opened": 23, "outside_decided": 9, "outside_merge_rate": 0.22, "merges": 3},
                      {"quarter": "2026Q1", "outside_opened": 28, "outside_decided": 8, "outside_merge_rate": 0.12, "merges": 1},
                      {"quarter": "2026Q2", "outside_opened": 0, "outside_decided": 0, "outside_merge_rate": None, "merges": 0},
                      {"quarter": "2026Q3", "outside_opened": 0, "outside_decided": 0, "outside_merge_rate": None, "merges": 0}]}


def test_outside_prs_that_stopped_are_reported_with_the_last_known_rate():
    lines, _ = _trend_lines(HTTPX, {"repo": "encode/httpx"})
    text = " ".join(x["text"] for x in lines)
    assert "No outside pull requests were opened in the last 2 quarters" in text
    assert "12%" in text and "2026Q1" in text
    assert any(x["signal"] == "warn" for x in lines)
