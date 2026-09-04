# Business Event Contract v1

Design contract; transport and consumers are not implemented.

Envelope: event_id (UUID), event_type (versioned name), schema_version, occurred_at (UTC), producer, aggregate_type, aggregate_id, aggregate_version (positive integer), correlation_id, causation_id, payload. All fields are required; causation_id may be null for a root action. ID and versions are preserved across retries. EventBridge transports this envelope in detail; its own event ID is not our idempotency key.

| Event | Producer | Payload | Consumer effect |
|---|---|---|---|
| WorkoutSessionCompleted.v1 | workouts | session_id, user_id, routine_version_id | progress recomputes from committed data; coaching may draft a suggestion |
| GoalChanged.v1 | goals | goal_id, user_id, revision | invalidate progress and draft recommendations |
| RoutineAccepted.v1 | routines | routine_id, user_id, version | update the product's planned-routine projection |
| ProgressSummaryUpdated.v1 | progress | user_id, projection_revision | invalidate summary cache; ephemeral UI notification |
| ProgressPhotoDeleted.v1 | media | photo_id, user_id | idempotent object cleanup through private media metadata |

Payload identifiers do not authorize actions: consumers use scoped service permissions and ownership checks. Keep private content out of envelopes. On photo deletion, persist a tombstone and private object key for cleanup; revoke access immediately and retain enough metadata to retry deletion until successful. Do not remove the only cleanup pointer first.

Version-breaking changes create a new event type and migration window. Consumers reject unsupported versions to a diagnosable failure path. Persistent inbox receipts prevent duplicate database effects. Replay retains event_id and is audited. Do not recycle IDs to force reprocessing; use explicit repair operations where needed.
