import json
import logging
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator

from kinetiq.modules.workouts.domain.session import PauseReason

logger = logging.getLogger(__name__)

CONTRACTS_DIR = Path(__file__).resolve().parents[6] / "contracts" / "vision" / "v1" / "schema"
CAPABILITIES_SCHEMA_PATH = CONTRACTS_DIR / "vision-capabilities.v1.schema.json"
OBSERVATION_SCHEMA_PATH = CONTRACTS_DIR / "vision-observation.v1.schema.json"


class VisionAdapterError(Exception):
    """Base exception for all Vision adapter errors."""


class VisionTimeoutError(VisionAdapterError):
    """Raised when a request to the Vision service exceeds its deadline."""


class VisionConnectionError(VisionAdapterError):
    """Raised when connection to the Vision service fails."""


class VisionSchemaValidationError(VisionAdapterError):
    """Raised when request or response payloads violate the versioned JSON schema."""


class VisionHttpError(VisionAdapterError):
    """Raised when the Vision service returns a non-2xx HTTP status."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class VisionRepetitionDTO:
    repetition_index: int
    start_timestamp: str
    end_timestamp: str
    confidence: float
    quality_score: float
    form_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VisionHoldDTO:
    elapsed_seconds: float
    is_holding: bool
    confidence: float
    stability_score: float
    form_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VisionObservationDTO:
    session_id: UUID
    epoch: int
    sequence: int
    timestamp_utc: str
    target_person_id: str
    exercise_key: str
    exercise_version: int
    tracking_state: str
    visibility_state: str
    reason_code: str
    repetitions: tuple[VisionRepetitionDTO, ...] = ()
    hold: VisionHoldDTO | None = None

    @property
    def confirmed_repetition_count(self) -> int:
        return len(self.repetitions)


@dataclass(frozen=True, slots=True)
class VisionSupportedExerciseDTO:
    exercise_key: str
    version: int
    name: str
    analysis_type: str
    supported_metrics: tuple[str, ...]
    required_visibility: str


@dataclass(frozen=True, slots=True)
class VisionCapabilitiesDTO:
    service: str
    contract_version: str
    supported_target_modes: tuple[str, ...]
    supported_camera_perspectives: tuple[str, ...]
    supported_exercises: tuple[VisionSupportedExerciseDTO, ...]


@dataclass(frozen=True, slots=True)
class VisionClientConfig:
    base_url: str = "http://127.0.0.1:8001"
    timeout_seconds: float = 5.0
    default_headers: dict[str, str] = field(default_factory=dict)


def map_reason_code_to_pause_reason(reason_code: str) -> PauseReason | None:
    """Map Vision contract observation reason codes to domain PauseReason."""
    match reason_code:
        case "OK":
            return None
        case "TARGET_AMBIGUOUS":
            return PauseReason.TARGET_AMBIGUOUS
        case "OCCLUSION" | "OUT_OF_FRAME" | "LOW_CONFIDENCE":
            return PauseReason.VISIBILITY
        case _:
            return PauseReason.VISIBILITY


class VisionRestAdapter:
    """Typed REST adapter for the external Vision microservice.

    Features:
    - Deadlines and configurable connection/socket timeouts.
    - Automatic correlation ID and request ID propagation.
    - Strict JSON Schema validation against versioned Draft 2020-12 contracts.
    - Explicit reason code to domain PauseReason mapping.
    - Zero direct database access.
    """

    def __init__(
        self,
        config: VisionClientConfig | None = None,
        *,
        capabilities_schema: dict[str, Any] | None = None,
        observation_schema: dict[str, Any] | None = None,
    ) -> None:
        self.config = config or VisionClientConfig()

        if capabilities_schema is not None:
            self._capabilities_schema = capabilities_schema
        elif CAPABILITIES_SCHEMA_PATH.exists():
            with open(CAPABILITIES_SCHEMA_PATH, encoding="utf-8") as f:
                self._capabilities_schema = json.load(f)
        else:
            self._capabilities_schema = {}

        if observation_schema is not None:
            self._observation_schema = observation_schema
        elif OBSERVATION_SCHEMA_PATH.exists():
            with open(OBSERVATION_SCHEMA_PATH, encoding="utf-8") as f:
                self._observation_schema = json.load(f)
        else:
            self._observation_schema = {}

        self._capabilities_validator = (
            Draft202012Validator(self._capabilities_schema)
            if self._capabilities_schema
            else None
        )
        self._observation_validator = (
            Draft202012Validator(self._observation_schema)
            if self._observation_schema
            else None
        )

    def _execute_http(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        url = f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"
        cid = correlation_id or str(uuid4())
        rid = str(uuid4())

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-correlation-id": cid,
            "x-request-id": rid,
            **self.config.default_headers,
        }

        data_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body.strip() else {}
        except (TimeoutError, socket.timeout) as err:
            logger.error("Vision service timeout for %s %s (cid=%s): %s", method, url, cid, err)
            raise VisionTimeoutError(f"Vision request to {path} timed out after {self.config.timeout_seconds}s") from err
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8") if hasattr(err, "read") else ""
            logger.error("Vision service HTTP error %s for %s (cid=%s): %s", err.code, url, cid, err_body)
            raise VisionHttpError(f"Vision service returned HTTP {err.code}: {err_body}", status_code=err.code) from err
        except urllib.error.URLError as err:
            if isinstance(err.reason, (socket.timeout, TimeoutError)):
                raise VisionTimeoutError(f"Vision request to {path} timed out") from err
            logger.error("Vision service connection failed for %s (cid=%s): %s", url, cid, err)
            raise VisionConnectionError(f"Failed to connect to Vision service at {url}: {err.reason}") from err
        except Exception as err:
            logger.error("Unexpected error contacting Vision service %s (cid=%s): %s", url, cid, err)
            raise VisionAdapterError(f"Unexpected vision error: {err}") from err

    def validate_capabilities_payload(self, data: dict[str, Any]) -> VisionCapabilitiesDTO:
        """Validate raw dictionary against capabilities schema and return strongly-typed DTO."""
        if self._capabilities_validator:
            errors = list(self._capabilities_validator.iter_errors(data))
            if errors:
                raise VisionSchemaValidationError(
                    f"Capabilities payload failed schema validation: {[e.message for e in errors]}"
                )

        supported_exercises = tuple(
            VisionSupportedExerciseDTO(
                exercise_key=item["exercise_key"],
                version=item["version"],
                name=item["name"],
                analysis_type=item["analysis_type"],
                supported_metrics=tuple(item["supported_metrics"]),
                required_visibility=item["required_visibility"],
            )
            for item in data.get("supported_exercises", [])
        )

        return VisionCapabilitiesDTO(
            service=data["service"],
            contract_version=data["contract_version"],
            supported_target_modes=tuple(data.get("supported_target_modes", [])),
            supported_camera_perspectives=tuple(data.get("supported_camera_perspectives", [])),
            supported_exercises=supported_exercises,
        )

    def fetch_capabilities(self, correlation_id: str | None = None) -> VisionCapabilitiesDTO:
        data = self._execute_http("GET", "/v1/capabilities", correlation_id=correlation_id)
        return self.validate_capabilities_payload(data)

    def start_session_analysis(
        self,
        *,
        session_id: UUID,
        target_person_id: str,
        exercise_key: str,
        exercise_version: int,
        epoch: int = 1,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "session_id": str(session_id),
            "target_person_id": target_person_id,
            "exercise_key": exercise_key,
            "exercise_version": exercise_version,
            "epoch": epoch,
        }
        return self._execute_http(
            "POST",
            f"/v1/sessions/{session_id}/analysis",
            payload=payload,
            correlation_id=correlation_id,
        )

    def validate_observation_payload(self, data: dict[str, Any]) -> VisionObservationDTO:
        """Validate raw dictionary against observation schema and return strongly-typed DTO."""
        if self._observation_validator:
            errors = list(self._observation_validator.iter_errors(data))
            if errors:
                raise VisionSchemaValidationError(
                    f"Observation payload failed schema validation: {[e.message for e in errors]}"
                )

        repetitions = tuple(
            VisionRepetitionDTO(
                repetition_index=rep["repetition_index"],
                start_timestamp=rep["start_timestamp"],
                end_timestamp=rep["end_timestamp"],
                confidence=rep["confidence"],
                quality_score=rep["quality_score"],
                form_flags=tuple(rep.get("form_flags", ())),
            )
            for rep in data.get("repetitions", [])
        )

        hold_data = data.get("hold")
        hold = None
        if hold_data is not None:
            hold = VisionHoldDTO(
                elapsed_seconds=hold_data["elapsed_seconds"],
                is_holding=hold_data["is_holding"],
                confidence=hold_data["confidence"],
                stability_score=hold_data["stability_score"],
                form_flags=tuple(hold_data.get("form_flags", ())),
            )

        return VisionObservationDTO(
            session_id=UUID(data["session_id"]),
            epoch=data["epoch"],
            sequence=data["sequence"],
            timestamp_utc=data["timestamp_utc"],
            target_person_id=data["target_person_id"],
            exercise_key=data["exercise_key"],
            exercise_version=data["exercise_version"],
            tracking_state=data["tracking_state"],
            visibility_state=data["visibility_state"],
            reason_code=data["reason_code"],
            repetitions=repetitions,
            hold=hold,
        )

    def fetch_observation(
        self,
        *,
        session_id: UUID,
        correlation_id: str | None = None,
    ) -> VisionObservationDTO:
        data = self._execute_http(
            "GET",
            f"/v1/sessions/{session_id}/observation",
            correlation_id=correlation_id,
        )
        return self.validate_observation_payload(data)

    def stop_session_analysis(
        self,
        *,
        session_id: UUID,
        correlation_id: str | None = None,
    ) -> bool:
        result = self._execute_http(
            "POST",
            f"/v1/sessions/{session_id}/analysis/stop",
            payload={"session_id": str(session_id)},
            correlation_id=correlation_id,
        )
        return bool(result.get("stopped", True))
