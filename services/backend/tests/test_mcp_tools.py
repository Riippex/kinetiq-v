"""MCP tool behavior over the secured Streamable HTTP transport: product
lifecycle, retry idempotency for every mutating tool, and cross-user isolation."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

import pytest
from mcp.client.session import ClientSession

from kinetiq.modules.catalog.application.seed_catalog import SeedCatalogUseCase
from kinetiq.modules.catalog.infrastructure.canonical_data import (
    CANONICAL_EXERCISES,
    CANONICAL_GOALS,
    CANONICAL_TEMPLATES,
)
from kinetiq.modules.catalog.infrastructure.repositories import DjangoCatalogRepository
from kinetiq.modules.catalog.infrastructure.vision_contract_adapter import (
    FileBasedVisionCapabilities,
)
from kinetiq.modules.goals.infrastructure.models import GoalRevisionRecord
from kinetiq.modules.identity.infrastructure.models import User
from kinetiq.modules.integrations.infrastructure.models import McpToolReceipt
from kinetiq.modules.media.infrastructure.models import ProgressPhotoRecord
from kinetiq.modules.routines.infrastructure.models import RoutineRecord
from kinetiq.modules.workouts.infrastructure.models import WorkoutSessionRecord
from mcp_support import (
    LifespanRunner,
    error_text,
    make_app,
    mcp_session,
    mint_token,
    result_payload,
)

SUB_A = "aaaaaaaa-0000-4000-8000-00000000000a"
SUB_B = "bbbbbbbb-0000-4000-8000-00000000000b"


@pytest.fixture
def alice(db: object) -> User:
    return User.objects.create(username="alice", email="a@kinetiq.test", cognito_subject=SUB_A)


@pytest.fixture
def bob(db: object) -> User:
    return User.objects.create(username="bob", email="b@kinetiq.test", cognito_subject=SUB_B)


@pytest.fixture
def seed_catalog(db: object) -> None:
    SeedCatalogUseCase(
        catalog_repo=DjangoCatalogRepository(), vision_capabilities=FileBasedVisionCapabilities()
    ).execute(
        goals=CANONICAL_GOALS, exercises=CANONICAL_EXERCISES, templates=CANONICAL_TEMPLATES
    )


def run_as(
    *subjects: str, scenario: Callable[..., Awaitable[None]]
) -> None:
    """Run `scenario` with one authenticated MCP session per subject."""

    async def main() -> None:
        app = make_app()
        async with LifespanRunner(app):
            sessions: list[ClientSession] = []
            contexts = [mcp_session(app, mint_token(subject)) for subject in subjects]
            try:
                for context in contexts:
                    sessions.append(await context.__aenter__())
                await scenario(*sessions)
            finally:
                for context in reversed(contexts):
                    await context.__aexit__(None, None, None)

    asyncio.run(main())


async def call(session: ClientSession, tool: str, **arguments: Any) -> Any:
    return result_payload(await session.call_tool(tool, arguments))


async def call_error(session: ClientSession, tool: str, **arguments: Any) -> str:
    return error_text(await session.call_tool(tool, arguments))


async def accepted_routine(session: ClientSession, key_prefix: str) -> dict[str, Any]:
    proposal = await call(session, "propose_routine", idempotency_key=f"{key_prefix}-propose")
    return await call(
        session,
        "accept_routine",
        idempotency_key=f"{key_prefix}-accept",
        routine_id=proposal["routine_id"],
        version=proposal["version"],
    )


# --- Lifecycle ---


@pytest.mark.django_db(transaction=True)
def test_profile_goal_routine_and_session_lifecycle(alice: User, seed_catalog: None) -> None:
    async def scenario(s: ClientSession) -> None:
        profile = await call(s, "get_profile")
        assert profile["id"] == str(alice.id)
        assert profile["display_name"] == "Athlete"

        updated = await call(
            s,
            "update_profile",
            idempotency_key="lifecycle-profile",
            display_name="Power Athlete",
            coaching_tone="MOTIVATIONAL",
            availability_days_per_week=4,
        )
        assert updated["display_name"] == "Power Athlete"
        assert updated["availability_days_per_week"] == 4

        assert await call(s, "get_active_goal") is None
        goal = await call(
            s,
            "set_goal",
            idempotency_key="lifecycle-goal",
            description="Complete 3 workouts weekly",
            measure="weekly_completed_sessions",
            baseline=0.0,
            target=3.0,
            unit="sessions",
        )
        assert (await call(s, "get_active_goal"))["goal_id"] == goal["goal_id"]
        assert len(await call(s, "list_goal_revisions")) == 1

        routine = await accepted_routine(s, "lifecycle")
        assert routine["status"] == "ACCEPTED"
        current = await call(s, "get_current_routine")
        assert current["title"] == "Full Body Foundation"

        prep = await call(
            s,
            "prepare_session",
            idempotency_key="lifecycle-prepare",
            routine_id=routine["routine_id"],
            routine_version=routine["version"],
        )
        assert prep["status"] == "READY"
        sid, rev = prep["session_id"], prep["revision"]

        start = await call(
            s, "start_session", idempotency_key="lifecycle-start", session_id=sid,
            expected_revision=rev,
        )
        assert start["status"] == "ACTIVE"
        pause = await call(
            s, "pause_session", idempotency_key="lifecycle-pause", session_id=sid,
            expected_revision=start["revision"],
        )
        assert pause["status"] == "PAUSED"
        resume = await call(
            s, "resume_session", idempotency_key="lifecycle-resume", session_id=sid,
            expected_revision=pause["revision"],
        )
        assert resume["status"] == "ACTIVE"
        finish = await call(
            s, "finish_session", idempotency_key="lifecycle-finish", session_id=sid,
            expected_revision=resume["revision"], perceived_effort=7,
            comments="Great workout via MCP",
        )
        assert finish["status"] == "COMPLETED"

        latest = await call(s, "get_latest_session")
        assert latest["session_id"] == sid
        assert latest["feedback"]["perceived_effort"] == 7
        summary = await call(s, "get_progress_summary")
        assert summary["consistency"]["completed_count"] == 1

    run_as(SUB_A, scenario=scenario)


@pytest.mark.django_db(transaction=True)
def test_abandon_session(alice: User, seed_catalog: None) -> None:
    async def scenario(s: ClientSession) -> None:
        routine = await accepted_routine(s, "abandon")
        prep = await call(
            s, "prepare_session", idempotency_key="abandon-prepare",
            routine_id=routine["routine_id"], routine_version=routine["version"],
        )
        start = await call(
            s, "start_session", idempotency_key="abandon-start",
            session_id=prep["session_id"], expected_revision=prep["revision"],
        )
        abandon = await call(
            s, "abandon_session", idempotency_key="abandon-abandon",
            session_id=start["session_id"], expected_revision=start["revision"],
        )
        assert abandon["status"] == "ABANDONED"

    run_as(SUB_A, scenario=scenario)


@pytest.mark.django_db(transaction=True)
def test_mutating_tools_reject_missing_or_blank_idempotency_keys(alice: User) -> None:
    async def scenario(s: ClientSession) -> None:
        # Omitted entirely: rejected by the tool's input schema.
        assert await call_error(s, "set_goal", description="x")
        assert await call_error(s, "propose_routine")
        # Present but blank or oversized: rejected by the tool.
        assert "idempotency_key" in await call_error(
            s, "update_profile", idempotency_key="   ", display_name="X"
        )
        assert "idempotency_key" in await call_error(
            s, "update_profile", idempotency_key="k" * 200, display_name="X"
        )

    run_as(SUB_A, scenario=scenario)
    assert GoalRevisionRecord.objects.count() == 0
    assert McpToolReceipt.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_tool_errors_are_reported_with_is_error(alice: User) -> None:
    async def scenario(s: ClientSession) -> None:
        result = await s.call_tool(
            "start_session",
            {"idempotency_key": "bad-1", "session_id": "not-a-uuid", "expected_revision": 1},
        )
        assert result.is_error is True

    run_as(SUB_A, scenario=scenario)


# --- Retry idempotency: the same command cannot create duplicate effects ---


@pytest.mark.django_db(transaction=True)
def test_set_goal_retry_replays_instead_of_adding_a_revision(alice: User) -> None:
    async def scenario(s: ClientSession) -> None:
        args = {"description": "Train 3x weekly", "baseline": 0.0, "target": 3.0}
        first = await call(s, "set_goal", idempotency_key="goal-retry", **args)
        second = await call(s, "set_goal", idempotency_key="goal-retry", **args)
        assert first == second
        assert len(await call(s, "list_goal_revisions")) == 1

        # The same key with different arguments is a conflict, not a replay.
        conflict = await call_error(
            s, "set_goal", idempotency_key="goal-retry", description="Different goal"
        )
        assert "IDEMPOTENCY_CONFLICT" in conflict
        assert len(await call(s, "list_goal_revisions")) == 1

        # A new key is a new command.
        await call(s, "set_goal", idempotency_key="goal-new", description="Second goal")
        assert len(await call(s, "list_goal_revisions")) == 2

    run_as(SUB_A, scenario=scenario)
    assert GoalRevisionRecord.objects.filter(owner_id=alice.id).count() == 2


@pytest.mark.django_db(transaction=True)
def test_concurrent_identical_set_goal_calls_have_one_effect(alice: User) -> None:
    async def scenario(s: ClientSession) -> None:
        results = await asyncio.gather(
            *[
                s.call_tool(
                    "set_goal", {"idempotency_key": "goal-race", "description": "Race goal"}
                )
                for _ in range(4)
            ]
        )
        assert len({json.dumps(result_payload(r), sort_keys=True) for r in results}) == 1

    run_as(SUB_A, scenario=scenario)
    assert GoalRevisionRecord.objects.filter(owner_id=alice.id).count() == 1


@pytest.mark.django_db(transaction=True)
def test_update_profile_retry_replays_the_first_response(alice: User) -> None:
    async def scenario(s: ClientSession) -> None:
        first = await call(
            s, "update_profile", idempotency_key="profile-retry", display_name="Retry"
        )
        second = await call(
            s, "update_profile", idempotency_key="profile-retry", display_name="Retry"
        )
        assert first == second  # including updated_at: the effect ran once

    run_as(SUB_A, scenario=scenario)
    assert McpToolReceipt.objects.filter(owner_id=alice.id, tool="update_profile").count() == 1


@pytest.mark.django_db(transaction=True)
def test_propose_and_accept_routine_retries_do_not_duplicate(
    alice: User, seed_catalog: None
) -> None:
    async def scenario(s: ClientSession) -> None:
        first = await call(s, "propose_routine", idempotency_key="propose-retry")
        second = await call(s, "propose_routine", idempotency_key="propose-retry")
        assert first == second

        args = {"routine_id": first["routine_id"], "version": first["version"]}
        accepted = await call(s, "accept_routine", idempotency_key="accept-retry", **args)
        again = await call(s, "accept_routine", idempotency_key="accept-retry", **args)
        assert accepted == again

    run_as(SUB_A, scenario=scenario)
    assert RoutineRecord.objects.filter(owner_id=alice.id).count() == 1


@pytest.mark.django_db(transaction=True)
def test_session_command_retries_replay_through_the_use_case(
    alice: User, seed_catalog: None
) -> None:
    async def scenario(s: ClientSession) -> None:
        routine = await accepted_routine(s, "session-retry")
        prepare_args = {
            "idempotency_key": "prepare-retry",
            "routine_id": routine["routine_id"],
            "routine_version": routine["version"],
        }
        prep = await call(s, "prepare_session", **prepare_args)
        assert await call(s, "prepare_session", **prepare_args) == prep

        sid, rev = prep["session_id"], prep["revision"]
        start_args = {"idempotency_key": "start-retry", "session_id": sid, "expected_revision": rev}
        start = await call(s, "start_session", **start_args)
        # The retry carries the original (now stale) expected_revision: it
        # must replay the original result, not fail or advance the session.
        assert await call(s, "start_session", **start_args) == start

        pause_args = {
            "idempotency_key": "pause-retry", "session_id": sid,
            "expected_revision": start["revision"],
        }
        pause = await call(s, "pause_session", **pause_args)
        assert await call(s, "pause_session", **pause_args) == pause

        resume_args = {
            "idempotency_key": "resume-retry", "session_id": sid,
            "expected_revision": pause["revision"],
        }
        resume = await call(s, "resume_session", **resume_args)
        assert await call(s, "resume_session", **resume_args) == resume

        finish_args = {
            "idempotency_key": "finish-retry", "session_id": sid,
            "expected_revision": resume["revision"], "perceived_effort": 6,
            "comments": "once",
        }
        finish = await call(s, "finish_session", **finish_args)
        assert await call(s, "finish_session", **finish_args) == finish

        latest = await call(s, "get_latest_session")
        assert latest["status"] == "COMPLETED"
        assert latest["feedback"] == {"perceived_effort": 6, "comments": "once"}
        assert latest["revision"] == finish["revision"]

    run_as(SUB_A, scenario=scenario)
    assert WorkoutSessionRecord.objects.filter(owner_id=alice.id).count() == 1


@pytest.mark.django_db(transaction=True)
def test_abandon_retry_replays(alice: User, seed_catalog: None) -> None:
    async def scenario(s: ClientSession) -> None:
        routine = await accepted_routine(s, "abandon-retry")
        prep = await call(
            s, "prepare_session", idempotency_key="ab-prep",
            routine_id=routine["routine_id"], routine_version=routine["version"],
        )
        args = {
            "idempotency_key": "ab-abandon", "session_id": prep["session_id"],
            "expected_revision": prep["revision"],
        }
        first = await call(s, "abandon_session", **args)
        assert await call(s, "abandon_session", **args) == first

    run_as(SUB_A, scenario=scenario)


@pytest.mark.django_db(transaction=True)
def test_same_idempotency_key_is_scoped_per_user(alice: User, bob: User) -> None:
    async def scenario(a: ClientSession, b: ClientSession) -> None:
        goal_a = await call(a, "set_goal", idempotency_key="shared-key", description="A goal")
        goal_b = await call(b, "set_goal", idempotency_key="shared-key", description="B goal")
        assert goal_a["description"] == "A goal"
        assert goal_b["description"] == "B goal"

    run_as(SUB_A, SUB_B, scenario=scenario)


# --- Cross-user isolation ---


@pytest.mark.django_db(transaction=True)
def test_users_only_see_and_control_their_own_data(
    alice: User, bob: User, seed_catalog: None
) -> None:
    photo = ProgressPhotoRecord.objects.create(
        owner=alice,
        session_id=None,
        s3_key=f"private/{alice.id}/{uuid4()}.jpg",
        content_type="image/jpeg",
        byte_length=1234,
        status="CONFIRMED",
    )

    async def scenario(a: ClientSession, b: ClientSession) -> None:
        # Alice builds up profile, goal, routine, session and progress.
        await call(a, "update_profile", idempotency_key="iso-a-profile", display_name="Alice")
        await call(a, "set_goal", idempotency_key="iso-a-goal", description="Alice goal")
        routine = await accepted_routine(a, "iso-a")
        prep = await call(
            a, "prepare_session", idempotency_key="iso-a-prep",
            routine_id=routine["routine_id"], routine_version=routine["version"],
        )
        start = await call(
            a, "start_session", idempotency_key="iso-a-start",
            session_id=prep["session_id"], expected_revision=prep["revision"],
        )
        finish = await call(
            a, "finish_session", idempotency_key="iso-a-finish",
            session_id=start["session_id"], expected_revision=start["revision"],
            perceived_effort=8, comments="Alice private note",
        )
        assert finish["status"] == "COMPLETED"

        # Bob sees none of it.
        bob_profile = await call(b, "get_profile")
        assert bob_profile["id"] == str(bob.id)
        assert bob_profile["display_name"] != "Alice"
        assert await call(b, "get_active_goal") is None
        assert await call(b, "list_goal_revisions") == []
        assert await call(b, "get_current_routine") is None
        assert await call(b, "get_latest_session") is None
        bob_progress = await call(b, "get_progress_summary")
        assert bob_progress["consistency"]["total_sessions"] == 0
        assert bob_progress["consistency"]["completed_count"] == 0
        assert bob_progress["performance_projections"] == []

        # Alice's data is intact and hers alone.
        assert (await call(a, "get_profile"))["display_name"] == "Alice"
        assert (await call(a, "get_progress_summary"))["consistency"]["completed_count"] == 1

        # Bob cannot act on Alice's routine or session, even knowing the ids.
        assert await call_error(
            b, "accept_routine", idempotency_key="iso-b-accept",
            routine_id=routine["routine_id"], version=routine["version"],
        )
        assert await call_error(
            b, "prepare_session", idempotency_key="iso-b-prepare",
            routine_id=routine["routine_id"], routine_version=routine["version"],
        )
        for tool in ("start_session", "pause_session", "resume_session", "abandon_session",
                     "finish_session"):
            assert await call_error(
                b, tool, idempotency_key=f"iso-b-{tool}", session_id=prep["session_id"],
                expected_revision=finish["revision"],
            ), tool
        latest = await call(a, "get_latest_session")
        assert latest["status"] == "COMPLETED"
        assert latest["feedback"]["comments"] == "Alice private note"

        # Media: no MCP tool exposes photos, so neither user can obtain
        # Alice's photo metadata or a signed URL through any output.
        tool_names = {t.name for t in (await b.list_tools()).tools}
        assert not any("photo" in name or "media" in name for name in tool_names)
        every_output = json.dumps(
            [
                await call(a, "get_profile"),
                await call(a, "get_latest_session"),
                await call(a, "get_progress_summary"),
                await call(b, "get_latest_session"),
                await call(b, "get_progress_summary"),
            ]
        )
        assert str(photo.id) not in every_output
        assert photo.s3_key not in every_output
        assert "X-Amz-Signature" not in every_output

    run_as(SUB_A, SUB_B, scenario=scenario)
    assert ProgressPhotoRecord.objects.filter(owner_id=alice.id).count() == 1
    assert not RoutineRecord.objects.filter(owner_id=bob.id).exists()
    assert not WorkoutSessionRecord.objects.filter(owner_id=bob.id).exists()
    assert not GoalRevisionRecord.objects.filter(owner_id=bob.id).exists()
