import hashlib
import logging
from collections.abc import Callable
from typing import Any, Protocol

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpRequest, HttpResponse, JsonResponse

logger = logging.getLogger(__name__)


class AccessTokenVerifier(Protocol):
    def verify(self, token: str) -> dict[str, Any] | None: ...


class CognitoAccessTokenVerifier:
    """Validate Cognito user access tokens against the configured pool."""

    def __init__(self) -> None:
        self._issuer: str = settings.COGNITO_ISSUER_URL
        self._client_ids: set[str] = set(settings.COGNITO_ALLOWED_CLIENT_IDS)
        self._keys = (
            jwt.PyJWKClient(settings.COGNITO_JWKS_URL, cache_keys=True, timeout=5)
            if self._issuer and self._client_ids and settings.COGNITO_JWKS_URL
            else None
        )

    def verify(self, token: str) -> dict[str, Any] | None:
        if not token or self._keys is None:
            return None
        try:
            key = self._keys.get_signing_key_from_jwt(token).key
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self._issuer,
                options={"require": ["exp", "iss", "sub"], "verify_aud": False},
            )
        except jwt.PyJWTError as error:
            logger.info("Cognito user token rejected: %s", type(error).__name__)
            return None
        except Exception:
            logger.exception("Cognito user token verification failed unexpectedly")
            return None

        if claims.get("token_use") != "access":
            return None
        if claims.get("client_id") not in self._client_ids:
            return None
        subject = claims.get("sub")
        return claims if isinstance(subject, str) and subject else None


def _local_user_for_subject(subject: str):
    user_model = get_user_model()
    existing = user_model.objects.filter(cognito_subject=subject).first()
    if existing is not None:
        return existing if existing.is_active else None

    username = f"cognito_{hashlib.sha256(subject.encode()).hexdigest()[:32]}"
    user, _ = user_model.objects.get_or_create(
        cognito_subject=subject,
        defaults={"username": username},
    )
    return user if user.is_active else None


class CognitoBearerAuthenticationMiddleware:
    """Resolve a verified Cognito bearer token into Django's request.user."""

    def __init__(
        self,
        get_response: Callable[[HttpRequest], HttpResponse],
        verifier: AccessTokenVerifier | None = None,
    ) -> None:
        self._get_response = get_response
        self._verifier = verifier or CognitoAccessTokenVerifier()

    def __call__(self, request: HttpRequest) -> HttpResponse:
        authorization = request.headers.get("Authorization", "")
        if not authorization:
            return self._get_response(request)

        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token.strip():
            return _unauthorized()

        claims = self._verifier.verify(token.strip())
        if claims is None:
            return _unauthorized()
        user = _local_user_for_subject(str(claims["sub"]))
        if user is None:
            return _unauthorized()
        request.user = user
        return self._get_response(request)


def _unauthorized() -> JsonResponse:
    response = JsonResponse(
        {"errors": [{"message": "Invalid or expired access token"}]}, status=401
    )
    response["WWW-Authenticate"] = 'Bearer realm="kinetiq-v"'
    return response
