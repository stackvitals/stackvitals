"""Flake kinds from the test's own code (Datadog's root-cause categories), after the environment's kinds."""
import pytest

from stackvitals.ci.kinds import kind_of


@pytest.mark.parametrize("text, kind", [
    ("OSError: [Errno 24] Too many open files", "resource leak"),
    ("Error: listen EADDRINUSE: address already in use :::3000", "resource leak"),
    ("Warning: An update to App inside a test was not wrapped in act(...)", "async wait"),
    ("TestingLibraryElementError: Unable to find an element with the text: Save", "async wait"),
    ("AssertionError: expected 2026-03-29 but DST shifted the hour", "time"),
    ("Falsifying example: test_sort(xs=[0, -1])", "randomness"),
    ("AssertionError: 0.30000000000000004 != 0.3", "floating point"),
    ("sqlite3.IntegrityError: UNIQUE constraint failed: users.email", "shared state"),
    ("FileNotFoundError: [Errno 2] No such file or directory: 'out/report.json'", "io"),
    ("AssertionError: Element counts were not equal", "ordering"),
    # The environment's kinds still win where both show.
    ("ECONNRESET while reading; Too many open files", "network"),
    ("plain assertion failed", None),
])
def test_code_kinds(text, kind):
    assert kind_of(text) == kind
