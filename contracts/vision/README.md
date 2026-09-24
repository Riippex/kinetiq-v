# Vision Contract v1

This contract defines the boundary between the Kinetiq V product backend and the independent `kinetiq-v-vision` service.

## Principles

1. **Explicit Capabilities:** The product never assumes an exercise or metric is vision-tracked. An exercise is only marked `visionSupported: true` in the product catalog if it is explicitly declared and validated in `contracts/vision/v1/fixtures/capabilities.v1.json`.
2. **Single Target Identity:** Tracking is bound to an active `session_id`, `epoch`, and `target_person_id`. Distractors or other people in the camera frame never contribute observations to the workout session.
3. **Pausable Integrity:** When visibility is lost (`OUT_OF_FRAME`, `OCCLUSION`) or ambiguity is detected (`TARGET_AMBIGUOUS`), the Vision service emits the corresponding reason code. The product backend pauses progression without erasing confirmed repetitions.
4. **Explicit Enrollment:** The phone captures one ephemeral JPEG/PNG still, Product verifies session ownership, and Vision returns normalized person boxes. A human selects the session target; pixels are not treated as identity and are not persisted by this flow.

## Structure

- `contracts/vision/v1/schema/`:
  - `vision-capabilities.v1.schema.json`: JSON Schema (Draft 2020-12) for the Vision service capability declaration.
  - `vision-observation.v1.schema.json`: JSON Schema (Draft 2020-12) for timestamped observation events.
- `contracts/vision/v1/fixtures/`:
  - `capabilities.v1.json`: Declared supported exercises (`bodyweight_squat`, `push_up`, `plank`, `glute_bridge`).
  - `observation_repetition.v1.json`: Confirmed repetition observation fixture.
  - `observation_hold.v1.json`: Confirmed isometric hold observation fixture.
  - `observation_target_ambiguous.v1.json`: Target ambiguity reason code fixture.
  - `observation_visibility_lost.v1.json`: Visibility loss reason code fixture.
