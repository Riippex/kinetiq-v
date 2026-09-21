"""Authentication for the Kinetiq MCP endpoint.

Only signed OIDC/JWT access tokens are accepted. A token is trusted after its
signature verifies against the trusted JWKS and its issuer, audience,
expiration, token use and scope all check out; only then is the validated
`sub` mapped to a local user. Raw user UUIDs, raw Cognito subjects and
unauthenticated identity headers are never accepted.
"""

import logging
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import anyio.to_thread
import jwt
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken

logger = logging.getLogger(__name__)

ALLOWED_ALGORITHMS = ["RS256"]


class AuthenticationRequiredError(Exception):
    """Raised when an MCP tool invocation lacks valid user authentication."""


@dataclass(frozen=True)
class OIDCSettings:
    issuer: str
    audience: str
    jwks_url: str
    required_scope: str
    token_use: str = "access"

    @property
    def configured(self) -> bool:
        return bool(self.issuer and self.audience and self.required_scope)


class SigningKeyResolver(Protocol):
    def get_signing_key(self, token: str) -> Any:
        """Return the trusted public key that must verify `token`'s signature."""


class JWKSClientResolver:
    """Resolves signing keys from the issuer's JWKS endpoint (cached by `kid`)."""

    def __init__(self, jwks_url: str) -> None:
        self._client = jwt.PyJWKClient(jwks_url, cache_keys=True, timeout=5)

    def get_signing_key(self, token: str) -> Any:
        return self._client.get_signing_key_from_jwt(token).key


def local_user_id_for_subject(subject: str) -> UUID | None:
    """Map a validated token `sub` to an active local user."""
    if not subject:
        return None
    user_model = get_user_model()
    user_id: UUID | None = (
        user_model.objects.filter(cognito_subject=subject, is_active=True)
        .values_list("id", flat=True)
        .first()
    )
    return user_id


def _token_scopes(claims: dict[str, Any]) -> list[str]:
    scope = claims.get("scope")
    if isinstance(scope, str):
        return scope.split()
    scp = claims.get("scp")
    if isinstance(scp, list):
        return [str(item) for item in scp]
    return []


def _audience_matches(claims: dict[str, Any], audience: str) -> bool:
    aud = claims.get("aud")
    if aud is not None:
        return aud == audience if isinstance(aud, str) else audience in aud
    # Cognito access tokens carry the app client in `client_id`, not `aud`.
    return bool(claims.get("client_id") == audience)


class OIDCTokenVerifier:
    """`TokenVerifier` for signed OIDC access tokens. Fails closed."""

    def __init__(
        self, settings: OIDCSettings, key_resolver: SigningKeyResolver | None = None
    ) -> None:
        self._settings = settings
        if key_resolver is None and settings.configured and settings.jwks_url:
            key_resolver = JWKSClientResolver(settings.jwks_url)
        self._key_resolver = key_resolver
        if not (settings.configured and self._key_resolver):
            logger.warning("MCP OIDC is not fully configured; every bearer token is rejected")

    async def verify_token(self, token: str) -> AccessToken | None:
        # Signature/claims validation may block on the JWKS fetch, so it runs
        # in a worker thread; the database lookup runs on Django's thread.
        access_token = await anyio.to_thread.run_sync(self._validate, token)
        if access_token is None or access_token.subject is None:
            return None
        user_id = await sync_to_async(local_user_id_for_subject, thread_sensitive=True)(
            access_token.subject
        )
        if user_id is None:
            logger.info("MCP token rejected: subject is not mapped to an active user")
            return None
        return access_token

    def _validate(self, token: str) -> AccessToken | None:
        settings = self._settings
        if not (settings.configured and self._key_resolver) or not token:
            return None
        try:
            key = self._key_resolver.get_signing_key(token)
            claims = jwt.decode(
                token,
                key,
                algorithms=ALLOWED_ALGORITHMS,
                issuer=settings.issuer,
                options={"require": ["exp", "iss", "sub"], "verify_aud": False},
            )
        except jwt.PyJWTError as exc:
            logger.info("MCP token rejected: %s", type(exc).__name__)
            return None
        except Exception:
            logger.exception("MCP token verification failed unexpectedly")
            return None

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            return None
        if not _audience_matches(claims, settings.audience):
            logger.info("MCP token rejected: audience mismatch")
            return None
        if claims.get("token_use") != settings.token_use:
            logger.info("MCP token rejected: unexpected token_use")
            return None
        scopes = _token_scopes(claims)
        if settings.required_scope not in scopes:
            logger.info("MCP token rejected: missing required scope")
            return None

        return AccessToken(
            token=token,
            client_id=str(claims.get("client_id") or claims.get("azp") or subject),
            scopes=scopes,
            expires_at=int(claims["exp"]),
            resource=settings.audience,
            subject=subject,
            claims={"iss": claims["iss"]},
        )


def resolve_mcp_owner_id() -> UUID:
    """Return the local user id for the request's validated access token.

    The bearer token was already validated by the transport's authentication
    middleware; here the validated `sub` is mapped to the local user.
    """
    access_token = get_access_token()
    if access_token is None or not access_token.subject:
        raise AuthenticationRequiredError(
            "AUTHENTICATION_REQUIRED: Sign in before accessing Kinetiq coach capabilities"
        )
    user_id = local_user_id_for_subject(access_token.subject)
    if user_id is None:
        raise AuthenticationRequiredError(
            "AUTHENTICATION_REQUIRED: The signed-in account is not available"
        )
    return user_id
