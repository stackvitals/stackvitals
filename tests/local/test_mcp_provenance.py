"""Every MCP answer says when its numbers are from and where they came from (M6)."""
from stackvitals import mcp_server


def test_answers_carry_as_of_and_sources_and_errors_stay_plain():
    wrapped = mcp_server._safe(lambda: {"repo": "o/r", "source": "stackvitals-data branch", "generated": "2026-10-20T12:00:00Z"})
    out = wrapped()
    assert out["as_of"] == "2026-10-20T12:00:00Z" and out["sources"] == ["stackvitals-data branch"]
    nested = mcp_server._safe(lambda: {"repo": "o/r", "source": "read live", "red_ci": {"until": "2026-10-19T00:00:00Z"}})()
    assert nested["as_of"] == "2026-10-19T00:00:00Z"
    bare = mcp_server._safe(lambda: {"repo": "o/r"})()
    assert bare["as_of"] and bare["sources"] == []

    def boom():
        raise ValueError("no such repo")
    assert mcp_server._safe(boom)() == {"error": "no such repo"}
