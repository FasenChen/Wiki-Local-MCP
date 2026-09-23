"""Store a Confluence personal access token in the operating-system vault."""

from getpass import getpass

import keyring

KEYRING_SERVICE = "confluence-readonly-mcp"
KEYRING_USERNAME = "pat"


def main() -> None:
    token = getpass("Confluence personal access token (input is hidden): ").strip()
    if not token:
        raise SystemExit("No token entered; nothing was saved.")

    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, token)
    print("Confluence PAT saved to the current user's operating-system credential store.")
