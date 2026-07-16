"""
Thin HTTP client for the Mission Control API.

Handles:
- Base URL resolution (MC_API_URL env var or application.yaml)
- JWT authentication with token storage (~/.config/mission-control/auth.json)
- ApiResponse envelope unwrapping (reads .data, raises on .error)
- SSE streaming for chat and live events
- Error handling with Click-friendly messages

Usage:
    from modules.clients.cli.api_client import api_client

    async with api_client() as api:
        missions = await api.get("/missions")
        await api.post("/missions", body={"name": "my-app", ...})
"""

import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import click
import httpx
import yaml

from modules.backend.core.logging import get_logger, setup_logging

logger = get_logger(__name__)

_AUTH_DIR = Path.home() / ".config" / "mission-control"
_AUTH_FILE = _AUTH_DIR / "auth.json"


# =============================================================================
# Errors
# =============================================================================


class ApiError(click.ClickException):
    """API request failed with a structured error."""

    def __init__(self, code: str, message: str, status: int = 0):
        super().__init__(message)
        self.api_code = code
        self.status = status


class ApiConnectionError(click.ClickException):
    """Cannot connect to the API server."""

    def __init__(self, base_url: str, detail: str):
        super().__init__(
            f"Cannot connect to Mission Control API at {base_url}\n"
            f"  {detail}\n\n"
            "  Is the server running?  python services.py start\n"
            "  Or set MC_API_URL if the server is elsewhere."
        )


# =============================================================================
# Client
# =============================================================================


class CliApiClient:
    """HTTP client for Mission Control API.

    Handles authentication, ApiResponse envelope unwrapping, and SSE streaming.
    All CLI commands use this instead of direct backend service calls.
    """

    def __init__(self, base_url: str | None = None):
        self._base_url = base_url or _resolve_base_url()
        self._client: httpx.AsyncClient | None = None
        self._access_token: str | None = None
        self._refresh_token_str: str | None = None

    async def __aenter__(self) -> "CliApiClient":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0),
        )
        self._load_stored_token()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Public HTTP methods ──────────────────────────────────────────

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET request, returns unwrapped data."""
        return await self._request("GET", path, params=params)

    async def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        """POST request, returns unwrapped data."""
        return await self._request("POST", path, body=body)

    async def put(self, path: str, body: dict[str, Any] | None = None) -> Any:
        """PUT request, returns unwrapped data."""
        return await self._request("PUT", path, body=body)

    async def patch(self, path: str, body: dict[str, Any] | None = None) -> Any:
        """PATCH request, returns unwrapped data."""
        return await self._request("PATCH", path, body=body)

    async def delete(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """DELETE request, returns unwrapped data."""
        return await self._request("DELETE", path, params=params)

    async def stream_sse(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream SSE events as parsed dicts.

        Yields dicts with 'event' (SSE event type) and 'data' (parsed JSON payload).
        """
        await self._ensure_auth()
        headers = self._auth_headers()
        assert self._client is not None
        try:
            async with self._client.stream(
                method,
                path,
                json=body,
                params=params,
                headers=headers,
            ) as response:
                if response.status_code != 200:
                    raw = await response.aread()
                    _raise_for_error(response.status_code, raw)
                event_type = "message"
                async for line in response.aiter_lines():
                    stripped = line.strip()
                    if not stripped:
                        continue
                    if stripped.startswith("event:"):
                        event_type = stripped[6:].strip()
                    elif stripped.startswith("data:"):
                        raw_data = stripped[5:].strip()
                        if raw_data:
                            try:
                                parsed = json.loads(raw_data)
                            except json.JSONDecodeError:
                                parsed = {"text": raw_data}
                            yield {"event": event_type, "data": parsed}
                            event_type = "message"
        except httpx.ConnectError as exc:
            raise ApiConnectionError(self._base_url, str(exc)) from exc

    # ── Auth ─────────────────────────────────────────────────────────

    async def login(self, email: str, password: str) -> dict[str, Any]:
        """Authenticate and store JWT tokens."""
        assert self._client is not None
        try:
            resp = await self._client.post(
                "/auth/login",
                json={"email": email, "password": password},
            )
        except httpx.ConnectError as exc:
            raise ApiConnectionError(self._base_url, str(exc)) from exc
        if resp.status_code != 200:
            _raise_for_error(resp.status_code, resp.content)
        envelope = resp.json()
        data = envelope.get("data", envelope)
        self._access_token = data["access_token"]
        self._refresh_token_str = data["refresh_token"]
        self._save_token(email)
        return data

    async def logout(self) -> None:
        """Clear stored authentication."""
        self._access_token = None
        self._refresh_token_str = None
        if _AUTH_FILE.exists():
            _AUTH_FILE.unlink()

    async def get_current_mission_id(self) -> str | None:
        """Get the logged-in user's current mission ID."""
        me = await self.get("/auth/me")
        return me.get("current_mission_id")

    @property
    def is_authenticated(self) -> bool:
        """Whether a token is currently loaded."""
        return self._access_token is not None

    # ── Private ──────────────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Make an authenticated request and unwrap the ApiResponse envelope."""
        await self._ensure_auth()
        headers = self._auth_headers()
        assert self._client is not None

        logger.debug("%s %s", method, path)

        try:
            resp = await self._client.request(
                method,
                path,
                json=body,
                params=params,
                headers=headers,
            )
        except httpx.ConnectError as exc:
            raise ApiConnectionError(self._base_url, str(exc)) from exc

        # Retry once on 401 (token expired)
        if resp.status_code == 401:
            if await self._try_refresh():
                headers = self._auth_headers()
                resp = await self._client.request(
                    method,
                    path,
                    json=body,
                    params=params,
                    headers=headers,
                )
            else:
                await self._interactive_login()
                headers = self._auth_headers()
                resp = await self._client.request(
                    method,
                    path,
                    json=body,
                    params=params,
                    headers=headers,
                )

        if resp.status_code >= 400:
            _raise_for_error(resp.status_code, resp.content)

        # Unwrap ApiResponse envelope
        envelope = resp.json()
        if isinstance(envelope, dict) and "success" in envelope:
            if not envelope["success"]:
                err = envelope.get("error", {})
                raise ApiError(
                    err.get("code", "UNKNOWN"),
                    err.get("message", "Unknown error"),
                    resp.status_code,
                )
            return envelope.get("data")
        return envelope

    async def _ensure_auth(self) -> None:
        """Ensure we have an access token, prompting for login if needed."""
        if self._access_token:
            return
        self._load_stored_token()
        if self._access_token:
            return
        await self._interactive_login()

    async def _interactive_login(self) -> None:
        """Prompt user for credentials and authenticate."""
        click.echo("Authentication required.")
        email = click.prompt("Email")
        password = click.prompt("Password", hide_input=True)
        await self.login(email, password)
        click.echo(click.style("Logged in.", fg="green"))

    async def _try_refresh(self) -> bool:
        """Try to refresh the access token. Returns True on success."""
        if not self._refresh_token_str:
            return False
        assert self._client is not None
        try:
            resp = await self._client.post(
                "/auth/refresh",
                json={"refresh_token": self._refresh_token_str},
            )
            if resp.status_code == 200:
                envelope = resp.json()
                data = envelope.get("data", envelope)
                self._access_token = data["access_token"]
                self._refresh_token_str = data.get(
                    "refresh_token",
                    self._refresh_token_str,
                )
                self._save_token()
                return True
        except httpx.HTTPError as exc:
            logger.debug("Token refresh failed: %s", exc)
        return False

    def _auth_headers(self) -> dict[str, str]:
        """Build Authorization header."""
        if self._access_token:
            return {"Authorization": f"Bearer {self._access_token}"}
        return {}

    def _load_stored_token(self) -> None:
        """Load JWT tokens from disk."""
        if not _AUTH_FILE.exists():
            return
        try:
            data = json.loads(_AUTH_FILE.read_text())
            self._access_token = data.get("access_token")
            self._refresh_token_str = data.get("refresh_token")
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            logger.warning("Corrupt auth file %s: %s — will re-authenticate", _AUTH_FILE, exc)

    def _save_token(self, email: str | None = None) -> None:
        """Persist JWT tokens to disk."""
        _AUTH_DIR.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token_str,
        }
        if email:
            data["email"] = email
        _AUTH_FILE.write_text(json.dumps(data))
        _AUTH_FILE.chmod(0o600)


# =============================================================================
# Module-level helpers
# =============================================================================


@asynccontextmanager
async def api_client(base_url: str | None = None) -> AsyncIterator[CliApiClient]:
    """Context manager for an authenticated API client.

    Usage:
        async with api_client() as api:
            data = await api.get("/missions")
    """
    client = CliApiClient(base_url=base_url)
    async with client:
        yield client


def _resolve_base_url() -> str:
    """Resolve API base URL from MC_API_URL env var or application.yaml."""
    env_url = os.environ.get("MC_API_URL")
    if env_url:
        return env_url.rstrip("/")

    project_root = _find_project_root()
    config_path = project_root / "config" / "settings" / "application.yaml"
    if not config_path.exists():
        raise click.ClickException(
            "Cannot determine API URL. Set MC_API_URL or ensure "
            "config/settings/application.yaml exists."
        )
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    server = cfg.get("server", {})
    host = server.get("host", "localhost")
    port = server.get("port", 8100)
    # Convert bind-all addresses to localhost for client connections
    if host in ("0.0.0.0", "::", "[::]", ""):
        host = "localhost"
    api_prefix = cfg.get("api_prefix", "/api")
    return f"http://{host}:{port}{api_prefix}/v1"


def _find_project_root() -> Path:
    """Locate the project root via .project_root marker."""
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        if (parent / ".project_root").exists():
            return parent
    raise click.ClickException("Cannot find .project_root marker. Run from the project directory.")


def _raise_for_error(status: int, body: bytes) -> None:
    """Parse error body and raise ApiError."""
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            err = parsed.get("error", {})
            if isinstance(err, dict):
                raise ApiError(
                    err.get("code", f"HTTP_{status}"),
                    err.get("message", f"Request failed with status {status}"),
                    status,
                )
            detail = parsed.get("detail", str(err))
            raise ApiError(f"HTTP_{status}", str(detail), status)
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    raise ApiError(f"HTTP_{status}", f"Request failed with status {status}", status)


async def require_mission(api: CliApiClient) -> str:
    """Get the current user's selected mission ID, or exit with guidance."""
    mission_id = await api.get_current_mission_id()
    if not mission_id:
        click.echo(
            click.style(
                "No mission selected.\n\n"
                "  Set one with:  mc mission use --name <name>\n"
                "  Or create:     mc mission create --name my-project --description '...'\n",
                fg="yellow",
            )
        )
        raise SystemExit(1)
    return mission_id


async def resolve_mission(
    api: CliApiClient,
    name_or_id: str,
    include_archived: bool = False,
) -> dict[str, Any] | None:
    """Resolve a mission name or ID to its dict, or None if not found."""
    params: dict[str, str] = {}
    if include_archived:
        params["include_archived"] = "true"
    data = await api.get("/missions", params=params)
    missions = extract_list(data, "missions")
    for m in missions:
        if m.get("name") == name_or_id or m.get("id") == name_or_id:
            return m
    return None


def extract_list(response: Any, field: str) -> list:
    """Extract a list from an API response that may be a list or dict wrapper."""
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        return response.get(field, [])
    return []


async def resolve_short_id(
    api: "CliApiClient",
    *,
    list_url: str,
    list_field: str,
    prefix: str,
    min_prefix_len: int = 4,
    not_found_hint: str | None = None,
) -> str:
    """Resolve a full UUID from a short prefix by listing + matching.

    Used by ``mc plan`` / ``mc gate`` (and any future CLI surface that
    accepts short ids). Pass-through for full UUIDs; for shorter input,
    fetches ``list_url``, extracts ``list_field``, and matches by prefix.
    Fails loud on no-match or ambiguous match.
    """
    if len(prefix) >= 32 and "-" in prefix:
        return prefix
    if len(prefix) < min_prefix_len:
        import click

        click.echo(
            f"Id prefix {prefix!r} too short (need >= {min_prefix_len} chars).",
            err=True,
        )
        sys.exit(1)
    response = await api.get(list_url)
    items = response.get(list_field, []) if isinstance(response, dict) else []
    matches = [item["id"] for item in items if item.get("id", "").startswith(prefix)]
    if not matches:
        import click

        msg = f"No id starts with {prefix!r}."
        if not_found_hint:
            msg += f" {not_found_hint}"
        click.echo(msg, err=True)
        sys.exit(1)
    if len(matches) > 1:
        import click

        click.echo(
            f"Ambiguous prefix {prefix!r} matches {len(matches)} items:\n  " + "\n  ".join(matches),
            err=True,
        )
        sys.exit(1)
    return matches[0]


def setup_cli_logging(verbose: bool, debug: bool) -> None:
    """Configure logging for the thin CLI client.

    Routes through the centralized logging setup (rule 001.2), matching
    the admin CLI's CliContext. Only HTTP-level diagnostics are logged —
    business logging stays on the server.
    """
    level = "DEBUG" if debug else "INFO" if verbose else "WARNING"
    setup_logging(level=level, format_type="console")
