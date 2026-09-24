# Submission Evidence

## Core claim

Kinetiq V is a multi-device coaching product that turns an accepted routine into a phone-controlled session. Kinetiq V Vision detects candidate people, requires the athlete to select the session target, and supplies movement observations. Product owns routines, safe state changes, Dynamic challenges, progress, display synchronization, and Alexa+ access through the same business use cases.

## Demonstrable path

1. Configure athlete context and accept an explained routine.
2. Prepare a Normal or Dynamic session on the phone.
3. Open the camera and grant permission explicitly.
4. Capture an ephemeral enrollment still.
5. Show normalized boxes returned by Vision and require a human target selection.
6. Confirm that only the selected target can affect live progress.
7. Show ambiguity pausing progression and asking for reconfirmation while confirmed work remains intact.
8. Pair a Fire TV or Vega display and mirror session state when the supported simulator or device is available.
9. Finish the session, optionally capture a separate progress photo, and retrieve follow-up context through the backend or Alexa+ MCP.

## Claim and evidence checklist

| Claim | Evidence | Current limit |
|---|---|---|
| Target enrollment crosses the real Product/Vision boundary. | Cross-repository test starts the FastAPI service and exercises create analysis, encoded frame submission, candidate listing, and deletion through the Django adapter. | Stub inference is used in the automated cross-repository run. |
| Enrollment is owner-scoped and explicit. | Django application and GraphQL tests require an owned session with an attached analysis; the mobile flow requests permission and a tap on a detected box. | Physical Galaxy device capture remains to be recorded. |
| Invalid images are rejected before inference. | Vision codec tests cover invalid base64, unsupported content, decoded pixels, and pre-decode dimension limits. | The 3 MB and 12 MP limits may be tuned after device measurements. |
| Ambiguity changes a later product action. | The Agentic Vision trace proves ambiguity pauses progression, requests reconfirmation, rejects stale epochs, and preserves confirmed repetitions. | Deterministic fixtures verify policy, not field accuracy. |
| Fire TV and Vega can consume shared session state. | Client, GraphQL, Redis concurrency, and TV polling tests. | Physical or official simulator evidence is still required. |
| AWS release behavior is ready for qualification. | Terraform, deployment runbooks, and opt-in AWS qualification suites in both repositories. | No live AWS deployment or rollback is claimed yet. |

## Evidence discipline

Synthetic and stub runs demonstrate software mechanics only. Detection accuracy, real-media safety gates, Android camera behavior, Fire TV/Vega operation, and AWS release qualification become verified only after their corresponding authorized environment runs are captured. No raw enrollment image, private progress photo, model weight, credential, or local planning document belongs in submission artifacts.
