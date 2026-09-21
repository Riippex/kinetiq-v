"""Bearer authentication for the MCP endpoint: only signed OIDC access tokens
that pass every check are accepted; the validated `sub` maps to a local user."""

import asyncio
import time
from collections.abc import Iterator
from uuid import uuid4

import jwt
import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

from kinetiq.interfaces.mcp import (
    AuthenticationRequiredError,
    OIDCTokenVerifier,
    resolve_mcp_owner_id,
)
from kinetiq.interfaces.mcp.auth import JWKSClientResolver
from kinetiq.modules.identity.infrastructure.models import User
from mcp_support import (
    ATTACKER_KEY,
    AUDIENCE,
    ISSUER,
    SCOPE,
    TRUSTED_KEY,
    make_verifier,
    mint_token,
    oidc_settings,
    trusted_jwks,
)

SUBJECT = "11111111-2222-3333-4444-555555555555"


def verify(token: str, verifier: OIDCTokenVerifier | None = None) -> AccessToken | None:
    return asyncio.run((verifier or make_verifier()).verify_token(token))


@pytest.fixture
def athlete(db: object) -> User:
    return User.objects.create(
        username="mcp_auth_athlete", email="auth@kinetiq.test", cognito_subject=SUBJECT
    )


@pytest.mark.django_db(transaction=True)
def test_valid_signed_token_is_accepted_and_carries_validated_subject(athlete: User) -> None:
    access = verify(mint_token(SUBJECT))
    assert access is not None
    assert access.subject == SUBJECT
    assert SCOPE in access.scopes


@pytest.mark.django_db(transaction=True)
def test_audience_may_be_an_aud_claim(athlete: User) -> None:
    assert verify(mint_token(SUBJECT, client_id=None, aud=AUDIENCE)) is not None
    assert verify(mint_token(SUBJECT, client_id=None, aud=["other", AUDIENCE])) is not None


@pytest.mark.django_db(transaction=True)
def test_forged_user_uuid_is_rejected(athlete: User) -> None:
    assert verify(str(athlete.id)) is None


@pytest.mark.django_db(transaction=True)
def test_forged_raw_cognito_subject_is_rejected(athlete: User) -> None:
    assert verify(SUBJECT) is None


@pytest.mark.django_db(transaction=True)
def test_token_signed_by_untrusted_key_with_trusted_kid_is_rejected(athlete: User) -> None:
    assert verify(mint_token(SUBJECT, key=ATTACKER_KEY)) is None


@pytest.mark.django_db(transaction=True)
def test_token_with_unknown_kid_is_rejected(athlete: User) -> None:
    assert verify(mint_token(SUBJECT, key=ATTACKER_KEY, kid="attacker-kid")) is None


@pytest.mark.django_db(transaction=True)
def test_unsigned_alg_none_token_is_rejected(athlete: User) -> None:
    now = int(time.time())
    unsigned = jwt.encode(
        {"sub": SUBJECT, "iss": ISSUER, "exp": now + 300, "client_id": AUDIENCE,
         "token_use": "access", "scope": SCOPE},
        None,
        algorithm="none",
        headers={"kid": "trusted-key-1"},
    )
    assert verify(unsigned) is None


@pytest.mark.django_db(transaction=True)
def test_hmac_token_using_public_key_as_secret_is_rejected(athlete: User) -> None:
    forged = jwt.encode(
        {"sub": SUBJECT, "iss": ISSUER, "exp": int(time.time()) + 300},
        "public-key-as-hmac-secret",
        algorithm="HS256",
        headers={"kid": "trusted-key-1"},
    )
    assert verify(forged) is None


@pytest.mark.django_db(transaction=True)
def test_expired_token_is_rejected(athlete: User) -> None:
    assert verify(mint_token(SUBJECT, expires_in=-60)) is None


@pytest.mark.django_db(transaction=True)
def test_token_without_expiration_is_rejected(athlete: User) -> None:
    payload = {"sub": SUBJECT, "iss": ISSUER, "client_id": AUDIENCE,
               "token_use": "access", "scope": SCOPE}
    token = jwt.encode(payload, TRUSTED_KEY, algorithm="RS256", headers={"kid": "trusted-key-1"})
    assert verify(token) is None


@pytest.mark.django_db(transaction=True)
def test_incorrect_issuer_is_rejected(athlete: User) -> None:
    assert verify(mint_token(SUBJECT, issuer="https://evil.example.com/pool")) is None


@pytest.mark.django_db(transaction=True)
def test_incorrect_audience_is_rejected(athlete: User) -> None:
    assert verify(mint_token(SUBJECT, client_id="some-other-client")) is None
    assert verify(mint_token(SUBJECT, client_id=None, aud="some-other-client")) is None
    # A wrong `aud` is not rescued by a matching client_id.
    assert verify(mint_token(SUBJECT, client_id=AUDIENCE, aud="some-other-client")) is None


@pytest.mark.django_db(transaction=True)
def test_wrong_token_use_is_rejected(athlete: User) -> None:
    assert verify(mint_token(SUBJECT, token_use="id")) is None
    assert verify(mint_token(SUBJECT, token_use=None)) is None


@pytest.mark.django_db(transaction=True)
def test_missing_required_scope_is_rejected(athlete: User) -> None:
    assert verify(mint_token(SUBJECT, scope="openid profile")) is None
    assert verify(mint_token(SUBJECT, scope=None)) is None


@pytest.mark.django_db(transaction=True)
def test_valid_token_for_unknown_subject_is_rejected(db: object) -> None:
    assert verify(mint_token("no-such-cognito-subject")) is None


@pytest.mark.django_db(transaction=True)
def test_valid_token_for_inactive_user_is_rejected(athlete: User) -> None:
    User.objects.filter(id=athlete.id).update(is_active=False)
    assert verify(mint_token(SUBJECT)) is None


@pytest.mark.django_db(transaction=True)
def test_unconfigured_verifier_fails_closed(athlete: User) -> None:
    token = mint_token(SUBJECT)
    assert verify(token, make_verifier(issuer="")) is None
    assert verify(token, make_verifier(audience="")) is None
    assert verify(token, OIDCTokenVerifier(oidc_settings(jwks_url=""))) is None


@pytest.mark.django_db(transaction=True)
def test_signing_key_is_resolved_through_the_trusted_jwks(
    athlete: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real JWKS client resolves keys from the JWKS document and rejects
    anything not signed by a key in it."""
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", lambda self: trusted_jwks())
    verifier = OIDCTokenVerifier(oidc_settings(), JWKSClientResolver(oidc_settings().jwks_url))

    assert verify(mint_token(SUBJECT), verifier) is not None
    assert verify(mint_token(SUBJECT, key=ATTACKER_KEY), verifier) is None
    assert verify(mint_token(SUBJECT, key=ATTACKER_KEY, kid="attacker-kid"), verifier) is None


@pytest.fixture
def clean_auth_context() -> Iterator[None]:
    token = auth_context_var.set(None)
    yield
    auth_context_var.reset(token)


def _authenticate_as(subject: str | None) -> None:
    if subject is None:
        auth_context_var.set(None)
        return
    auth_context_var.set(
        AuthenticatedUser(
            AccessToken(token="t", client_id="c", scopes=[SCOPE], subject=subject)
        )
    )


@pytest.mark.django_db
def test_resolve_owner_maps_validated_subject_to_local_user(
    athlete: User, clean_auth_context: None
) -> None:
    _authenticate_as(SUBJECT)
    assert resolve_mcp_owner_id() == athlete.id


@pytest.mark.django_db
def test_resolve_owner_requires_a_validated_token(db: object, clean_auth_context: None) -> None:
    _authenticate_as(None)
    with pytest.raises(AuthenticationRequiredError):
        resolve_mcp_owner_id()


@pytest.mark.django_db
def test_resolve_owner_rejects_subject_that_is_not_a_local_user(
    db: object, clean_auth_context: None
) -> None:
    _authenticate_as(str(uuid4()))
    with pytest.raises(AuthenticationRequiredError):
        resolve_mcp_owner_id()


def test_no_identity_header_or_uuid_authentication_remains() -> None:
    """The old unrestricted channels must be gone from the auth module."""
    import inspect

    from kinetiq.interfaces.mcp import auth

    source = inspect.getsource(auth).lower()
    assert "x-user-id" not in source
    assert "sessionstore" not in source
    assert "uuid(token" not in source
