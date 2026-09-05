# Kinetiq V Coaching Experience

## Purpose

Help users turn a fitness goal into an evolving routine, complete sessions with support, and understand their progress over time. The product relationship continues between workouts and across devices.

## Routine Creation and Adaptation

Proposed inputs include the user's goal, experience, available equipment, available time, preferred schedule, exercise preferences, and self-reported limitations. Later suggestions can also use completed sessions, skipped exercises, perceived effort, user feedback, and supported movement observations.

Explain why a routine was suggested and let the user edit or accept it. Preserve routine versions so historical sessions retain the prescription actually used. Missing history should lead to onboarding questions or an explicit initial assumption, not invented personalization. Exact exercise selection and progression rules require design and validation.

Track workout performance and progress toward the goal separately. Completing sessions is useful evidence of consistency, but does not by itself establish that every goal has been achieved. Select relevant progress measures with the user, distinguish measured data from self-reports and estimates, and do not promise outcomes from unsupported observations.

## Session and Follow-up Journey

1. **Set context:** capture a goal and enough preferences to suggest an initial routine.
2. **Prepare:** use the phone-first preparation flow to review the accepted routine, choose Normal or Dynamic mode, set session-level coaching and intensity, and select a camera and display. The TV offers reduced remote-friendly controls.
3. **Train:** the phone coordinates capture. Vision returns timestamped movement observations and confidence. Kinetiq V manages the routine, session, displays, and coaching decisions.
4. **Close:** save completed activity and supported observations; ask for optional effort and session feedback. Keep partial sessions and missing analysis distinguishable from completed, measured activity.
5. **Capture an optional progress photo:** offer an explicit capture step after each session. Allow skipping, preview, retake, and deletion. Never silently capture or publish an image.
6. **Review:** show the session summary, trends, goal progress, and optional chronological photo comparisons.
7. **Continue between sessions:** Alexa+ can retrieve authorized history, discuss the goal, suggest the next routine, and update preferences without an active Fire TV or browser session. Keep relevant state in the backend so this does not depend on a display remaining open.

## Progress Photos

Photos are a private, user-controlled visual diary associated with the user, capture time, and optionally a session. Consistent framing and lighting can be suggested to make comparisons useful. Appearance changes are not automatic proof of fitness improvement; body composition or medical conclusions from images are outside the agreed scope.

Store image objects privately and keep references and metadata in the product database. Define access, retention, and deletion before implementation. Camera access for workout analysis does not authorize a progress photo or permanent video retention. Sharing image content with an assistant requires appropriate user authorization and a supported client path; routine voice follow-up should work from structured progress data without fetching private images.

## Alexa+ and Runtime MCP

The product MCP exposes authenticated, user-scoped business capabilities for profiles, goals, routine suggestions and versions, sessions, progress, and preferences. It does not expose unrestricted database queries. Clients and Alexa+ must use the same business rules and persistent records.

The intended experience includes follow-up outside an active workout. User-initiated conversations are distinct from proactive reminders or unsolicited speech. Validate the platform's scheduling, notification, media, and voice capabilities before promising proactive behavior. A running MCP server alone does not provide proactive delivery. Reminder preferences and permissions must be explicit if that capability is implemented.

Kinetiq V owns profiles, goals and goal revisions, routine versions, workout sessions, user feedback, progress measurements, private photo references, and coaching preferences. The database and storage services remain undecided.

Vision owns perception and temporal movement analysis. It receives the exercise configuration needed for analysis and returns supported observations, timestamps, confidence, and visibility states. It does not generate personalized workout plans, store progress photos, or determine whether a user's long-term goal has been achieved.

Use documented simulators or test environments for Fire TV, Ring, and Alexa+ where available; their setup and supported behaviors still need verification. Record whether each demonstration uses live hardware, an official simulator, or a local mock. Mocked behavior is not evidence that an external integration works.

Proposed first complete implementation slice: goal and onboarding context → proposed routine → phone-camera session with browser feedback → saved results and optional photo → progress view and next-session suggestion. This establishes the coaching loop before expanding device integrations; it does not reduce the intended product to a repetition counter. Add Alexa+ access to the same records and validate Fire TV and Ring as subsequent integration milestones.

Next design work: define the initial supported goal and exercise set, routine-selection rules, product entities, and a versioned product–Vision contract including interrupted streams and insufficient visibility. Choose AWS services and scoped deployment permissions against those concrete needs.

## Confirmed Target and Visibility UX

At session start, the user selects and confirms their person region in a live preview. This is session-specific tracking, not biometric account verification. Only the selected person's observations contribute to the workout; other people and animals must be excluded and evaluated as distractors.

Vision reports tracking state, evidence freshness, and reason codes. The product preserves confirmed results, explains visibility loss, and pauses affected exercise progression after a short grace interval; ambiguous identity pauses immediately and requires confirmation. Cached state supports continuity but cannot stand in for unseen motion. Following a pause, offer resume after fresh stable evidence. Retain saved results when the tracking context expires. Exact timers are proposed in the Vision repository's docs/session-target-tracking.md and require evaluation. The enrollment preview is separate from the optional post-session photo; it need not be saved.

See [session preparation and Dynamic mode](session-preparation.md) for the pre-session configuration snapshot, bounded challenge behavior, and phone/TV control split.
