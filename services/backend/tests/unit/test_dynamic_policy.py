from uuid import UUID, uuid4

from kinetiq.modules.workouts.application.ports import AcceptedRoutineItem
from kinetiq.modules.workouts.domain import (
    CoachingTone,
    DynamicChallengeFrequency,
    DynamicChallengePolicy,
    DynamicChallengeStatus,
    DynamicChallengeType,
    DynamicSessionConfiguration,
    SessionConfiguration,
    SessionIntensity,
    SessionMode,
    WorkoutSession,
)


def make_dynamic_session(
    seed: UUID | None = None,
    frequency: DynamicChallengeFrequency = DynamicChallengeFrequency.STANDARD,
    allowed_types: tuple[DynamicChallengeType, ...] = (
        DynamicChallengeType.HOLD_POSE,
        DynamicChallengeType.MIRROR_POSE,
        DynamicChallengeType.QUICK_REPS,
        DynamicChallengeType.RECOVERY,
    ),
) -> WorkoutSession:
    seed = seed or UUID("11111111-2222-3333-4444-555555555555")
    dynamic_cfg = DynamicSessionConfiguration(
        frequency=frequency,
        allowed_challenge_types=allowed_types,
        scoring_enabled=True,
        narration_enabled=True,
        policy_version=1,
        random_seed=seed,
    )
    config = SessionConfiguration(
        requested_mode=SessionMode.DYNAMIC,
        active_mode=SessionMode.DYNAMIC,
        intensity=SessionIntensity.PLANNED,
        coaching_tone=CoachingTone.CALM,
        capture_device_id="cam-1",
        display_device_id=None,
        prompt_for_progress_photo=True,
        dynamic=dynamic_cfg,
    )
    return WorkoutSession.prepare(
        session_id=uuid4(),
        owner_id=uuid4(),
        routine_id=uuid4(),
        routine_version=1,
        configuration=config,
    )


def test_dynamic_policy_seed_determinism() -> None:
    session = make_dynamic_session()
    routine_items = (
        AcceptedRoutineItem(exercise_id="ex-pushup", repetitions=10, duration_seconds=None),
        AcceptedRoutineItem(exercise_id="ex-squat", repetitions=15, duration_seconds=None),
        AcceptedRoutineItem(exercise_id="ex-plank", repetitions=None, duration_seconds=30),
    )

    policy = DynamicChallengePolicy(version=1)
    gen1 = policy.generate_challenges(session=session, accepted_routine_items=routine_items)
    gen2 = policy.generate_challenges(session=session, accepted_routine_items=routine_items)

    assert len(gen1) > 0
    assert gen1 == gen2


def test_dynamic_policy_filters_user_exclusions() -> None:
    session = make_dynamic_session()
    routine_items = (
        AcceptedRoutineItem(exercise_id="ex-pushup", repetitions=10, duration_seconds=None),
        AcceptedRoutineItem(exercise_id="ex-burpee", repetitions=5, duration_seconds=None),
    )

    policy = DynamicChallengePolicy(version=1)

    # Exclude burpees
    challenges = policy.generate_challenges(
        session=session,
        accepted_routine_items=routine_items,
        user_exclusions=("ex-burpee",),
    )

    assert len(challenges) > 0
    for c in challenges:
        assert c.exercise_id != "ex-burpee"
        assert c.exercise_id == "ex-pushup"


def test_dynamic_policy_frequency_levels() -> None:
    routine_items = tuple(
        AcceptedRoutineItem(exercise_id=f"ex-{i}", repetitions=10, duration_seconds=None)
        for i in range(6)
    )
    policy = DynamicChallengePolicy(version=1)

    session_low = make_dynamic_session(frequency=DynamicChallengeFrequency.LOW)
    challenges_low = policy.generate_challenges(
        session=session_low, accepted_routine_items=routine_items
    )
    assert len(challenges_low) == 1

    session_high = make_dynamic_session(frequency=DynamicChallengeFrequency.HIGH)
    challenges_high = policy.generate_challenges(
        session=session_high, accepted_routine_items=routine_items
    )
    assert len(challenges_high) == 6


def test_dynamic_policy_stops_issuing_after_dynamic_disabled() -> None:
    session = make_dynamic_session().start()
    disabled_session = session.disable_dynamic_mode()
    assert disabled_session.configuration.dynamic is not None
    assert disabled_session.configuration.active_mode == SessionMode.NORMAL

    routine_items = (
        AcceptedRoutineItem(exercise_id="ex-pushup", repetitions=10, duration_seconds=None),
    )
    policy = DynamicChallengePolicy(version=1)
    challenges = policy.generate_challenges(
        session=disabled_session, accepted_routine_items=routine_items
    )

    assert challenges == ()


def test_challenge_skip_has_no_penalty() -> None:
    session = make_dynamic_session()
    routine_items = (
        AcceptedRoutineItem(exercise_id="ex-pushup", repetitions=10, duration_seconds=None),
    )
    policy = DynamicChallengePolicy(version=1)
    challenges = policy.generate_challenges(session=session, accepted_routine_items=routine_items)
    assert len(challenges) == 1

    challenge = challenges[0]
    assert challenge.status == DynamicChallengeStatus.PENDING

    skipped = challenge.skip()
    assert skipped.status == DynamicChallengeStatus.SKIPPED

    # Invariant: session confirmed_repetitions and performed_sets are completely untouched
    assert session.confirmed_repetitions == 0
    assert session.performed_sets == ()
