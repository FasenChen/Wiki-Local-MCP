"""Minimal GET-only client for the Confluence Server/Data Center REST API."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
import keyring

from .credentials import KEYRING_SERVICE, KEYRING_USERNAME


class ConfluenceConfigurationError(RuntimeError):
    """Raised when required connection settings are missing or invalid."""


class ConfluenceAPIError(RuntimeError):
    """Raised when Confluence returns an unsuccessful response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ConfluenceSettings:
    base_url: str
    pat: str | None
    username: str | None
    password: str | None
    ca_bundle: str | None

    @classmethod
    def from_environment(cls) -> "ConfluenceSettings":
        raw_url = os.environ.get("ATLASSIAN_CONFLUENCE_URL", "").strip()
        if not raw_url:
            raise ConfluenceConfigurationError(
                "Set ATLASSIAN_CONFLUENCE_URL to the Confluence base URL, "
                "including any context path such as /confluence."
            )

        parsed = urlsplit(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfluenceConfigurationError(
                "ATLASSIAN_CONFLUENCE_URL must be an absolute http:// or https:// URL."
            )
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConfluenceConfigurationError(
                "ATLASSIAN_CONFLUENCE_URL must not contain credentials, a query, or a fragment."
            )
        normalized_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))

        pat = os.environ.get("ATLASSIAN_CONFLUENCE_PAT", "").strip() or None
        username = os.environ.get("ATLASSIAN_CONFLUENCE_USERNAME", "").strip() or None
        password = os.environ.get("ATLASSIAN_CONFLUENCE_PASSWORD", "") or None
        if pat is None and not (username and password):
            try:
                pat = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
            except Exception as exc:
                raise ConfluenceConfigurationError(
                    "Could not read the operating-system credential store. Set "
                    "ATLASSIAN_CONFLUENCE_PAT or save a PAT with "
                    "`uv run confluence-mcp-store-pat`."
                ) from exc

        if pat is None and not (username and password):
            raise ConfluenceConfigurationError(
                "No Confluence credentials found. Save a PAT with "
                "`uv run confluence-mcp-store-pat`, set ATLASSIAN_CONFLUENCE_PAT, "
                "or set both ATLASSIAN_CONFLUENCE_USERNAME and "
                "ATLASSIAN_CONFLUENCE_PASSWORD."
            )

        ca_bundle = os.environ.get("ATLASSIAN_CONFLUENCE_CA_BUNDLE", "").strip() or None
        return cls(normalized_url, pat, username, password, ca_bundle)


class ConfluenceClient:
    """A deliberately GET-only wrapper around Confluence REST API v1."""

    def __init__(self, settings: ConfluenceSettings) -> None:
        headers = {"Accept": "application/json"}
        auth: tuple[str, str] | None = None
        if settings.pat:
            headers["Authorization"] = f"Bearer {settings.pat}"
        else:
            assert settings.username is not None and settings.password is not None
            auth = (settings.username, settings.password)

        self._client = httpx.Client(
            base_url=f"{settings.base_url}/rest/api/",
            headers=headers,
            auth=auth,
            verify=settings.ca_bundle or True,
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=False,
        )
        self._base_url = settings.base_url

    def _validate_page_id(self, page_id: str) -> None:
        if not re.fullmatch(r"[0-9]+", page_id):
            raise ValueError("page_id must contain only digits.")

    def get_page(self, page_id: str) -> dict[str, Any]:
        self._validate_page_id(page_id)
        return self._get_json(
            f"content/{page_id}",
            params={"expand": "body.storage,body.view,version,space,ancestors"},
        )

    def search_pages(self, cql: str, limit: int) -> list[dict[str, Any]]:
        payload = self._get_json(
            "content/search",
            params={"cql": cql, "limit": limit, "expand": "space,version"},
        )
        return payload.get("results", [])

    def search_cql(self, cql: str, *, limit: int, start: int) -> dict[str, Any]:
        return self._get_json(
            "search",
            params={
                "cql": cql,
                "limit": limit,
                "start": start,
                "expand": "content.space,content.version",
            },
        )

    def list_spaces(self, *, limit: int, start: int) -> dict[str, Any]:
        return self._get_json("space", params={"type": "global", "limit": limit, "start": start})

    def get_comments(self, page_id: str, *, limit: int) -> list[dict[str, Any]]:
        self._validate_page_id(page_id)
        payload = self._get_json(
            f"content/{page_id}/child/comment",
            params={
                "expand": "body.storage,version,history",
                "depth": "all",
                "limit": limit,
            },
        )
        return payload.get("results", [])

    def get_child_pages(self, page_id: str, *, limit: int) -> list[dict[str, Any]]:
        self._validate_page_id(page_id)
        payload = self._get_json(
            f"content/{page_id}/child/page",
            params={"expand": "space,version", "limit": limit},
        )
        return payload.get("results", [])

    def _get_json(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        # This is the only HTTP operation in the client. No write method is exposed.
        try:
            response = self._client.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise ConfluenceAPIError("The Confluence request timed out.") from exc
        except httpx.ConnectError as exc:
            raise ConfluenceAPIError(
                "Could not connect to Confluence. Check the URL, network/VPN, and TLS CA settings."
            ) from exc

        if response.is_redirect:
            raise ConfluenceAPIError(
                "Confluence redirected the API request. Check the base URL and context path; "
                "the server does not follow redirects to avoid sending credentials elsewhere.",
                status_code=response.status_code,
            )
        if response.status_code == 401:
            raise ConfluenceAPIError(
                "Confluence returned 401: credentials are missing, invalid, or expired.",
                status_code=401,
            )
        if response.status_code == 403:
            raise ConfluenceAPIError(
                "Confluence returned 403: the account lacks permission to read this content.",
                status_code=403,
            )
        if response.status_code == 404:
            raise ConfluenceAPIError(
                "Confluence returned 404: check the page ID and base URL context path; "
                "a page hidden by permissions may also appear unavailable.",
                status_code=404,
            )
        if response.is_error:
            raise ConfluenceAPIError(
                f"Confluence returned HTTP {response.status_code}.",
                status_code=response.status_code,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ConfluenceAPIError("Confluence returned a non-JSON response; check the base URL.") from exc
        if not isinstance(payload, dict):
            raise ConfluenceAPIError("Confluence returned an unexpected response shape.")
        return payload

    def absolute_url(self, path: str | None, *, base: str | None = None) -> str | None:
        if not path:
            return None
        response_base = base or self._base_url
        return urljoin(response_base.rstrip("/") + "/", path.lstrip("/"))

    def page_url(self, page: dict[str, Any]) -> str | None:
        links = page.get("_links") or {}
        return self.absolute_url(links.get("webui"), base=links.get("base"))


@lru_cache(maxsize=1)
def get_client() -> ConfluenceClient:
    return ConfluenceClient(ConfluenceSettings.from_environment())


def quote_cql(value: str) -> str:
    """Escape a value embedded in a quoted CQL string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')
