from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from kinetiq.modules.catalog.application.ports import CatalogRepository
from kinetiq.modules.goals.application.ports import GoalRepository
from kinetiq.modules.profiles.application.ports import ProfileRepository
from kinetiq.modules.profiles.domain.entities import ExperienceLevel, UserProfile
from kinetiq.modules.routines.application.ports import RoutineRepository
from kinetiq.modules.routines.domain.entities import (
    Routine,
    RoutineEligibilityCriteria,
    RoutineProposal,
)
from kinetiq.modules.routines.domain.errors import (
    NoEligibleRoutineTemplatesError,
)
from kinetiq.modules.routines.domain.filtering import filter_eligible_templates
from kinetiq.modules.routines.domain.provider import (
    DeterministicCoachingProvider,
    RoutineCoachingProvider,
    validate_coaching_output,
)
from kinetiq.modules.workouts.domain.session import CoachingTone


class ProposeRoutineUseCase:
    """Proposes an explained routine assembled from eligible catalog templates.

    1. Retrieves athlete's current profile and active goal.
    2. Deterministically filters catalog templates against equipment, duration, and goal.
    3. Invokes coaching provider for ranking and explanation.
    4. Validates provider output strictly against catalog rules, falling back safely.
    """

    def __init__(
        self,
        catalog_repo: CatalogRepository,
        profile_repo: ProfileRepository,
        goal_repo: GoalRepository,
        routine_repo: RoutineRepository | None = None,
        coaching_provider: RoutineCoachingProvider | None = None,
    ) -> None:
        self._catalog_repo = catalog_repo
        self._profile_repo = profile_repo
        self._goal_repo = goal_repo
        self._routine_repo = routine_repo
        self._coaching_provider = coaching_provider
        self._fallback_provider = DeterministicCoachingProvider()

    def execute(self, athlete_id: UUID) -> RoutineProposal:
        # 1. Resolve Profile
        profile = self._profile_repo.get_by_owner_id(athlete_id)
        if profile is None:
            profile = UserProfile(
                owner_id=athlete_id,
                display_name="Athlete",
                timezone="UTC",
                experience_level=ExperienceLevel.RETURNING,
                availability_days_per_week=3,
                target_session_minutes=15,
                available_equipment=("NONE",),
                workout_space="LIVING_ROOM",
                preferences=(),
                exclusions=(),
                limitations=(),
                coaching_tone=CoachingTone.CALM,
                updated_at=datetime.now(UTC),
            )

        # 2. Resolve Active Goal (optional target goal code if associated)
        active_goal = self._goal_repo.get_active_goal(athlete_id)
        target_goal_code = None
        if active_goal is not None:
            # Match against catalog goals if measure matches, or default habit goal
            catalog_goals = self._catalog_repo.list_goal_definitions()
            for cg in catalog_goals:
                if active_goal.measure and cg.measure == active_goal.measure:
                    target_goal_code = cg.code
                    break
            if target_goal_code is None and catalog_goals:
                target_goal_code = catalog_goals[0].code

        # 3. Build criteria
        criteria = RoutineEligibilityCriteria(
            available_equipment=frozenset(profile.available_equipment),
            target_duration_minutes=profile.target_session_minutes,
            experience_level=profile.experience_level.value,
            target_goal_code=target_goal_code,
            workout_space=profile.workout_space,
        )

        # 4. Fetch catalog templates and exercises
        templates = self._catalog_repo.list_routine_templates()
        exercises = self._catalog_repo.list_exercises()
        exercises_by_code = {ex.code: ex for ex in exercises}

        # 5. Deterministic eligibility filtering
        eligible_templates = filter_eligible_templates(templates, exercises_by_code, criteria)
        if not eligible_templates:
            raise NoEligibleRoutineTemplatesError(
                f"No catalog templates match criteria for athlete {athlete_id} "
                f"(equipment={sorted(criteria.available_equipment)}, "
                f"target_duration={criteria.target_duration_minutes}m)"
            )

        # 6. Constrained provider ranking & explanation with strict validation and safe fallback
        chosen_output = None
        if self._coaching_provider is not None:
            try:
                raw_output = self._coaching_provider.rank_and_explain(eligible_templates, criteria)
                chosen_output = validate_coaching_output(raw_output, eligible_templates)
            except Exception:
                chosen_output = None

        if chosen_output is None:
            chosen_output = self._fallback_provider.rank_and_explain(eligible_templates, criteria)

        # 7. Find selected template
        selected_template = next(
            t for t in eligible_templates if t.code == chosen_output.recommended_template_code
        )

        routine_id = uuid4()
        prescription: dict[str, object] = {
            "templateCode": selected_template.code,
            "templateVersion": selected_template.version,
            "estimatedDurationMinutes": selected_template.estimated_duration_minutes,
            "items": [
                {
                    "exerciseId": ex.code,
                    "exerciseVersion": ex.version,
                    "name": ex.name,
                    "visionSupported": ex.vision_supported,
                    "order": item.order,
                    "sets": item.sets,
                    "repetitions": item.repetitions,
                    "durationSeconds": item.duration_seconds,
                }
                for item in selected_template.items
                for ex in [exercises_by_code[item.exercise_code]]
            ],
        }

        if self._routine_repo is not None:
            routine = Routine(
                id=uuid4(),
                routine_id=routine_id,
                owner_id=athlete_id,
                version=1,
                title=selected_template.title,
                rationale=chosen_output.rationale,
                prescription=prescription,
                accepted=False,
                created_at=datetime.now(UTC),
            )
            self._routine_repo.save(routine)

        return RoutineProposal(
            proposal_id=uuid4(),
            athlete_id=athlete_id,
            template_code=selected_template.code,
            template_version=selected_template.version,
            title=selected_template.title,
            description=selected_template.description,
            estimated_duration_minutes=selected_template.estimated_duration_minutes,
            items=selected_template.items,
            rationale=chosen_output.rationale,
            created_at=datetime.now(UTC),
            routine_id=routine_id,
            version=1,
            accepted=False,
        )
