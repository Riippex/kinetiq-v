"""MCP tools exposing Kinetiq product use cases to Alexa+.

Every tool resolves its owner from the validated bearer token (never from a
tool argument), and every mutating tool requires a caller-provided
`idempotency_key` so a retried command cannot repeat its effect.

Progress photos are intentionally not exposed: a photo tool would hand a
signed object URL to a third party, which needs a separate, explicitly
authorized photo-sharing flow.
"""

import functools
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from asgiref.sync import sync_to_async
from mcp.server.mcpserver.exceptions import ToolError

from kinetiq.bootstrap.container import (
    abandon_workout_session,
    accept_routine,
    finish_workout_session,
    get_active_goal,
    get_current_routine,
    get_profile,
    get_progress_summary,
    get_workout_session,
    list_goal_revisions,
    pause_workout_session,
    prepare_workout_session,
    propose_routine,
    record_session_feedback,
    resume_workout_session,
    set_goal,
    start_workout_session,
    update_profile,
)
from kinetiq.interfaces.mcp.auth import AuthenticationRequiredError, resolve_mcp_owner_id
from kinetiq.interfaces.mcp.idempotency import (
    IdempotencyConflictError,
    run_idempotent,
    validate_idempotency_key,
)
from kinetiq.modules.goals.application import SetGoalCommand
from kinetiq.modules.profiles.application import UpdateProfileCommand
from kinetiq.modules.profiles.domain.entities import ExperienceLevel, UserProfile
from kinetiq.modules.routines.domain.errors import RoutineDomainError
from kinetiq.modules.workouts.application import (
    FinishSessionCommand,
    PrepareSessionCommand,
    RecordSessionFeedbackCommand,
    SessionLifecycleCommand,
)
from kinetiq.modules.workouts.domain import SessionIntensity, SessionMode
from kinetiq.modules.workouts.domain.session import CoachingTone, SessionFeedback, WorkoutSession
from kinetiq.modules.workouts.infrastructure.models import WorkoutSessionRecord

# Anticipated business failures (not found, stale revision, invalid input,
# idempotency conflicts) reach the caller as readable tool errors; anything
# else is treated by the SDK as a crash and reported generically.
_EXPECTED_FAILURES = (
    ValueError,
    RoutineDomainError,
    AuthenticationRequiredError,
    IdempotencyConflictError,
)


def tool_errors[**P, R](func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await func(*args, **kwargs)
        except _EXPECTED_FAILURES as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


async def _owner_id() -> UUID:
    return await sync_to_async(resolve_mcp_owner_id, thread_sensitive=True)()


async def _idempotent(
    owner_id: UUID,
    tool: str,
    idempotency_key: str,
    payload: dict[str, Any],
    effect: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    return await sync_to_async(run_idempotent, thread_sensitive=True)(
        owner_id=owner_id, tool=tool, key=idempotency_key, payload=payload, effect=effect
    )


def _profile_payload(profile: UserProfile) -> dict[str, Any]:
    return {
        "id": str(profile.owner_id),
        "display_name": profile.display_name,
        "experience_level": profile.experience_level.value,
        "availability_days_per_week": profile.availability_days_per_week,
        "target_session_minutes": profile.target_session_minutes,
        "available_equipment": list(profile.available_equipment),
        "workout_space": profile.workout_space,
        "preferences": list(profile.preferences),
        "exclusions": list(profile.exclusions),
        "limitations": list(profile.limitations),
        "coaching_tone": profile.coaching_tone.value,
        "updated_at": profile.updated_at.isoformat(),
    }


def _goal_payload(goal: Any) -> dict[str, Any]:
    return {
        "goal_id": str(goal.goal_id),
        "description": goal.description,
        "measure": goal.measure,
        "baseline": goal.baseline,
        "target": goal.target,
        "unit": goal.unit,
        "created_at": goal.created_at.isoformat(),
    }


def _session_payload(session: WorkoutSession) -> dict[str, Any]:
    return {
        "session_id": str(session.id),
        "status": session.state.value,
        "revision": session.revision,
    }


# --- Profile Tools ---


@tool_errors
async def mcp_get_profile() -> dict[str, Any]:
    """Retrieve the authenticated athlete's profile and coaching preferences."""
    owner_id = await _owner_id()
    profile = await sync_to_async(get_profile().execute, thread_sensitive=True)(owner_id)
    return _profile_payload(profile)


@tool_errors
async def mcp_update_profile(
    idempotency_key: str,
    display_name: str | None = None,
    coaching_tone: str | None = None,
    experience_level: str | None = None,
    availability_days_per_week: int | None = None,
    target_session_minutes: int | None = None,
    available_equipment: list[str] | None = None,
    workout_space: str | None = None,
    preferences: list[str] | None = None,
    exclusions: list[str] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    """Update profile attributes and coaching preferences for the authenticated athlete.

    `idempotency_key` is required; retrying with the same key repeats no effect.
    """
    validate_idempotency_key(idempotency_key)
    owner_id = await _owner_id()

    command = UpdateProfileCommand(
        display_name=display_name,
        experience_level=ExperienceLevel(experience_level.upper()) if experience_level else None,
        availability_days_per_week=availability_days_per_week,
        target_session_minutes=target_session_minutes,
        available_equipment=tuple(available_equipment) if available_equipment is not None else None,
        workout_space=workout_space,
        preferences=tuple(preferences) if preferences is not None else None,
        exclusions=tuple(exclusions) if exclusions is not None else None,
        limitations=tuple(limitations) if limitations is not None else None,
        coaching_tone=CoachingTone(coaching_tone.upper()) if coaching_tone else None,
    )

    def effect() -> dict[str, Any]:
        return _profile_payload(update_profile().execute(owner_id, command))

    payload = {
        "display_name": display_name,
        "coaching_tone": coaching_tone,
        "experience_level": experience_level,
        "availability_days_per_week": availability_days_per_week,
        "target_session_minutes": target_session_minutes,
        "available_equipment": available_equipment,
        "workout_space": workout_space,
        "preferences": preferences,
        "exclusions": exclusions,
        "limitations": limitations,
    }
    return await _idempotent(owner_id, "update_profile", idempotency_key, payload, effect)


# --- Goal Tools ---


@tool_errors
async def mcp_get_active_goal() -> dict[str, Any] | None:
    """Retrieve the athlete's active consistency or performance goal."""
    owner_id = await _owner_id()
    goal = await sync_to_async(get_active_goal().execute, thread_sensitive=True)(owner_id)
    return None if goal is None else _goal_payload(goal)


@tool_errors
async def mcp_list_goal_revisions() -> list[dict[str, Any]]:
    """List historical goal revisions in chronological order."""
    owner_id = await _owner_id()
    revisions = await sync_to_async(list_goal_revisions().execute, thread_sensitive=True)(owner_id)
    return [_goal_payload(rev) for rev in revisions]


@tool_errors
async def mcp_set_goal(
    idempotency_key: str,
    description: str,
    measure: str | None = None,
    baseline: float | None = None,
    target: float | None = None,
    unit: str | None = None,
) -> dict[str, Any]:
    """Set or update the athlete's active goal with measurable baseline and target.

    `idempotency_key` is required; retrying with the same key adds no new goal revision.
    """
    validate_idempotency_key(idempotency_key)
    owner_id = await _owner_id()
    command = SetGoalCommand(
        description=description, measure=measure, baseline=baseline, target=target, unit=unit
    )

    def effect() -> dict[str, Any]:
        return _goal_payload(set_goal().execute(owner_id, command))

    payload = {
        "description": description,
        "measure": measure,
        "baseline": baseline,
        "target": target,
        "unit": unit,
    }
    return await _idempotent(owner_id, "set_goal", idempotency_key, payload, effect)


# --- Routine & Coaching Tools ---


@tool_errors
async def mcp_get_current_routine() -> dict[str, Any] | None:
    """Retrieve the athlete's currently accepted routine version."""
    owner_id = await _owner_id()
    routine = await sync_to_async(get_current_routine().execute, thread_sensitive=True)(owner_id)
    if routine is None:
        return None

    items: list[Any] = []
    if isinstance(routine.prescription, dict):
        raw_items = routine.prescription.get("items", [])
        if isinstance(raw_items, list):
            items = raw_items

    return {
        "routine_id": str(routine.routine_id),
        "title": routine.title,
        "version": routine.version,
        "status": "ACCEPTED" if routine.accepted else "PROPOSED",
        "items": items,
    }


@tool_errors
async def mcp_propose_routine(idempotency_key: str) -> dict[str, Any]:
    """Generate an explained routine proposal from goals, exclusions, limitations and progress.

    `idempotency_key` is required; retrying with the same key returns the same
    proposal instead of saving another one.
    """
    validate_idempotency_key(idempotency_key)
    owner_id = await _owner_id()

    def effect() -> dict[str, Any]:
        proposal = propose_routine().execute(owner_id)
        return {
            "routine_id": str(proposal.routine_id or proposal.proposal_id),
            "title": proposal.title,
            "version": proposal.version,
            "rationale": proposal.rationale,
            "items": [
                {
                    "exercise_id": item.exercise_code,
                    "order": item.order,
                    "sets": item.sets,
                    "repetitions": item.repetitions,
                    "duration_seconds": item.duration_seconds,
                }
                for item in proposal.items
            ],
        }

    return await _idempotent(owner_id, "propose_routine", idempotency_key, {}, effect)


@tool_errors
async def mcp_accept_routine(idempotency_key: str, routine_id: str, version: int) -> dict[str, Any]:
    """Accept a proposed routine version, making it the active immutable routine version.

    `idempotency_key` is required; retrying with the same key repeats no effect.
    """
    validate_idempotency_key(idempotency_key)
    owner_id = await _owner_id()
    routine_uuid = UUID(routine_id)

    def effect() -> dict[str, Any]:
        routine = accept_routine().execute(owner_id, routine_uuid, version)
        return {
            "routine_id": str(routine.routine_id),
            "title": routine.title,
            "version": routine.version,
            "status": "ACCEPTED" if routine.accepted else "PROPOSED",
        }

    payload = {"routine_id": str(routine_uuid), "version": version}
    return await _idempotent(owner_id, "accept_routine", idempotency_key, payload, effect)


# --- Workout Session Tools ---


def _sync_get_latest_session(owner_id: UUID) -> dict[str, Any] | None:
    latest_record = (
        WorkoutSessionRecord.objects.filter(owner_id=owner_id)
        .order_by("-updated_at", "-created_at")
        .first()
    )
    if latest_record is None:
        return None
    session = get_workout_session().execute(owner_id=owner_id, session_id=latest_record.id)
    if session is None:
        return None
    return {
        "session_id": str(session.id),
        "routine_id": str(session.routine_id),
        "routine_version": session.routine_version,
        "status": session.state.value,
        "active_mode": session.configuration.active_mode.value,
        "revision": session.revision,
        "confirmed_repetitions": session.confirmed_repetitions,
        "performed_sets": [
            {
                "exercise_id": s.exercise_id,
                "set_order": s.set_order,
                "repetitions": s.repetitions,
                "duration_seconds": s.duration_seconds,
            }
            for s in session.performed_sets
        ],
        "feedback": (
            {
                "perceived_effort": session.feedback.perceived_effort,
                "comments": session.feedback.comments,
            }
            if session.feedback
            else None
        ),
    }


@tool_errors
async def mcp_get_latest_session() -> dict[str, Any] | None:
    """Retrieve the athlete's most recent workout session details, state, and results."""
    owner_id = await _owner_id()
    return await sync_to_async(_sync_get_latest_session, thread_sensitive=True)(owner_id)


@tool_errors
async def mcp_prepare_session(
    idempotency_key: str,
    routine_id: str,
    routine_version: int,
    mode: str = "NORMAL",
    coaching_tone: str = "CALM",
    capture_device_id: str = "mobile-primary",
    display_device_id: str | None = None,
) -> dict[str, Any]:
    """Prepare a workout session snapshot from an accepted routine version.

    `idempotency_key` is required and is passed to the session use case, so a
    retry returns the same session instead of preparing another.
    """
    key = validate_idempotency_key(idempotency_key)
    owner_id = await _owner_id()
    command = PrepareSessionCommand(
        routine_id=UUID(routine_id),
        routine_version=routine_version,
        mode=SessionMode(mode.upper()),
        coaching_tone=CoachingTone(coaching_tone.upper()),
        intensity=SessionIntensity.PLANNED,
        capture_device_id=capture_device_id,
        display_device_id=display_device_id,
        prompt_for_progress_photo=False,
        idempotency_key=key,
    )
    session = await sync_to_async(prepare_workout_session().execute, thread_sensitive=True)(
        owner_id=owner_id, command=command
    )
    return _session_payload(session)


async def _lifecycle(
    use_case_factory: Callable[[], Any],
    idempotency_key: str,
    session_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    key = validate_idempotency_key(idempotency_key)
    owner_id = await _owner_id()
    command = SessionLifecycleCommand(
        session_id=UUID(session_id),
        expected_revision=expected_revision,
        idempotency_key=key,
    )
    session = await sync_to_async(use_case_factory().execute, thread_sensitive=True)(
        owner_id=owner_id, command=command
    )
    return _session_payload(session)


@tool_errors
async def mcp_start_session(
    idempotency_key: str, session_id: str, expected_revision: int
) -> dict[str, Any]:
    """Start a prepared or paused workout session. `idempotency_key` is required."""
    return await _lifecycle(start_workout_session, idempotency_key, session_id, expected_revision)


@tool_errors
async def mcp_pause_session(
    idempotency_key: str, session_id: str, expected_revision: int
) -> dict[str, Any]:
    """Pause an active workout session. `idempotency_key` is required."""
    return await _lifecycle(pause_workout_session, idempotency_key, session_id, expected_revision)


@tool_errors
async def mcp_resume_session(
    idempotency_key: str, session_id: str, expected_revision: int
) -> dict[str, Any]:
    """Resume a paused workout session. `idempotency_key` is required."""
    return await _lifecycle(resume_workout_session, idempotency_key, session_id, expected_revision)


@tool_errors
async def mcp_abandon_session(
    idempotency_key: str, session_id: str, expected_revision: int
) -> dict[str, Any]:
    """Abandon a workout session without recording completed activity.

    `idempotency_key` is required.
    """
    return await _lifecycle(
        abandon_workout_session, idempotency_key, session_id, expected_revision
    )


@tool_errors
async def mcp_finish_session(
    idempotency_key: str,
    session_id: str,
    expected_revision: int,
    perceived_effort: int | None = None,
    comments: str | None = None,
) -> dict[str, Any]:
    """Finish an active workout session, optionally recording perceived effort and comments.

    `idempotency_key` is required; optional feedback is recorded under a key
    derived from it, so a retry repeats neither the finish nor the feedback.
    """
    key = validate_idempotency_key(idempotency_key)
    owner_id = await _owner_id()
    command = FinishSessionCommand(
        session_id=UUID(session_id),
        expected_revision=expected_revision,
        idempotency_key=key,
        performed_sets=(),
    )
    session = await sync_to_async(finish_workout_session().execute, thread_sensitive=True)(
        owner_id=owner_id, command=command
    )

    if perceived_effort is not None or comments is not None:
        feedback_command = RecordSessionFeedbackCommand(
            session_id=UUID(session_id),
            # Finishing advances the revision by exactly one. Deriving the
            # feedback revision from the request (not from the possibly
            # replayed finish result) keeps a retried command identical.
            expected_revision=expected_revision + 1,
            idempotency_key=f"{key}:feedback",
            feedback=SessionFeedback(perceived_effort=perceived_effort, comments=comments),
        )
        session = await sync_to_async(record_session_feedback().execute, thread_sensitive=True)(
            owner_id=owner_id, command=feedback_command
        )

    return _session_payload(session)


# --- Progress Tools ---


@tool_errors
async def mcp_get_progress_summary(days: int = 30) -> dict[str, Any]:
    """Review consistency, performance trends, and goal progress over the past N days."""
    owner_id = await _owner_id()
    to_date = datetime.now(UTC)
    from_date = to_date - timedelta(days=max(1, min(days, 365)))
    summary = await sync_to_async(get_progress_summary().execute, thread_sensitive=True)(
        owner_id=owner_id, from_date=from_date, to_date=to_date
    )
    goal = summary.goal_progress
    return {
        "from_date": summary.from_date.isoformat(),
        "to_date": summary.to_date.isoformat(),
        "consistency": {
            "total_sessions": summary.consistency.total_sessions,
            "planned_sessions": summary.consistency.planned_sessions,
            "consistency_ratio": summary.consistency.consistency_ratio,
            "current_streak_days": summary.consistency.current_streak_days,
            "completed_count": summary.consistency.completed_count,
            "abandoned_count": summary.consistency.abandoned_count,
            "skipped_count": summary.consistency.skipped_count,
        },
        "performance_projections": [
            {
                "exercise_id": p.exercise_id,
                "exercise_name": p.exercise_name,
                "measured_volume": p.measured_volume,
                "self_reported_volume": p.self_reported_volume,
                "estimated_1rm": p.estimated_1rm,
                "evidence_source": p.evidence_source.value,
                "trend": p.trend.value,
            }
            for p in summary.performance_projections
        ],
        "goal_progress": (
            {
                "goal_id": str(goal.goal_id) if goal.goal_id else None,
                "description": goal.description,
                "baseline": goal.baseline,
                "target": goal.target,
                "current_value": goal.current_value,
                "unit": goal.unit,
                "progress_ratio": goal.progress_ratio,
                "evidence_source": goal.evidence_source.value,
            }
            if goal
            else None
        ),
    }
