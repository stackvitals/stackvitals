from mergescout.signals.walls import build_walls, find_walls
from signals_data import make_con


def walls(**meta):
    return {w for w, _ in find_walls({"has_issues": True, "ai_policy_sha": None, "contributing_excerpt": "",
                                      "readme_excerpt": "", **meta})}


def test_each_wall_is_found_with_evidence():
    assert walls(contributing_excerpt="You must sign our Contributor License Agreement.") == {"cla"}
    assert walls(contributing_excerpt="All commits need a Signed-off-by line (DCO).") == {"dco"}
    assert walls(contributing_excerpt="Please open an issue first and wait for approval.") == {"issue_first"}
    assert walls(contributing_excerpt="We do not accept AI-generated pull requests.") == {"ai_ban"}
    assert walls(readme_excerpt="We are not accepting pull requests at this time.") == {"no_outside_prs"}
    assert walls(ai_policy_sha="abc") == {"ai_policy"}
    assert walls(has_issues=False) == {"issues_disabled"}
    assert walls(contributing_excerpt="Thanks for contributing! Run the tests.") == set()


def test_snippet_shows_the_matched_text():
    found = dict(find_walls({"has_issues": True, "contributing_excerpt": "x " * 200 + "Sign the CLA here." + " y" * 200}))
    assert "Sign the CLA" in found["cla"] and len(found["cla"]) <= 160


def test_build_walls_table():
    con = make_con({"repo_meta": [{"repo_id": 1, "name": "o/r", "has_issues": True,
                                   "contributing_excerpt": "Sign the CLA"}]})
    build_walls(con)
    assert con.execute("SELECT repo_id, wall, blocking FROM repo_walls").fetchall() == [(1, "cla", True)]


