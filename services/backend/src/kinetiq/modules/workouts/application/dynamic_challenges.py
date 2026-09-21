from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from kinetiq.modules.workouts.application.ports import (
    RoutineItemLookup,
    SessionLifecycleRepository,
    UserProfileLookup,
)
from kinetiq.modules.workouts.application.session_lifecycle import SessionNotFound
from kinetiq.modules.workouts.domain import (
    DynamicChallenge,
    DynamicChallengePolicy,
    DynamicChallengeStatus,
    UnknownDynamicChallengeError,
    WorkoutSession,
)


class GetSessionDynamicChallengesUseCase:
    def __init__(
        self,
        session_repo: SessionLifecycleRepository,
        routine_lookup: RoutineItemLookup,
        user_profile_lookup: UserProfileLookup | None = None,
    ) -> None:
        self._session_repo = session_repo
        self._routine_lookup = routine_lookup
        self._user_profile_lookup = user_profile_lookup

    def execute(self, *, owner_id: UUID, session_id: UUID) -> tuple[DynamicChallenge, ...]:
        session = self._session_repo.get_session(owner_id=owner_id, session_id=session_id)
        if session is None:
            raise SessionNotFound(f"Session '{session_id}' not found")

        if session.configuration.dynamic is None:
            return ()

        items = self._routine_lookup.get_accepted_routine_items(
            owner_id=owner_id,
            routine_id=session.routine_id,
            version=session.routine_version,
        )
        if not items:
            return ()

        exclusions = (
            self._user_profile_lookup.get_user_exclusions(owner_id=owner_id)
            if self._user_profile_lookup is not None
            else ()
        )

        policy = DynamicChallengePolicy(version=session.configuration.dynamic.policy_version)
        challenges = policy.generate_challenges(
            session=session,
            accepted_routine_items=items,
            user_exclusions=exclusions,
        )

        if not session.skipped_challenge_ids:
            return challenges

        skipped_set = set(session.skipped_challenge_ids)
        return tuple(
            replace(c, status=DynamicChallengeStatus.SKIPPED)
            if str(c.challenge_id) in skipped_set
            else c
            for c in challenges
        )


class SkipDynamicChallengeUseCase:
    def __init__(
        self,
        session_repo: SessionLifecycleRepository,
        routine_lookup: RoutineItemLookup,
        user_profile_lookup: UserProfileLookup | None = None,
    ) -> None:
        self._session_repo = session_repo
        self._routine_lookup = routine_lookup
        self._user_profile_lookup = user_profile_lookup

    def execute(
        self,
        *,
        owner_id: UUID,
        session_id: UUID,
        expected_revision: int,
        challenge_id: UUID,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> tuple[DynamicChallenge, ...]:
        def _transition(s: WorkoutSession) -> WorkoutSession:
            current_ids: set[UUID] = set()
            items = self._routine_lookup.get_accepted_routine_items(
                owner_id=owner_id,
                routine_id=s.routine_id,
                version=s.routine_version,
            )
            if s.configuration.dynamic is not None and items:
                exclusions = (
                    self._user_profile_lookup.get_user_exclusions(owner_id=owner_id)
                    if self._user_profile_lookup is not None
                    else ()
                )
                policy = DynamicChallengePolicy(version=s.configuration.dynamic.policy_version)
                challenges = policy.generate_challenges(
                    session=s,
                    accepted_routine_items=items,
                    user_exclusions=exclusions,
                )
                current_ids = {c.challenge_id for c in challenges}
            if challenge_id not in current_ids:
                raise UnknownDynamicChallengeError(challenge_id)
            return s.skip_challenge(challenge_id)

        session = self._session_repo.apply_transition(
            owner_id=owner_id,
            session_id=session_id,
            expected_revision=expected_revision,
            operation="workouts.skip_challenge",
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            transition=_transition,
        )

        items = self._routine_lookup.get_accepted_routine_items(
            owner_id=owner_id,
            routine_id=session.routine_id,
            version=session.routine_version,
        )
        if not items or session.configuration.dynamic is None:
            return ()

        exclusions = (
            self._user_profile_lookup.get_user_exclusions(owner_id=owner_id)
            if self._user_profile_lookup is not None
            else ()
        )

        policy = DynamicChallengePolicy(version=session.configuration.dynamic.policy_version)
        challenges = policy.generate_challenges(
            session=session,
            accepted_routine_items=items,
            user_exclusions=exclusions,
        )

        skipped_set = set(session.skipped_challenge_ids)
        return tuple(
            replace(c, status=DynamicChallengeStatus.SKIPPED)
            if str(c.challenge_id) in skipped_set
            else c
            for c in challenges
        )
