# Initial Audience and Routine Planning

## Accepted Product Direction

Start with people returning to exercise at home who want to build consistency with little equipment. This is the initial audience, not a permanent limit on the product.

Create recommendations from an exercise catalog and defined routine templates. AI helps select, adapt, and explain eligible options using user context. Users can accept or edit recommendations. Specific exercises, exercise guidance, and progression parameters still require selection and validation.

The first demo should show a user setting a goal, receiving an explained routine, completing a session, and reviewing progress and a proposed next step. It should eventually demonstrate Alexa+ accessing the same saved context between workouts.

## Initial Profile

| Input | Purpose | Proposed handling |
|---|---|---|
| Goal and success measure | Explain what the user wants to achieve | Save the user's wording plus an agreed measure; do not infer a body-change goal |
| Experience | Distinguish starting, returning, and regular training | Ask directly; do not infer from camera appearance |
| Days and session duration | Fit the user's schedule | Require positive values and a feasible weekly schedule |
| Equipment and space | Filter eligible templates and exercises | Ask explicitly; allow no equipment |
| Preferences and exclusions | Make suggestions usable | Preserve explicit exclusions across suggestions |
| Self-reported limitations | Identify requests the catalog cannot support | Do not invent an adaptation when supported guidance is absent |
| Coaching preferences | Adjust tone and interaction frequency | Optional; use a neutral default |

Allow profile edits. Save the relevant context with each recommendation so later changes do not rewrite its original rationale.

## Proposed Recommendation Rules

1. Check that required context exists; ask a focused question when a missing answer changes eligibility.
2. Filter the catalog by available equipment, space, explicit exclusions, and supported adaptations. Treat these as constraints, not preferences the language model can override.
3. Select an eligible template that fits the declared time and experience. If none fits, explain the mismatch and request an adjustment instead of inventing unsupported exercise content.
4. Use preferences and comparable workout history to rank eligible options. On the first session, explicitly explain that the suggestion uses profile information only.
5. Produce a draft with exercise identifiers, prescribed activity, estimated duration, rationale, and assumptions. Validate generated output against the catalog and constraints before presenting it.
6. Let the user accept or edit the draft. Revalidate edits and save an immutable routine version before attaching it to a session.
7. After the session, use recorded completion, optional perceived effort and comments, and supported Vision observations to propose maintaining or changing the next routine. Missing tracking is not poor performance. A missed session is not a reason to automatically increase workload.
8. Explain proposed changes and require acceptance before they replace the planned routine. Quantitative progression thresholds remain an open design decision.

## Progress Views

| Dimension | Proposed evidence | Interpretation |
|---|---|---|
| Consistency | Completed versus planned sessions within a stated period | Report partial, skipped, and rescheduled sessions separately |
| Performance | Comparable exercise results and user-reported effort | Preserve exercise version, units, and measurement source; flag insufficient evidence |
| Personal goal | Agreed measures, baseline, updates, and optional photos | Distinguish measurements, self-reports, and estimates; do not equate attendance or appearance with goal achievement |

Photos remain optional private diary entries. Skipping a photo must never block session completion or progress review. No automatic body-composition or medical inference is planned.

## Proposed Product Records

These are logical entities, not a database-engine or deployment decision. All personal records must belong to an authenticated user.

| Record | Minimum information and relationships |
|---|---|
| Profile | User, experience, availability, equipment, space, preferences, exclusions, update time |
| Goal revision | User, goal text, measure and unit where applicable, optional baseline and target, effective date |
| Exercise definition | Stable identifier, version, requirements, supported prescription types, guidance, Vision support status |
| Routine template | Versioned structure, eligibility rules, exercise choices, duration calculation |
| Routine proposal/version | User, goal revision, profile context, template/catalog versions, prescription, rationale, draft or accepted state |
| Workout session | User, accepted routine version, timestamps, state, actual activity, analysis coverage |
| Session feedback | Session, optional perceived effort and comments, capture time |
| Progress entry | User, goal or exercise reference, value and unit, timestamp, source, associated session when applicable |
| Photo entry | User, private object reference, capture time, optional session link, deletion state |
| Coaching preferences | User, tone and frequency; reminder consent only if supported delivery is implemented |

Derived progress summaries should be reproducible from source records. Finishing or saving a session twice after a network retry must not double-count activity. A failed photo upload must not undo saved workout results.

## First-Demo Acceptance Scenarios

- A returning user with no history receives a routine explained from their stated context.
- An excluded exercise or unavailable equipment never appears in an accepted recommendation.
- When no eligible template exists, the product explains the missing fit.
- Editing a profile or routine leaves previous session prescriptions intact.
- Interrupted or low-confidence tracking stays distinguishable from measured results.
- Completing a session persists results even when feedback or the photo is skipped.
- A subsequent progress query uses the saved session and distinguishes consistency from goal achievement.
- A next-session proposal explains its evidence and remains a proposal until accepted.
- Once Alexa+ integration is implemented, it can retrieve the same authorized progress without an active TV/browser session.

## Next Design Decisions

Select the initial exercise catalog and templates, define the product–Vision contract, and choose the backend and persistence services against these records and access patterns. Phone operating system and model are still unknown. Validate other device paths with documented test environments and label simulated versus real behavior in demo evidence.
