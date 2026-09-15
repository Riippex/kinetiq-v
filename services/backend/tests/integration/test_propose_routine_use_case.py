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
from kinetiq.modules.routines.application.propose_routine import ProposeRoutineUseCase
from kinetiq.modules.routines.domain.entities import RoutineEligibilityCriteria
from kinetiq.modules.routines.domain.errors import NoEligibleRoutineTemplatesError
from kinetiq.modules.routines.domain.provider import (
    CoachingProposalOutput,
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
