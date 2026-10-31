"""Portal's catalog as a page in the shared header, with the same guard as its Markdown: a public portal repo shows
public repos only, and text from repos can't inject markup."""
from stackvitals.portal.pages import render_catalog_html

CATALOG = {"org": "acme", "built_at": "2026-10-20T12:00:00Z", "complete": True, "campaigns": [],
           "repos": [{"name": "web", "private": False, "owners": {"status": "valid", "reasons": ["CODEOWNERS covers 98%"]},
                      "language": "TypeScript", "pushed": "2026-10-19T10:00:00Z", "rules": [1, 2],
                      "score": {"level": "gold", "results": []}, "modules": {"ci_first_try": "92%"}},
                     {"name": "secret-infra", "private": True, "owners": {"status": "none"}, "language": "Go"},
                     {"name": "<img src=x onerror=alert(1)>", "private": False, "owners": {"status": "weak"}}]}


def test_the_portal_page_keeps_private_repos_off_a_public_destination_and_escapes_everything():
    page = render_catalog_html(CATALOG, destination_private=False)
    assert "web" in page and "gold" in page and "secret-infra" not in page
    assert "<img src=x" not in page and "&lt;img" in page
    assert "<h2>Repos</h2>" in page and "1 valid, 1 weak" in page and "Private repos are left out" in page
    assert "secret-infra" in render_catalog_html(CATALOG, destination_private=True)
