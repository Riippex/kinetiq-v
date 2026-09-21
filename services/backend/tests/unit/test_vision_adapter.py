import io
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from uuid import uuid4

from kinetiq.modules.integrations.vision_adapter import (
    VisionAnalysisNotFoundError,
    VisionClientConfig,
    VisionConnectionError,
    VisionCursorExpiredError,
    VisionHttpError,
    VisionIdempotencyConflictError,
    VisionObservationDTO,
    VisionRestAdapter,
    VisionSchemaValidationError,
    VisionStaleEpochError,
    VisionTimeoutError,
    map_reason_code_to_pause_reason,
)
from kinetiq.modules.workouts.domain import PauseReason


def _load_fixture(relative_path: str) -> dict:
    base_dir = Path(__file__).resolve().parents[4] / "contracts" / "vision" / "v1" / "fixtures"
    fixture_file = base_dir / relative_path
    with open(fixture_file, encoding="utf-8") as f:
        return json.load(f)


def _mock_response(payload: dict | list | None) -> MagicMock:
    body_bytes = json.dumps(payload).encode("utf-8") if payload is not None else b""
    mock_response = MagicMock()
    mock_response.read.return_value = body_bytes
    mock_response.__enter__.return_value = mock_response
    return mock_response


def _http_error(url: str, code: int, error_body: dict) -> HTTPError:
    fp = io.BytesIO(json.dumps(error_body).encode("utf-8"))
    return HTTPError(url=url, code=code, msg="error", hdrs={}, fp=fp)


class VisionObservationSchemaValidationTests(unittest.TestCase):
    """Observation payload validation is the only schema validation this
    adapter still performs: Vision has no versioned /v1/capabilities REST
    endpoint, so capabilities are read from a local pinned fixture via
    FileBasedVisionCapabilities instead (see vision_contract_adapter.py)."""

    def setUp(self) -> None:
        self.config = VisionClientConfig(base_url="http://localhost:8080", timeout_seconds=2.0)
        self.adapter = VisionRestAdapter(config=self.config)

    def test_validate_positive_observation_fixtures(self) -> None:
        positive_files = [
            "observation_repetition.v1.json",
            "observation_hold.v1.json",
            "observation_target_ambiguous.v1.json",
            "observation_visibility_lost.v1.json",
        ]
        for filename in positive_files:
            with self.subTest(fixture=filename):
                payload = _load_fixture(filename)
                dto = self.adapter.validate_observation_payload(payload)
                self.assertIsInstance(dto, VisionObservationDTO)
                self.assertEqual(payload["session_id"], dto.session_id)
                self.assertEqual(payload["tracking_state"], dto.tracking_state)
                self.assertEqual(payload["reason_code"], dto.reason_code)

    def test_validate_negative_observation_fixtures_raise_validation_error(self) -> None:
        negative_dir = (
            Path(__file__).resolve().parents[4]
            / "contracts"
            / "vision"
            / "v1"
            / "fixtures"
            / "negative"
        )
        negative_files = list(negative_dir.glob("*.json"))
        self.assertGreater(len(negative_files), 0, "Negative fixtures must exist")

        for file_path in negative_files:
            with self.subTest(negative_fixture=file_path.name):
                with open(file_path, encoding="utf-8") as f:
                    payload = json.load(f)
                with self.assertRaises(VisionSchemaValidationError):
                    self.adapter.validate_observation_payload(payload)


class VisionRestAdapterAnalysesRoutesTests(unittest.TestCase):
    """Exercises every canonical /v1/analyses route from
    kinetiq-v-vision's contracts/v1/rest-api.md, verifying both the exact
    HTTP request shape and the parsed response DTO."""

    def setUp(self) -> None:
        self.config = VisionClientConfig(
            base_url="http://vision-service.local:8080", timeout_seconds=3.5
        )
        self.adapter = VisionRestAdapter(config=self.config)

    @patch("urllib.request.urlopen")
    def test_create_analysis_posts_to_v1_analyses(self, mock_urlopen) -> None:
        session_id = uuid4()
        mock_urlopen.return_value = _mock_response(
            {
                "analysis_id": "an_1",
                "session_id": str(session_id),
                "epoch": 1,
                "state": "AWAITING_SELECTION",
            }
        )

        dto = self.adapter.create_analysis(
            session_id=session_id,
            source_id="camera-front",
            exercise_key="bodyweight_squat",
            exercise_version=1,
            idempotency_key="idem-1",
        )

        self.assertEqual("an_1", dto.analysis_id)
        self.assertEqual(1, dto.epoch)
        self.assertEqual("AWAITING_SELECTION", dto.state)

        req = mock_urlopen.call_args[0][0]
        self.assertEqual("POST", req.get_method())
        self.assertEqual("http://vision-service.local:8080/v1/analyses", req.full_url)
        body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(str(session_id), body["session_id"])
        self.assertEqual("camera-front", body["source_id"])
        self.assertEqual("bodyweight_squat", body["exercise_key"])
        self.assertEqual("idem-1", body["idempotency_key"])

    @patch("urllib.request.urlopen")
    def test_select_target_posts_expected_epoch(self, mock_urlopen) -> None:
        mock_urlopen.return_value = _mock_response(
            {"target_person_id": "cand_1", "epoch": 1, "state": "TRACKING"}
        )

        dto = self.adapter.select_target(
            analysis_id="an_1", candidate_id="cand_1", expected_epoch=1
        )

        self.assertEqual("cand_1", dto.target_person_id)
        self.assertEqual("TRACKING", dto.state)

        req = mock_urlopen.call_args[0][0]
        self.assertEqual("POST", req.get_method())
        self.assertEqual("http://vision-service.local:8080/v1/analyses/an_1/target", req.full_url)
        body = json.loads(req.data.decode("utf-8"))
        self.assertEqual("cand_1", body["candidate_id"])
        self.assertEqual(1, body["expected_epoch"])

    @patch("urllib.request.urlopen")
    def test_select_target_stale_epoch_raises_typed_error(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = _http_error(
            "http://vision-service.local:8080/v1/analyses/an_1/target",
            409,
            {
                "error": {
                    "code": "STALE_EPOCH",
                    "message": "Expected epoch 1 does not match active epoch 2",
                    "details": {"expected_epoch": 1, "current_epoch": 2},
                }
            },
        )

        with self.assertRaises(VisionStaleEpochError) as ctx:
            self.adapter.select_target(analysis_id="an_1", candidate_id="cand_1", expected_epoch=1)
        self.assertEqual(1, ctx.exception.expected_epoch)
        self.assertEqual(2, ctx.exception.current_epoch)

    @patch("urllib.request.urlopen")
    def test_create_analysis_idempotency_conflict_raises_typed_error(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = _http_error(
            "http://vision-service.local:8080/v1/analyses",
            409,
            {
                "error": {
                    "code": "IDEMPOTENCY_CONFLICT",
                    "message": "Idempotency key 'k1' was already used for a different request",
                    "details": {"idempotency_key": "k1"},
                }
            },
        )

        with self.assertRaises(VisionIdempotencyConflictError) as ctx:
            self.adapter.create_analysis(
                session_id=uuid4(), source_id="cam", exercise_key="push_up", idempotency_key="k1"
            )
        self.assertEqual("k1", ctx.exception.idempotency_key)

    @patch("urllib.request.urlopen")
    def test_get_analysis_status_not_found_raises_typed_error(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = _http_error(
            "http://vision-service.local:8080/v1/analyses/missing",
            404,
            {"error": {"code": "NOT_FOUND", "message": "not found", "details": {}}},
        )

        with self.assertRaises(VisionAnalysisNotFoundError) as ctx:
            self.adapter.get_analysis_status(analysis_id="missing")
        self.assertEqual("missing", ctx.exception.analysis_id)

    @patch("urllib.request.urlopen")
    def test_list_candidates_parses_bbox_and_confidence(self, mock_urlopen) -> None:
        mock_urlopen.return_value = _mock_response(
            {
                "candidates": [
                    {
                        "candidate_id": "cand_1",
                        "bbox": [0.1, 0.2, 0.3, 0.4],
                        "confidence": 0.91,
                        "detected_at": "2026-09-17T00:00:00Z",
                    }
                ]
            }
        )

        candidates = self.adapter.list_candidates(analysis_id="an_1")

        self.assertEqual(1, len(candidates))
        self.assertEqual("cand_1", candidates[0].candidate_id)
        self.assertEqual((0.1, 0.2, 0.3, 0.4), candidates[0].bbox)
        self.assertEqual(0.91, candidates[0].confidence)

        req = mock_urlopen.call_args[0][0]
        self.assertEqual(
            "http://vision-service.local:8080/v1/analyses/an_1/candidates", req.full_url
        )

    @patch("urllib.request.urlopen")
    def test_poll_observations_passes_cursor_and_limit_and_validates(self, mock_urlopen) -> None:
        obs_payload = _load_fixture("observation_repetition.v1.json")
        mock_urlopen.return_value = _mock_response(
            {"observations": [obs_payload], "next_cursor": "1:2", "has_more": False}
        )

        page = self.adapter.poll_observations(analysis_id="an_1", after_cursor="1:1", limit=10)

        self.assertEqual(1, len(page.observations))
        self.assertEqual("1:2", page.next_cursor)
        self.assertFalse(page.has_more)

        req = mock_urlopen.call_args[0][0]
        self.assertIn("/v1/analyses/an_1/observations?", req.full_url)
        self.assertIn("after=1:1", req.full_url)
        self.assertIn("limit=10", req.full_url)

    @patch("urllib.request.urlopen")
    def test_poll_observations_cursor_expired_raises_typed_error(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = _http_error(
            "http://vision-service.local:8080/v1/analyses/an_1/observations",
            410,
            {
                "error": {
                    "code": "CURSOR_EXPIRED",
                    "message": "cursor expired",
                    "details": {"requested_cursor": "1:1", "oldest_cursor": "1:50"},
                }
            },
        )

        with self.assertRaises(VisionCursorExpiredError) as ctx:
            self.adapter.poll_observations(analysis_id="an_1", after_cursor="1:1")
        self.assertEqual("1:1", ctx.exception.requested_cursor)
        self.assertEqual("1:50", ctx.exception.oldest_cursor)

    @patch("urllib.request.urlopen")
    def test_delete_analysis_sends_delete(self, mock_urlopen) -> None:
        mock_urlopen.return_value = _mock_response(None)

        self.adapter.delete_analysis(analysis_id="an_1")

        req = mock_urlopen.call_args[0][0]
        self.assertEqual("DELETE", req.get_method())
        self.assertEqual("http://vision-service.local:8080/v1/analyses/an_1", req.full_url)

    @patch("urllib.request.urlopen")
    def test_generic_http_error_falls_back_to_vision_http_error(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = _http_error(
            "http://vision-service.local:8080/v1/analyses",
            500,
            {"error": {"code": "INTERNAL", "message": "boom", "details": {}}},
        )

        with self.assertRaises(VisionHttpError) as ctx:
            self.adapter.create_analysis(
                session_id=uuid4(), source_id="cam", exercise_key="bodyweight_squat"
            )
        self.assertEqual(500, ctx.exception.status_code)

    @patch("urllib.request.urlopen")
    def test_timeout_surfaces_vision_timeout_error(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = URLError(TimeoutError("timed out"))

        with self.assertRaises(VisionTimeoutError):
            self.adapter.get_analysis_status(analysis_id="an_1")

    @patch("urllib.request.urlopen")
    def test_connection_failure_surfaces_vision_connection_error(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = URLError(ConnectionRefusedError("Connection refused"))

        with self.assertRaises(VisionConnectionError):
            self.adapter.get_analysis_status(analysis_id="an_1")


class ReasonCodeMappingTests(unittest.TestCase):
    def test_reason_code_mappings(self) -> None:
        self.assertIsNone(map_reason_code_to_pause_reason("OK"))
        self.assertEqual(
            PauseReason.TARGET_AMBIGUOUS,
            map_reason_code_to_pause_reason("TARGET_AMBIGUOUS"),
        )
        self.assertEqual(
            PauseReason.VISIBILITY,
            map_reason_code_to_pause_reason("OCCLUSION"),
        )
        self.assertEqual(
            PauseReason.VISIBILITY,
            map_reason_code_to_pause_reason("OUT_OF_FRAME"),
        )
        self.assertEqual(
            PauseReason.VISIBILITY,
            map_reason_code_to_pause_reason("LOW_CONFIDENCE"),
        )
        self.assertEqual(
            PauseReason.VISIBILITY,
            map_reason_code_to_pause_reason("UNKNOWN_CODE_FALLBACK"),
        )


class VisionAdapterArchitectureIsolationTests(unittest.TestCase):
    def test_adapter_module_does_not_import_django(self) -> None:
        import kinetiq.modules.integrations.vision_adapter as module

        module_code = Path(module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("django", module_code.lower())
        self.assertNotIn("WorkoutSessionRecord", module_code)


if __name__ == "__main__":
    unittest.main()
