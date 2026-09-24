# Vision Target Enrollment

The phone is the trust boundary for selecting the person whose movement may affect a workout. After preparing a session, the athlete explicitly opens the camera, captures one enrollment still, reviews every detected person box, and taps the box that represents them. Detection does not imply identity; Product does not confirm a target without this human action.

The mobile client calls `startSessionVisionAnalysis`, then `submitVisionEnrollmentFrame`. The Django backend verifies session ownership, resolves the attached Vision analysis, and relays the bounded base64 frame through its service-authenticated REST adapter. The Vision service decodes JPEG or PNG bytes, derives dimensions from the image, runs the configured person detector, and returns normalized boxes. The phone then calls `confirmSessionTarget` with the selected candidate and current session revision.

Enrollment pixels are processed ephemerally and are not persisted by Product or Vision. They are separate from the optional progress-photo flow and do not create a biometric profile. The mobile app requests camera permission at the moment enrollment begins and explains why it is needed.

Input is bounded at both services. Product rejects empty or oversized GraphQL payloads. Vision performs strict base64 and media-signature checks, inspects encoded dimensions before decoding, rejects images over 12 megapixels or 3 MB, and accepts only JPEG or PNG. The Vision service credential remains in Django and is never exposed to the mobile client.

When no person is found, the phone asks the athlete to improve full-body framing and retake the still. When multiple people are found, every box remains selectable and explicit confirmation is required. A confirmed target is session-scoped. Tracking ambiguity later pauses progression and asks for reconfirmation; stale epochs cannot silently replace the target.

Automated evidence covers GraphQL ownership, the Product-to-Vision REST contract, image decoding, bounding-box propagation, and target confirmation. Android camera rendering and physical phone-to-display behavior still require an on-device run and must not be described as verified until that evidence is recorded.
