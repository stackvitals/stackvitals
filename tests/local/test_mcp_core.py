import asyncio

from stackvitals.mcp_server import CORE_TOOLS, build_server


def test_the_default_server_offers_the_core_tools_and_all_adds_the_rest():
    core = {t.name for t in asyncio.run(build_server(tools="core").list_tools())}
    every = {t.name for t in asyncio.run(build_server(tools="all").list_tools())}
    assert core == set(CORE_TOOLS) and len(core) == 11 and core < every and len(every) == 35
