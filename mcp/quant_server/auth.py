"""Who is calling? Principal resolution for the common gate (Phase 15, P0).

Two questions, answered separately:

* **Which caller** may reach the bridge at all. When ``EVE_INTERNAL_SECRET``
  is set, every request must carry it in ``X-Eve-Internal``. Only the Hisaab
  server knows it; a browser never does. Missing or wrong -> 403.
* **Which user** the call is for. A Supabase access token in
  ``Authorization: Bearer`` is verified locally (signature, ``exp``,
  ``aud=authenticated``, ``iss``) and its ``sub`` becomes the user id. A bad
  token -> 401. A model-supplied ``user_id`` argument is never trusted; the
  gate strips it.

Verification uses the project's JWKS (asymmetric ES256/RS256 signing keys).
Projects still on the legacy shared secret set ``SUPABASE_JWT_SECRET`` and get
HS256 verification instead -- the JWKS endpoint returns no keys for them.

The stdio MCP server has no headers. Following the MCP spec's guidance that
STDIO servers take credentials from the environment, it gets a principal from
``EVE_LOCAL_USER_ID`` but only when ``EVE_LOCAL_DEV=1`` -- a local research
console, never production.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import jwt

PrincipalKind = Literal["user", "local_dev", "anonymous"]

_TRUTHY = {"1", "true", "yes", "on"}


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


@dataclass(frozen=True)
class Principal:
    """The verified identity a tool call runs as."""

    kind: PrincipalKind
    user_id: str | None = None
    # The caller's own Supabase access token, kept so user-tier writes can go
    # through PostgREST *as the user* and RLS stays a backstop. Never logged.
    access_token: str | None = None

    @property
    def is_user(self) -> bool:
        return self.user_id is not None

    @property
    def key(self) -> str:
        """Rate-limit / audit key."""
        return self.user_id or "anonymous"


ANONYMOUS = Principal(kind="anonymous")


class AuthError(Exception):
    """Authentication or caller-authorisation failure (401 / 403)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


# The principal of the tool call currently executing. Set by the gate before
# a tool runs; asyncio.to_thread copies context, so tools running in worker
# threads see it too. User-tier tools read it through ``require_principal``
# instead of taking an argument the model could fill in.
_CURRENT: ContextVar[Principal] = ContextVar("eve_principal", default=ANONYMOUS)


def current_principal() -> Principal:
    return _CURRENT.get()


def require_principal() -> Principal:
    principal = _CURRENT.get()
    if not principal.is_user:
        raise AuthError(401, "this tool needs a signed-in user")
    return principal


def set_current_principal(principal: Principal):  # -> Token
    return _CURRENT.set(principal)


def reset_current_principal(token) -> None:
    _CURRENT.reset(token)


# ------------------------------------------------------------------ settings


def internal_secret() -> str | None:
    value = os.environ.get("EVE_INTERNAL_SECRET", "").strip()
    return value or None


def require_user_everywhere() -> bool:
    """``EVE_REQUIRE_USER=1`` makes every tool, research ones included, need a user."""
    return _env_flag("EVE_REQUIRE_USER")


def _supabase_url() -> str | None:
    value = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    return value or None


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{url}/auth/v1/.well-known/jwks.json", cache_keys=True)


def verify_supabase_jwt(token: str) -> dict[str, object]:
    """Verify a Supabase access token and return its claims.

    Raises ``AuthError(401)`` on any failure. The message is generic on
    purpose: the caller is the Hisaab server, and the detail goes to the log.
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise AuthError(401, f"malformed access token: {exc}") from exc

    alg = header.get("alg")
    url = _supabase_url()
    options = {"require": ["exp", "sub"]}
    decode_kwargs: dict[str, object] = {"audience": "authenticated", "options": options}
    if url:
        decode_kwargs["issuer"] = f"{url}/auth/v1"

    try:
        if alg == "HS256":
            secret = os.environ.get("SUPABASE_JWT_SECRET", "").strip()
            if not secret:
                raise AuthError(
                    401,
                    "HS256 token but SUPABASE_JWT_SECRET is not set on the engine",
                )
            claims = jwt.decode(token, secret, algorithms=["HS256"], **decode_kwargs)
        elif alg in {"ES256", "RS256"}:
            if not url:
                raise AuthError(401, "SUPABASE_URL is not set on the engine")
            key = _jwks_client(url).get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=[alg], **decode_kwargs)
        else:
            raise AuthError(401, f"unsupported token algorithm {alg!r}")
    except jwt.PyJWTError as exc:
        raise AuthError(401, f"invalid access token: {exc}") from exc

    if claims.get("role") not in (None, "authenticated"):
        raise AuthError(401, "token is not for an authenticated user")
    return claims


# ------------------------------------------------------------------ resolution


def _local_dev_principal() -> Principal | None:
    if not _env_flag("EVE_LOCAL_DEV"):
        return None
    user_id = os.environ.get("EVE_LOCAL_USER_ID", "").strip()
    if not user_id:
        return None
    return Principal(kind="local_dev", user_id=user_id)


def principal_from_headers(headers: Mapping[str, str]) -> Principal:
    """Resolve the principal for one HTTP request to the bridge."""
    secret = internal_secret()
    if secret is not None:
        presented = headers.get("x-eve-internal", "")
        if not hmac.compare_digest(presented.encode(), secret.encode()):
            raise AuthError(403, "caller is not allowed to reach the engine")

    auth = headers.get("authorization", "")
    if auth:
        scheme, _, token = auth.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise AuthError(401, "Authorization header must be 'Bearer <token>'")
        claims = verify_supabase_jwt(token.strip())
        return Principal(kind="user", user_id=str(claims["sub"]), access_token=token.strip())

    local = _local_dev_principal()
    if local is not None:
        return local
    return ANONYMOUS


def principal_from_env() -> Principal:
    """Resolve the principal for the stdio MCP server (no headers exist)."""
    return _local_dev_principal() or ANONYMOUS
