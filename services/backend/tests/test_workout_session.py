import unittest
from uuid import uuid4

from kinetiq.modules.workouts.domain import (
    CoachingTone,
    DynamicChallengeFrequency,
    DynamicChallengeType,
    DynamicSessionConfiguration,
    InvalidSessionStateTransition,
    ObservationCoverage,
    PauseReason,
    PerformedSet,
    SessionConfiguration,
    SessionFeedback,
    SessionIntensity,
    SessionMode,
    SessionState,
    WorkoutSession,
)


def dynamic_configuration() -> DynamicSessionConfiguration:
    return DynamicSessionConfiguration(
        frequency=DynamicChallengeFrequency.STANDARD,
        allowed_challenge_types=(
            DynamicChallengeType.HOLD_POSE,
            DynamicChallengeType.QUICK_REPS,
        ),
        scoring_enabled=True,
        narration_enabled=True,
        policy_version=1,
        random_seed=uuid4(),
    )


def session_configuration(mode: SessionMode) -> SessionConfiguration:
    return SessionConfiguration(
        requested_mode=mode,
        active_mode=mode,
        intensity=SessionIntensity.PLANNED,
        coaching_tone=CoachingTone.MOTIVATIONAL,
        capture_device_id="phone-camera",
        display_device_id="living-room-tv",
        prompt_for_progress_photo=True,
        dynamic=dynamic_configuration() if mode is SessionMode.DYNAMIC else None,
    )


def prepared_session(mode: SessionMode) -> WorkoutSession:
    return WorkoutSession.prepare(
        session_id=uuid4(),
        owner_id=uuid4(),
        routine_id=uuid4(),
        routine_version=3,
        configuration=session_configuration(mode),
    )


class SessionPreparationTests(unittest.TestCase):
    def test_preparation_snapshots_the_routine_and_configuration(self) -> None:
        session = prepared_session(SessionMode.DYNAMIC)

        self.assertEqual(SessionState.READY, session.state)
        self.assertEqual(3, session.routine_version)
        self.assertEqual(SessionMode.DYNAMIC, session.configuration.requested_mode)
        self.assertEqual(1, session.revision)

    def test_dynamic_mode_requires_dynamic_configuration(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires Dynamic configuration"):
            SessionConfiguration(
                requested_mode=SessionMode.DYNAMIC,
                active_mode=SessionMode.DYNAMIC,
                intensity=SessionIntensity.PLANNED,
                coaching_tone=CoachingTone.CALM,
                capture_device_id="phone-camera",
                display_device_id=None,
                prompt_for_progress_photo=False,
                dynamic=None,
            )

    def test_preparation_cannot_begin_with_dynamic_already_disabled(self) -> None:
        configuration = session_configuration(SessionMode.DYNAMIC)
        configuration = SessionConfiguration(
            requested_mode=configuration.requested_mode,
            active_mode=SessionMode.NORMAL,
            intensity=configuration.intensity,
            coaching_tone=configuration.coaching_tone,
            capture_device_id=configuration.capture_device_id,
            display_device_id=configuration.display_device_id,
            prompt_for_progress_photo=configuration.prompt_for_progress_photo,
            dynamic=configuration.dynamic,
        )

        with self.assertRaisesRegex(ValueError, "must begin in its requested mode"):
            WorkoutSession.prepare(
                session_id=uuid4(),
                owner_id=uuid4(),
                routine_id=uuid4(),
                routine_version=1,
                configuration=configuration,
            )

    def test_normal_mode_rejects_dynamic_configuration(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot include Dynamic configuration"):
            SessionConfiguration(
                requested_mode=SessionMode.NORMAL,
                active_mode=SessionMode.NORMAL,
                intensity=SessionIntensity.PLANNED,
                coaching_tone=CoachingTone.CALM,
                capture_device_id="phone-camera",
                display_device_id=None,
                prompt_for_progress_photo=False,
                dynamic=dynamic_configuration(),
            )

    def test_dynamic_mode_can_be_disabled_without_losing_requested_mode(self) -> None:
        active = prepared_session(SessionMode.DYNAMIC).start()

        normal = active.disable_dynamic_mode()

        self.assertEqual(SessionMode.DYNAMIC, normal.configuration.requested_mode)
        self.assertEqual(SessionMode.NORMAL, normal.configuration.active_mode)
        self.assertEqual(active.revision + 1, normal.revision)

    def test_normal_session_cannot_gain_dynamic_mode_after_start(self) -> None:
        active = prepared_session(SessionMode.NORMAL).start()

        unchanged = active.disable_dynamic_mode()

        self.assertIs(active, unchanged)
        self.assertEqual(SessionMode.NORMAL, unchanged.configuration.active_mode)

    def test_start_transitions_ready_session_to_active(self) -> None:
        ready = prepared_session(SessionMode.NORMAL)
        active = ready.start()

        self.assertEqual(SessionState.ACTIVE, active.state)
        self.assertEqual(ready.revision + 1, active.revision)
        self.assertIsNone(active.pause_reason)

    def test_start_rejects_non_ready_session(self) -> None:
        active = prepared_session(SessionMode.NORMAL).start()

        with self.assertRaises(InvalidSessionStateTransition):
            active.start()

    def test_pause_transitions_active_session_with_reason(self) -> None:
        active = prepared_session(SessionMode.DYNAMIC).start()
        paused = active.pause(reason=PauseReason.VISIBILITY)

        self.assertEqual(SessionState.PAUSED, paused.state)
        self.assertEqual(active.revision + 1, paused.revision)
        self.assertEqual(PauseReason.VISIBILITY, paused.pause_reason)

    def test_pause_rejects_non_active_session(self) -> None:
        ready = prepared_session(SessionMode.NORMAL)
        with self.assertRaises(InvalidSessionStateTransition):
            ready.pause()

    def test_resume_transitions_paused_session_and_clears_reason(self) -> None:
        active = prepared_session(SessionMode.NORMAL).start()
        paused = active.pause(reason=PauseReason.USER_REQUEST)
        resumed = paused.resume()

        self.assertEqual(SessionState.ACTIVE, resumed.state)
        self.assertEqual(paused.revision + 1, resumed.revision)
        self.assertIsNone(resumed.pause_reason)

    def test_resume_rejects_non_paused_session(self) -> None:
        active = prepared_session(SessionMode.NORMAL).start()
        with self.assertRaises(InvalidSessionStateTransition):
            active.resume()

    def test_disable_dynamic_mode_during_paused_state(self) -> None:
        active = prepared_session(SessionMode.DYNAMIC).start()
        paused = active.pause()
        normal_paused = paused.disable_dynamic_mode()

        self.assertEqual(SessionState.PAUSED, normal_paused.state)
        self.assertEqual(SessionMode.NORMAL, normal_paused.configuration.active_mode)
        self.assertEqual(paused.revision + 1, normal_paused.revision)

    def test_finish_transitions_active_or_paused_session_to_completed(self) -> None:
        active = prepared_session(SessionMode.NORMAL).start()
        completed_from_active = active.finish()
        self.assertEqual(SessionState.COMPLETED, completed_from_active.state)
        self.assertEqual(active.revision + 1, completed_from_active.revision)

        paused = prepared_session(SessionMode.NORMAL).start().pause()
        completed_from_paused = paused.finish()
        self.assertEqual(SessionState.COMPLETED, completed_from_paused.state)
        self.assertEqual(paused.revision + 1, completed_from_paused.revision)

    def test_finish_rejects_ready_or_completed_session(self) -> None:
        ready = prepared_session(SessionMode.NORMAL)
        with self.assertRaises(InvalidSessionStateTransition):
            ready.finish()

        completed = ready.start().finish()
        with self.assertRaises(InvalidSessionStateTransition):
            completed.finish()

    def test_abandon_transitions_ready_active_or_paused_session(self) -> None:
        ready = prepared_session(SessionMode.NORMAL)
        abandoned_ready = ready.abandon()
        self.assertEqual(SessionState.ABANDONED, abandoned_ready.state)
        self.assertEqual(ready.revision + 1, abandoned_ready.revision)

        active = prepared_session(SessionMode.NORMAL).start()
        abandoned_active = active.abandon()
        self.assertEqual(SessionState.ABANDONED, abandoned_active.state)

        paused = prepared_session(SessionMode.NORMAL).start().pause()
        abandoned_paused = paused.abandon()
        self.assertEqual(SessionState.ABANDONED, abandoned_paused.state)

    def test_abandon_rejects_completed_or_already_abandoned_session(self) -> None:
        completed = prepared_session(SessionMode.NORMAL).start().finish()
        with self.assertRaises(InvalidSessionStateTransition):
            completed.abandon()

        abandoned = prepared_session(SessionMode.NORMAL).abandon()
        with self.assertRaises(InvalidSessionStateTransition):
            abandoned.abandon()

    def test_finish_records_performed_sets_coverage_and_feedback(self) -> None:
        session = prepared_session(SessionMode.NORMAL).start()
        sets = (
            PerformedSet(exercise_id="exercise-push-up-v1", set_order=1, repetitions=12),
            PerformedSet(exercise_id="exercise-push-up-v1", set_order=2, repetitions=10),
            PerformedSet(exercise_id="exercise-plank-v1", set_order=1, duration_seconds=60),
        )
        coverage = ObservationCoverage(
            coverage_ratio=0.92,
            tracked_seconds=120,
            total_seconds=130,
            fully_visible_ratio=0.88,
            untracked_reasons=("OCCLUDED",),
        )
        feedback = SessionFeedback(perceived_effort=8, comments="Challenging set")

        completed = session.finish(
            performed_sets=sets,
            observation_coverage=coverage,
            feedback=feedback,
        )

        self.assertEqual(SessionState.COMPLETED, completed.state)
        self.assertEqual(22, completed.confirmed_repetitions)
        self.assertEqual(3, len(completed.performed_sets))
        self.assertIsNotNone(completed.observation_coverage)
        self.assertEqual(0.92, completed.observation_coverage.coverage_ratio)
        self.assertIsNotNone(completed.feedback)
        self.assertEqual(8, completed.feedback.perceived_effort)
        self.assertEqual("Challenging set", completed.feedback.comments)

    def test_record_feedback_updates_completed_session(self) -> None:
        completed = prepared_session(SessionMode.NORMAL).start().finish()
        self.assertIsNone(completed.feedback)

        updated = completed.record_feedback(
            SessionFeedback(perceived_effort=7, comments="Felt good")
        )
        self.assertEqual(completed.revision + 1, updated.revision)
        self.assertIsNotNone(updated.feedback)
        self.assertEqual(7, updated.feedback.perceived_effort)
        self.assertEqual("Felt good", updated.feedback.comments)

    def test_record_feedback_rejects_non_completed_session(self) -> None:
        active = prepared_session(SessionMode.NORMAL).start()
        with self.assertRaises(InvalidSessionStateTransition):
            active.record_feedback(SessionFeedback(perceived_effort=5))

    def test_session_feedback_validates_effort_range(self) -> None:
        with self.assertRaises(ValueError):
            SessionFeedback(perceived_effort=0)
        with self.assertRaises(ValueError):
            SessionFeedback(perceived_effort=11)
        with self.assertRaises(ValueError):
            SessionFeedback(perceived_effort=-1)

        valid = SessionFeedback(perceived_effort=1)
        self.assertEqual(1, valid.perceived_effort)
        valid10 = SessionFeedback(perceived_effort=10)
        self.assertEqual(10, valid10.perceived_effort)

    def test_performed_set_and_coverage_validation(self) -> None:
        with self.assertRaises(ValueError):
            PerformedSet(exercise_id="", set_order=1)
        with self.assertRaises(ValueError):
            PerformedSet(exercise_id="pushups", set_order=0)
        with self.assertRaises(ValueError):
            PerformedSet(exercise_id="pushups", set_order=1, repetitions=-1)
        with self.assertRaises(ValueError):
            ObservationCoverage(coverage_ratio=1.5, tracked_seconds=10, total_seconds=10)
        with self.assertRaises(ValueError):
            ObservationCoverage(coverage_ratio=-0.1, tracked_seconds=10, total_seconds=10)


if __name__ == "__main__":
    unittest.main()
