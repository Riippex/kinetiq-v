from collections.abc import Sequence
from uuid import uuid4

import pytest

from kinetiq.modules.catalog.application.seed_catalog import SeedCatalogUseCase
from kinetiq.modules.catalog.domain.entities import RoutineTemplate, RoutineTemplateItem
from kinetiq.modules.catalog.infrastructure.canonical_data import (
    CANONICAL_EXERCISES,
    CANONICAL_GOALS,
    CANONICAL_TEMPLATES,
)
from kinetiq.modules.catalog.infrastructure.models import RoutineTemplateRecord
from kinetiq.modules.catalog.infrastructure.repositories import DjangoCatalogRepository
from kinetiq.modules.catalog.infrastructure.vision_contract_adapter import (
    FileBasedVisionCapabilities,
)
from kinetiq.modules.goals.application.set_goal import SetGoalCommand, SetGoalUseCase
from kinetiq.modules.goals.infrastructure.repositories import DjangoGoalRepository
from kinetiq.modules.identity.infrastructure.models import User
from kinetiq.modules.profiles.application.get_profile import GetProfileUseCase
from kinetiq.modules.profiles.application.update_profile import (
    UpdateProfileCommand,
    UpdateProfileUseCase,
)
from kinetiq.modules.profiles.infrastructure.repositories import DjangoProfileRepository
from kinetiq.modules.progress.application.get_progress_summary import GetProgressSummaryUseCase
from kinetiq.modules.progress.infrastructure.repositories import (
    DjangoGoalLookup,
    DjangoProfileLookup,
    DjangoSessionHistoryLookup,
)
from kinetiq.modules.routines.application.propose_routine import ProposeRoutineUseCase
from kinetiq.modules.routines.domain.entities import RoutineEligibilityCriteria
from kinetiq.modules.routines.domain.errors import (
    NoEligibleRoutineTemplatesError,
    UnsupportedLimitationError,
)
from kinetiq.modules.routines.domain.provider import (
    CoachingProposalOutput,
)
from kinetiq.modules.routines.infrastructure.models import RoutineRecord
from kinetiq.modules.workouts.infrastructure.models import (
    ObservationCoverageRecord,
    PerformedSetRecord,
    WorkoutSessionRecord,
)


class MockLLMProvider:
    def __init__(self, template_code: str, rationale: str) -> None:
        self.template_code = template_code
        self.rationale = rationale

    def rank_and_explain(
        self,
        eligible_templates: Sequence[RoutineTemplate],
        criteria: RoutineEligibilityCriteria,
    ) -> CoachingProposalOutput:
        return CoachingProposalOutput(
            recommended_template_code=self.template_code,
            rationale=self.rationale,
        )


@pytest.fixture
def catalog_seeded() -> DjangoCatalogRepository:
    repo = DjangoCatalogRepository()
    vision = FileBasedVisionCapabilities()
    SeedCatalogUseCase(catalog_repo=repo, vision_capabilities=vision).execute(
        goals=CANONICAL_GOALS,
        exercises=CANONICAL_EXERCISES,
        templates=CANONICAL_TEMPLATES,
    )
    return repo


@pytest.mark.django_db
def test_propose_routine_with_deterministic_provider(
    catalog_seeded: DjangoCatalogRepository,
) -> None:
    profile_repo = DjangoProfileRepository()
    goal_repo = DjangoGoalRepository()

    user = User.objects.create_user(
        email=f"athlete-{uuid4()}@example.com",
        username=f"athlete-{uuid4()}",
    )
    athlete_id = user.id

    # 1. Initialize profile
    GetProfileUseCase(profile_repo).execute(athlete_id, default_display_name="Test Athlete")

    # 2. Set goal
    SetGoalUseCase(goal_repo).execute(
        owner_id=athlete_id,
        command=SetGoalCommand(
            description="Build daily movement consistency",
            measure="weekly_completed_sessions",
            baseline=0.0,
            target=3.0,
            unit="sessions/week",
        ),
    )

    use_case = ProposeRoutineUseCase(
        catalog_repo=catalog_seeded,
        profile_repo=profile_repo,
        goal_repo=goal_repo,
    )

    proposal = use_case.execute(athlete_id)

    assert proposal.athlete_id == athlete_id
    assert proposal.template_code == "template-full-body-foundation-v1"
    assert proposal.template_version == 1
    assert proposal.title == "Full Body Foundation"
    assert proposal.estimated_duration_minutes == 15
    assert len(proposal.items) == 4
    assert "Full Body Foundation" in proposal.rationale
    assert "returning" in proposal.rationale.lower()


@pytest.mark.django_db
def test_propose_routine_with_valid_external_provider(
    catalog_seeded: DjangoCatalogRepository,
) -> None:
    profile_repo = DjangoProfileRepository()
    goal_repo = DjangoGoalRepository()

    user = User.objects.create_user(
        email=f"athlete-{uuid4()}@example.com",
        username=f"athlete-{uuid4()}",
    )
    athlete_id = user.id
    GetProfileUseCase(profile_repo).execute(athlete_id)

    mock_provider = MockLLMProvider(
        template_code="template-full-body-foundation-v1",
        rationale="AI coach recommendation: balanced push/squat/plank flow for returning athletes.",
    )

    use_case = ProposeRoutineUseCase(
        catalog_repo=catalog_seeded,
        profile_repo=profile_repo,
        goal_repo=goal_repo,
        coaching_provider=mock_provider,
    )

    proposal = use_case.execute(athlete_id)
    assert proposal.template_code == "template-full-body-foundation-v1"
    assert "AI coach recommendation" in proposal.rationale


@pytest.mark.django_db
def test_propose_routine_recovers_from_hallucinated_template_code(
    catalog_seeded: DjangoCatalogRepository,
) -> None:
    profile_repo = DjangoProfileRepository()
    goal_repo = DjangoGoalRepository()

    user = User.objects.create_user(
        email=f"athlete-{uuid4()}@example.com",
        username=f"athlete-{uuid4()}",
    )
    athlete_id = user.id
    GetProfileUseCase(profile_repo).execute(athlete_id)

    # Provider hallucinated an invalid template code
    hallucinating_provider = MockLLMProvider(
        template_code="template-hallucinated-advanced-crossfit-v99",
        rationale="You should try this extreme high intensity workout instead!",
    )

    use_case = ProposeRoutineUseCase(
        catalog_repo=catalog_seeded,
        profile_repo=profile_repo,
        goal_repo=goal_repo,
        coaching_provider=hallucinating_provider,
    )

    # Must fall back gracefully to the deterministic catalog template
    proposal = use_case.execute(athlete_id)
    assert proposal.template_code == "template-full-body-foundation-v1"
    assert "Full Body Foundation" in proposal.rationale


@pytest.mark.django_db
def test_propose_routine_raises_when_no_templates_eligible(
    catalog_seeded: DjangoCatalogRepository,
) -> None:
    profile_repo = DjangoProfileRepository()
    goal_repo = DjangoGoalRepository()

    user = User.objects.create_user(
        email=f"athlete-{uuid4()}@example.com",
        username=f"athlete-{uuid4()}",
    )
    athlete_id = user.id
    GetProfileUseCase(profile_repo).execute(athlete_id)

    # Replace catalog templates with one requiring PULL_UP_BAR
    RoutineTemplateRecord.objects.all().delete()
    catalog_seeded.save_routine_template(
        RoutineTemplate(
            code="template-only-pullups",
            version=1,
            title="Pull-ups only",
            description="Bar only",
            target_goal_code="goal-habit-consistency-v1",
            estimated_duration_minutes=20,
            items=(
                RoutineTemplateItem(
                    exercise_code="exercise-pull-up-v1",
                    order=1,
                    sets=3,
                    repetitions=5,
                ),
            ),
        )
    )

    # Athlete only has NONE available
    UpdateProfileUseCase(profile_repo).execute(
        owner_id=athlete_id,
        command=UpdateProfileCommand(
            available_equipment=["NONE"],
        ),
    )

    use_case = ProposeRoutineUseCase(
        catalog_repo=catalog_seeded,
        profile_repo=profile_repo,
        goal_repo=goal_repo,
    )

    with pytest.raises(NoEligibleRoutineTemplatesError) as exc:
        use_case.execute(athlete_id)
    assert "No catalog templates match criteria" in str(exc.value)


@pytest.mark.django_db
def test_propose_routine_excludes_templates_with_excluded_exercise(
    catalog_seeded: DjangoCatalogRepository,
) -> None:
    """Regression test: an athlete's explicit exclusion must prevent the
    excluded catalog exercise from appearing in a proposed routine."""
    profile_repo = DjangoProfileRepository()
    goal_repo = DjangoGoalRepository()

    user = User.objects.create_user(
        email=f"athlete-{uuid4()}@example.com",
        username=f"athlete-{uuid4()}",
    )
    athlete_id = user.id
    GetProfileUseCase(profile_repo).execute(athlete_id)

    # The only canonical template includes push-up; excluding it must leave
    # no eligible template rather than silently including the exercise.
    UpdateProfileUseCase(profile_repo).execute(
        owner_id=athlete_id,
        command=UpdateProfileCommand(exclusions=("exercise-push-up-v1",)),
    )

    use_case = ProposeRoutineUseCase(
        catalog_repo=catalog_seeded,
        profile_repo=profile_repo,
        goal_repo=goal_repo,
    )

    with pytest.raises(NoEligibleRoutineTemplatesError) as exc:
        use_case.execute(athlete_id)
    assert "exercise-push-up-v1" in str(exc.value)


@pytest.mark.django_db
def test_propose_routine_free_text_exclusion_is_never_inferred(
    catalog_seeded: DjangoCatalogRepository,
) -> None:
    """Exclusions are normalized against stable catalog identifiers only: a
    free-text medical description must not be matched to any exercise, so the
    proposal proceeds unaffected instead of guessing at intent."""
    profile_repo = DjangoProfileRepository()
    goal_repo = DjangoGoalRepository()

    user = User.objects.create_user(
        email=f"athlete-{uuid4()}@example.com",
        username=f"athlete-{uuid4()}",
    )
    athlete_id = user.id
    GetProfileUseCase(profile_repo).execute(athlete_id)

    UpdateProfileUseCase(profile_repo).execute(
        owner_id=athlete_id,
        command=UpdateProfileCommand(exclusions=("no push ups because of my shoulder",)),
    )

    use_case = ProposeRoutineUseCase(
        catalog_repo=catalog_seeded,
        profile_repo=profile_repo,
        goal_repo=goal_repo,
    )

    proposal = use_case.execute(athlete_id)
    assert proposal.template_code == "template-full-body-foundation-v1"


@pytest.mark.django_db
def test_propose_routine_raises_unsupported_limitation_error(
    catalog_seeded: DjangoCatalogRepository,
) -> None:
    """Regression test: a self-reported limitation must never be silently
    ignored. With no catalog template declaring an adaptation for it, the
    domain must raise a clear, distinct error rather than proceed unsafely."""
    profile_repo = DjangoProfileRepository()
    goal_repo = DjangoGoalRepository()

    user = User.objects.create_user(
        email=f"athlete-{uuid4()}@example.com",
        username=f"athlete-{uuid4()}",
    )
    athlete_id = user.id
    GetProfileUseCase(profile_repo).execute(athlete_id)

    UpdateProfileUseCase(profile_repo).execute(
        owner_id=athlete_id,
        command=UpdateProfileCommand(limitations=("KNEE_PAIN",)),
    )

    use_case = ProposeRoutineUseCase(
        catalog_repo=catalog_seeded,
        profile_repo=profile_repo,
        goal_repo=goal_repo,
    )

    with pytest.raises(UnsupportedLimitationError) as exc:
        use_case.execute(athlete_id)
    assert "KNEE_PAIN" in str(exc.value)


@pytest.mark.django_db
def test_propose_routine_reflects_real_session_without_false_goal_achievement(
    catalog_seeded: DjangoCatalogRepository,
) -> None:
    """A real saved session must change the coaching rationale's
    goal-progress note, and that note must state the real (partial)
    progress ratio -- never overstate it as fully achieved."""
    profile_repo = DjangoProfileRepository()
    goal_repo = DjangoGoalRepository()

    user = User.objects.create_user(
        email=f"athlete-{uuid4()}@example.com",
        username=f"athlete-{uuid4()}",
    )
    athlete_id = user.id
    GetProfileUseCase(profile_repo).execute(athlete_id)

    # Goal tracks real push-up reps: 0 -> 50.
    SetGoalUseCase(goal_repo).execute(
        owner_id=athlete_id,
        command=SetGoalCommand(
            description="Reach 50 push-up reps",
            measure="exercise-push-up-v1",
            baseline=0.0,
            target=50.0,
            unit="reps",
        ),
    )

    progress_summary_use_case = GetProgressSummaryUseCase(
        session_history_lookup=DjangoSessionHistoryLookup(),
        profile_lookup=DjangoProfileLookup(),
        goal_lookup=DjangoGoalLookup(),
    )

    use_case = ProposeRoutineUseCase(
        catalog_repo=catalog_seeded,
        profile_repo=profile_repo,
        goal_repo=goal_repo,
        progress_summary_use_case=progress_summary_use_case,
    )

    # 1. Before any session has ever been saved, there is no evidence to back
    # a goal-progress claim, so none must be made.
    baseline_proposal = use_case.execute(athlete_id)
    assert "of your active goal" not in baseline_proposal.rationale

    # 2. Save a real completed session with 20 push-up reps.
    routine_row = RoutineRecord.objects.create(
        id=uuid4(),
        routine_id=uuid4(),
        owner=user,
        title="Ad-hoc",
        version=1,
        prescription={},
    )
    session = WorkoutSessionRecord.objects.create(
        id=uuid4(),
        owner=user,
        routine=routine_row,
        revision=1,
        state="COMPLETED",
        configuration={},
    )
    PerformedSetRecord.objects.create(
        session=session,
        exercise_id="exercise-push-up-v1",
        set_order=1,
        repetitions=20,
    )
    ObservationCoverageRecord.objects.create(
        session=session,
        coverage_ratio=0.9,
        tracked_seconds=540,
        total_seconds=600,
    )

    # 3. The next proposal must reflect this real, partial progress: 20 of
    # 50 reps is 40% -- not "achieved" and not fabricated.
    updated_proposal = use_case.execute(athlete_id)
    assert "40% of your active goal" in updated_proposal.rationale
    assert "100% of your active goal" not in updated_proposal.rationale


@pytest.mark.django_db
def test_propose_routine_uses_real_onboarding_goal_weekly_completed_sessions(
    catalog_seeded: DjangoCatalogRepository,
) -> None:
    """Recheck with the goal onboarding actually creates
    (`weekly_completed_sessions`): completed sessions this week drive the
    stated progress, and nothing is claimed before any session exists."""
    profile_repo = DjangoProfileRepository()
    goal_repo = DjangoGoalRepository()

    user = User.objects.create_user(
        email=f"athlete-{uuid4()}@example.com",
        username=f"athlete-{uuid4()}",
    )
    athlete_id = user.id
    GetProfileUseCase(profile_repo).execute(athlete_id)
    SetGoalUseCase(goal_repo).execute(
        owner_id=athlete_id,
        command=SetGoalCommand(
            description="Build daily movement consistency",
            measure="weekly_completed_sessions",
            baseline=0.0,
            target=3.0,
            unit="sessions/week",
        ),
    )

    use_case = ProposeRoutineUseCase(
        catalog_repo=catalog_seeded,
        profile_repo=profile_repo,
        goal_repo=goal_repo,
        progress_summary_use_case=GetProgressSummaryUseCase(
            session_history_lookup=DjangoSessionHistoryLookup(),
            profile_lookup=DjangoProfileLookup(),
            goal_lookup=DjangoGoalLookup(),
        ),
    )

    assert "of your active goal" not in use_case.execute(athlete_id).rationale

    routine_id = uuid4()
    routine_row = RoutineRecord.objects.create(
        id=routine_id, routine_id=routine_id, owner=user, title="R", version=1, prescription={}
    )
    for _ in range(2):
        WorkoutSessionRecord.objects.create(
            id=uuid4(),
            owner=user,
            routine=routine_row,
            revision=1,
            state="COMPLETED",
            configuration={},
        )

    rationale = use_case.execute(athlete_id).rationale
    assert "67% of your active goal" in rationale
    assert "100% of your active goal" not in rationale
