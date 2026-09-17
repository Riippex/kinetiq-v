import io
import json
import os
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from uuid import uuid4

from kinetiq.modules.integrations.vision_adapter import (
    VisionClientConfig,
    VisionConnectionError,
    VisionHttpError,
    VisionObservationDTO,
    VisionRestAdapter,
    VisionSchemaValidationError,
    VisionTimeoutError,
    map_reason_code_to_pause_reason,
)
from kinetiq.modules.workouts.domain import PauseReason


def _load_fixture(relative_path: str) -> dict:
    base_dir = Path(__file__).resolve().parents[4] / "contracts" / "vision" / "v1" / "fixtures"
    fixture_file = base_dir / relative_path
    with open(fixture_file, "r", encoding="utf-8") as f:
        return json.load(f)


class VisionRestAdapterSchemaValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = VisionClientConfig(
            base_url="http://localhost:8080",
            timeout_seconds=2.0,
        )
        self.adapter = VisionRestAdapter(config=self.config)

    def test_validate_positive_capabilities_fixture(self) -> None:
        payload = _load_fixture("capabilities.v1.json")
        validated = self.adapter.validate_capabilities_payload(payload)
        self.assertEqual("1.0.0", validated.contract_version)
        exercise_keys = [ex.exercise_key for ex in validated.supported_exercises]
        self.assertIn("bodyweight_squat", exercise_keys)

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
                self.assertEqual(payload["session_id"], str(dto.session_id))
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
                with open(file_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                with self.assertRaises(VisionSchemaValidationError):
                    self.adapter.validate_observation_payload(payload)


class VisionRestAdapterHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = VisionClientConfig(
            base_url="http://vision-service.local:8080",
            timeout_seconds=3.5,
        )
        self.adapter = VisionRestAdapter(config=self.config)

    @patch("urllib.request.urlopen")
    def test_fetch_capabilities_passes_headers_and_returns_dto(self, mock_urlopen) -> None:
        payload = _load_fixture("capabilities.v1.json")
        body_bytes = json.dumps(payload).encode("utf-8")
        mock_response = MagicMock()
        mock_response.read.return_value = body_bytes
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        correlation_id = "corr-12345"
        dto = self.adapter.fetch_capabilities(correlation_id=correlation_id)

        self.assertEqual("1.0.0", dto.contract_version)
        self.assertTrue(mock_urlopen.called)
        req = mock_urlopen.call_args[0][0]
        self.assertEqual("http://vision-service.local:8080/v1/capabilities", req.full_url)
        self.assertEqual(correlation_id, req.headers["X-correlation-id"])
        self.assertIn("X-request-id", req.headers)
        self.assertEqual(3.5, mock_urlopen.call_args[1]["timeout"])

    @patch("urllib.request.urlopen")
    def test_fetch_observation_passes_headers_and_validates(self, mock_urlopen) -> None:
        payload = _load_fixture("observation_repetition.v1.json")
        session_id = payload["session_id"]
        body_bytes = json.dumps(payload).encode("utf-8")
        mock_response = MagicMock()
        mock_response.read.return_value = body_bytes
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        dto = self.adapter.fetch_observation(session_id=session_id)

        self.assertEqual(session_id, str(dto.session_id))
        self.assertEqual("CONFIRMED", dto.tracking_state)
        self.assertEqual(2, len(dto.repetitions))
        self.assertEqual("person_track_01", dto.target_person_id)

        req = mock_urlopen.call_args[0][0]
        self.assertEqual(
            f"http://vision-service.local:8080/v1/sessions/{session_id}/observation",
            req.full_url,
        )
        self.assertIn("X-correlation-id", req.headers)
        self.assertIn("X-request-id", req.headers)

    @patch("urllib.request.urlopen")
    def test_http_error_surfaces_vision_http_error(self, mock_urlopen) -> None:
        fp = io.BytesIO(b'{"error": "Internal Server Error"}')
        mock_urlopen.side_effect = HTTPError(
            url="http://vision-service.local:8080/v1/capabilities",
            code=500,
            msg="Server Error",
            hdrs={},
            fp=fp,
        )

        with self.assertRaises(VisionHttpError) as ctx:
            self.adapter.fetch_capabilities()
        self.assertEqual(500, ctx.exception.status_code)

    @patch("urllib.request.urlopen")
    def test_timeout_surfaces_vision_timeout_error(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = URLError(socket.timeout("timed out"))

        with self.assertRaises(VisionTimeoutError):
            self.adapter.fetch_observation(session_id=uuid4())

    @patch("urllib.request.urlopen")
    def test_connection_failure_surfaces_vision_connection_error(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = URLError(ConnectionRefusedError("Connection refused"))

        with self.assertRaises(VisionConnectionError):
            self.adapter.fetch_capabilities()


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
