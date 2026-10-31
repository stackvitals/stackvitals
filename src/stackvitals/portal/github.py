"""Every Portal read goes through here: a refusal or a missing item is "not available", never a failure, because GitHub
keeps changing what a token may read (stargazer lists in July 2026, the SBOM export endpoint ending 2026-11-13)."""
import httpx

from stackvitals.ci.api import API, APIError, OutOfBudget

REFUSED = ("HTTP 401", "HTTP 403", "HTTP 404", "HTTP 409", "HTTP 410", "HTTP 451")


class _NotAvailable:
    def __repr__(self) -> str:
        return "not available"

    def __bool__(self) -> bool:
        return False


NA = _NotAvailable()


def read(api, path: str, params: dict | None = None):
    try:
        return api._get(path, params)
    except APIError as exc:
        if any(code in str(exc) for code in REFUSED):
            return NA
        raise


def read_file(api, repo: str, path: str, ref: str | None = None):
    try:
        return api.file(path, ref, repo=repo).decode("utf-8", "replace")
    except APIError as exc:
        if any(code in str(exc) for code in REFUSED):
            return NA
        raise


def status(api, path: str) -> int | None:
    """Only the HTTP status (membership checks answer 204 or 404 with no body)."""
    with api._lock:
        if api.max_requests is not None and api.requests >= api.max_requests:
            raise OutOfBudget(f"stopped after {api.requests} requests (budget)")
        api.requests += 1
    try:
        return api.client.get(f"{API}{path}", headers=api.headers).status_code
    except httpx.TransportError:
        return None
