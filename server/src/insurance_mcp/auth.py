"""Named bearer tokens: each AI client sends its own token, and its name is the caller.

The name is also the caller key that row-level security uses: it decides which
states' customers the caller sees (sql/060_row_security.sql). To use a sign-in
provider such as Entra ID or Auth0 instead, replace caller_for with a JWT check
that returns the provider's stable user id. Nothing else needs to change.

Run this file to print a new random token:  uv run python -m insurance_mcp.auth
"""

import hmac
import secrets


def caller_for(authorization: str | None, tokens: dict[str, str]) -> str | None:
    """The name of the token in an "Authorization: Bearer <token>" header, or None.

    hmac.compare_digest takes the same time whether the first character or the
    last one is wrong, so response times don't leak how close a guess was.
    """
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    for name, expected in tokens.items():
        if hmac.compare_digest(token.encode(), expected.encode()):
            return name
    return None


def new_token() -> str:
    """43 random characters (256 bits): letters, digits, - and _ only."""
    return secrets.token_urlsafe(32)


if __name__ == "__main__":
    print(new_token())
