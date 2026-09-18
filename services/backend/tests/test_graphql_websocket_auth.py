import asyncio

import pytest
from django.contrib.auth.models import AnonymousUser

from kinetiq.interfaces.graphql.schema import _authenticated_owner_id, schema
from kinetiq.interfaces.graphql.websocket import AuthenticatedGraphQLWSConsumer
from kinetiq.modules.identity.infrastructure.models import User


class _FakeInfo:
    def __init__(self, context) -> None:
        self.context = context


def _get_context_for_scope_user(user) -> object:
    consumer = AuthenticatedGraphQLWSConsumer(schema=schema)
    consumer.scope = {"user": user}
    return asyncio.run(consumer.get_context(consumer, consumer))


@pytest.mark.django_db
def test_authenticated_scope_user_resolves_to_owner_id() -> None:
    user = User.objects.create_user(username="ws-athlete")

    context = _get_context_for_scope_user(user)

    owner_id = _authenticated_owner_id(_FakeInfo(context))
    assert owner_id == user.pk


def test_anonymous_scope_user_resolves_to_no_owner() -> None:
    context = _get_context_for_scope_user(AnonymousUser())

    owner_id = _authenticated_owner_id(_FakeInfo(context))
    assert owner_id is None


def test_missing_scope_user_resolves_to_no_owner() -> None:
    """AuthMiddlewareStack always sets scope["user"], but the consumer must
    not crash if some other middleware stack omits it entirely."""
    consumer = AuthenticatedGraphQLWSConsumer(schema=schema)
    consumer.scope = {}

    context = asyncio.run(consumer.get_context(consumer, consumer))

    owner_id = _authenticated_owner_id(_FakeInfo(context))
    assert owner_id is None
