from __future__ import annotations

import random
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import NAMESPACE_DNS, UUID, uuid5

if TYPE_CHECKING:
    from kinetiq.modules.workouts.application.ports import AcceptedRoutineItem

from kinetiq.modules.workouts.domain.session import (
    DynamicChallengeFrequency,
    DynamicChallengeType,
    SessionMode,
    WorkoutSession,
)


class DynamicChallengeStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"


class UnknownDynamicChallengeError(ValueError):
    """Raised when a client attempts to skip a challenge_id that is not
    among the challenges the policy currently generates for this session
    -- i.e. an arbitrary or stale ID rather than one the athlete was
    actually shown."""

    def __init__(self, challenge_id: object) -> None:
        super().__init__(
            f"Challenge '{challenge_id}' is not among the currently generated "
            "challenges for this session"
        )
        self.challenge_id = challenge_id


@dataclass(frozen=True, slots=True)
class DynamicChallenge:
    challenge_id: UUID
    challenge_type: DynamicChallengeType
    exercise_id: str
    target_value: int
    description: str
    set_order: int
    status: DynamicChallengeStatus = DynamicChallengeStatus.PENDING

    def __post_init__(self) -> None:
        if not self.exercise_id.strip():
            raise ValueError("Exercise ID cannot be empty")
        if self.set_order < 1:
            raise ValueError("Set order must be at least 1")
        if self.target_value < 1:
            raise ValueError("Target value must be positive")

    def skip(self) -> DynamicChallenge:
        """Mark this challenge as skipped. Skip has zero penalty and does not
        alter workout performance data or confirmed repetitions."""
        return replace(self, status=DynamicChallengeStatus.SKIPPED)


class DynamicChallengePolicy:
    """Versioned, deterministic generator for Dynamic workout challenges.

    Scoped honestly to generation and skip only: this policy produces the
    challenge list a session should currently see and lets one be marked
    skipped. It has no evidence-based completion path -- nothing in this
    codebase inspects Vision observations to decide a challenge's target
    was actually met, so DynamicChallengeStatus.COMPLETED is defined for a
    future pass but never produced today. Treat "not skipped" as "still
    pending", not as "done"."""

    def __init__(self, version: int = 1) -> None:
        if version < 1:
            raise ValueError("Policy version must be positive")
        self.version = version

    def generate_challenges(
        self,
        *,
        session: WorkoutSession,
        accepted_routine_items: tuple[AcceptedRoutineItem, ...],
        user_exclusions: tuple[str, ...] = (),
    ) -> tuple[DynamicChallenge, ...]:
        # session.configuration.dynamic is never cleared by
        # disable_dynamic_mode() (only active_mode flips to NORMAL, so the
        # configuration can be re-enabled later) -- checking dynamic is
        # None alone would keep issuing challenges for a session that
        # disabled Dynamic mid-workout. active_mode is the live switch.
        if (
            session.configuration.dynamic is None
            or session.configuration.active_mode is not SessionMode.DYNAMIC
        ):
            return ()

        dynamic_config = session.configuration.dynamic
        allowed_types = dynamic_config.allowed_challenge_types
        if not allowed_types:
            return ()

        # Normalize user exclusions for lookup
        exclusion_set = {ex.strip().lower() for ex in user_exclusions if ex.strip()}
        eligible_items = [
            item
            for item in accepted_routine_items
            if item.exercise_id.strip().lower() not in exclusion_set
        ]

        if not eligible_items:
            return ()

        # Deterministic seed combining session random seed, policy version, and session ID
        seed_str = f"{dynamic_config.random_seed}:{self.version}:{session.id}"
        rng = random.Random(seed_str)

        frequency = dynamic_config.frequency
        total_items = len(eligible_items)
        if frequency == DynamicChallengeFrequency.LOW:
            count = 1
        elif frequency == DynamicChallengeFrequency.HIGH:
            count = total_items
        else:  # STANDARD
            count = max(1, (total_items + 1) // 2)

        count = min(count, total_items)
        selected_items = rng.sample(eligible_items, count)
        # Sort by their set order / index in the routine to maintain logical order
        selected_items.sort(key=lambda item: accepted_routine_items.index(item))

        challenges: list[DynamicChallenge] = []
        for idx, item in enumerate(selected_items):
            c_type = rng.choice(allowed_types)
            set_order = accepted_routine_items.index(item) + 1

            if c_type == DynamicChallengeType.HOLD_POSE:
                target_value = rng.choice([5, 10, 15])
                description = f"Hold {item.exercise_id} pose for {target_value} seconds"
            elif c_type == DynamicChallengeType.MIRROR_POSE:
                target_value = rng.choice([5, 8, 10])
                description = f"Mirror {item.exercise_id} reference pose for {target_value} seconds"
            elif c_type == DynamicChallengeType.QUICK_REPS:
                target_value = rng.choice([3, 5, 8])
                description = f"Perform {target_value} quick reps of {item.exercise_id}"
            else:  # RECOVERY
                target_value = rng.choice([15, 20, 30])
                description = (
                    f"Take a {target_value} second recovery pause before {item.exercise_id}"
                )

            # Deterministic UUID for the challenge
            challenge_uuid = uuid5(
                NAMESPACE_DNS, f"{seed_str}:{item.exercise_id}:{set_order}:{idx}"
            )

            challenges.append(
                DynamicChallenge(
                    challenge_id=challenge_uuid,
                    challenge_type=c_type,
                    exercise_id=item.exercise_id,
                    target_value=target_value,
                    description=description,
                    set_order=set_order,
                    status=DynamicChallengeStatus.PENDING,
                )
            )

        return tuple(challenges)
