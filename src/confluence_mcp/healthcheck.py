"""Check that the configured Confluence credentials identify a user."""

from __future__ import annotations

import sys

from .client import ConfluenceAPIError, ConfluenceClient, ConfluenceConfigurationError, ConfluenceSettings


def verify_wiki_connection(settings: ConfluenceSettings) -> None:
    client = ConfluenceClient(settings)
    try:
        user = client.get_current_user()
        user_type = user.get("type")
        identifiers = (user.get("username"), user.get("userKey"))
        identified = any(
            isinstance(value, str) and value.strip() and value.strip().casefold() != "anonymous"
            for value in identifiers
        )
        if (isinstance(user_type, str) and user_type.strip().casefold() == "anonymous") or not identified:
            raise ConfluenceAPIError("Could not confirm an authenticated Confluence user.")
    finally:
        client.close()


def main() -> int:
    try:
        verify_wiki_connection(ConfluenceSettings.from_environment())
    except (ConfluenceAPIError, ConfluenceConfigurationError, OSError, ValueError) as exc:
        print(f"Confluence check failed: {exc}", file=sys.stderr)
        return 1
    print("Confluence authentication succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
