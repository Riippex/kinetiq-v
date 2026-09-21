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
    """Raised when the Vision service returns a non-2xx HTTP status not
    otherwise mapped to a more specific exception below."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class VisionAnalysisNotFoundError(VisionAdapterError):
    """Raised on 404 for an analysis_id the Vision service does not know about."""

    def __init__(self, analysis_id: str) -> None:
        super().__init__(f"Vision analysis '{analysis_id}' was not found")
        self.analysis_id = analysis_id


class VisionStaleEpochError(VisionAdapterError):
    """Raised on 409 STALE_EPOCH: the caller's expected_epoch no longer
    matches the analysis's current epoch (e.g. a concurrent re-target or
    stream restart already advanced it)."""

    def __init__(
        self, message: str, expected_epoch: int | None = None, current_epoch: int | None = None
    ) -> None:
        super().__init__(message)
        self.expected_epoch = expected_epoch
        self.current_epoch = current_epoch


class VisionCursorExpiredError(VisionAdapterError):
    """Raised on 410 CURSOR_EXPIRED: the requested observation cursor has
    aged out of Vision's sliding retention buffer."""

    def __init__(
        self, message: str, requested_cursor: str, oldest_cursor: str | None = None
    ) -> None:
        super().__init__(message)
        self.requested_cursor = requested_cursor
        self.oldest_cursor = oldest_cursor


class VisionIdempotencyConflictError(VisionAdapterError):
    """Raised on 409 IDEMPOTENCY_CONFLICT: an idempotency_key was reused
    with different request parameters than the request that originally
    claimed it."""

    def __init__(self, message: str, idempotency_key: str | None = None) -> None:
        super().__init__(message)
        self.idempotency_key = idempotency_key


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
    session_id: str
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
class VisionAnalysisDTO:
    analysis_id: str
    session_id: str
    epoch: int
    state: str


@dataclass(frozen=True, slots=True)
class VisionAnalysisStatusDTO:
    analysis_id: str
    session_id: str
    epoch: int
    state: str
    last_valid_at: str | None = None


@dataclass(frozen=True, slots=True)
class VisionTargetSelectionDTO:
    target_person_id: str
    epoch: int
    state: str


@dataclass(frozen=True, slots=True)
class VisionCandidateDTO:
    candidate_id: str
    bbox: tuple[float, float, float, float]
    confidence: float
    detected_at: str


@dataclass(frozen=True, slots=True)
class VisionObservationsPageDTO:
    observations: tuple[VisionObservationDTO, ...]
    next_cursor: str | None
    has_more: bool


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
    """Typed REST adapter for the external Vision microservice, aligned with
    the canonical `/v1/analyses` contract (kinetiq-v-vision
    `contracts/v1/rest-api.md`): create an analysis, list detected
    candidates, confirm a target with `expected_epoch`, poll observations by
    cursor, and delete the analysis.

    Features:
    - Deadlines and configurable connection/socket timeouts.
    - Automatic correlation ID and request ID propagation.
    - Strict JSON Schema validation of observation payloads against the
      versioned Draft 2020-12 contract.
    - Typed exceptions for the contract's structured error codes
      (STALE_EPOCH -> VisionStaleEpochError, CURSOR_EXPIRED ->
      VisionCursorExpiredError, 404 -> VisionAnalysisNotFoundError).
    - Explicit reason code to domain PauseReason mapping.
    - Zero direct database access.

    Capabilities (supported exercises/perspectives) are not served by this
    adapter: the Vision service has no versioned `/v1/capabilities` REST
    endpoint, and capabilities are instead read from the local pinned
    fixture via `FileBasedVisionCapabilities`
    (modules/catalog/infrastructure/vision_contract_adapter.py).
    """

    def __init__(
        self,
        config: VisionClientConfig | None = None,
        *,
        observation_schema: dict[str, Any] | None = None,
    ) -> None:
        self.config = config or VisionClientConfig()

        if observation_schema is not None:
            self._observation_schema = observation_schema
        elif OBSERVATION_SCHEMA_PATH.exists():
            with open(OBSERVATION_SCHEMA_PATH, encoding="utf-8") as f:
                self._observation_schema = json.load(f)
        else:
            self._observation_schema = {}

        self._observation_validator = (
            Draft202012Validator(self._observation_schema) if self._observation_schema else None
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
        except TimeoutError as err:
            logger.error("Vision service timeout for %s %s (cid=%s): %s", method, url, cid, err)
            raise VisionTimeoutError(
                f"Vision request to {path} timed out after {self.config.timeout_seconds}s"
            ) from err
        except urllib.error.HTTPError as err:
            err_body_raw = err.read().decode("utf-8") if hasattr(err, "read") else ""
            logger.error(
                "Vision service HTTP error %s for %s (cid=%s): %s", err.code, url, cid, err_body_raw
            )
            raise self._map_http_error(err.code, err_body_raw, path) from err
        except urllib.error.URLError as err:
            if isinstance(err.reason, (socket.timeout, TimeoutError)):
                raise VisionTimeoutError(f"Vision request to {path} timed out") from err
            logger.error("Vision service connection failed for %s (cid=%s): %s", url, cid, err)
            raise VisionConnectionError(
                f"Failed to connect to Vision service at {url}: {err.reason}"
            ) from err
        except Exception as err:
            logger.error(
                "Unexpected error contacting Vision service %s (cid=%s): %s", url, cid, err
            )
            raise VisionAdapterError(f"Unexpected vision error: {err}") from err

    @staticmethod
    def _map_http_error(status_code: int, body: str, path: str) -> VisionAdapterError:
        """Map the contract's structured error envelope

        (`{"error": {"code", "message", "details", ...}}`) to a specific
        typed exception where one is defined, falling back to the generic
        `VisionHttpError` otherwise.
        """
        error_obj: dict[str, Any] = {}
        try:
            parsed = json.loads(body) if body.strip() else {}
            error_obj = parsed.get("error", {}) if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, AttributeError):
            pass

        code = error_obj.get("code")
        message = error_obj.get("message") or f"Vision service returned HTTP {status_code}: {body}"
        details = error_obj.get("details") or {}

        if status_code == 404:
            analysis_id = details.get("analysis_id") or path.rsplit("/", 1)[-1]
            return VisionAnalysisNotFoundError(str(analysis_id))
        if code == "STALE_EPOCH":
            return VisionStaleEpochError(
                message,
                expected_epoch=details.get("expected_epoch"),
                current_epoch=details.get("current_epoch"),
            )
        if code == "CURSOR_EXPIRED" or status_code == 410:
            return VisionCursorExpiredError(
                message,
                requested_cursor=details.get("requested_cursor", ""),
                oldest_cursor=details.get("oldest_cursor"),
            )
        if code == "IDEMPOTENCY_CONFLICT":
            return VisionIdempotencyConflictError(
                message, idempotency_key=details.get("idempotency_key")
            )
        return VisionHttpError(message, status_code=status_code)

    def create_analysis(
        self,
        *,
        session_id: UUID,
        source_id: str,
        exercise_key: str,
        exercise_version: int = 1,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> VisionAnalysisDTO:
        payload = {
            "session_id": str(session_id),
            "source_id": source_id,
            "exercise_key": exercise_key,
            "exercise_version": exercise_version,
            "idempotency_key": idempotency_key,
        }
        data = self._execute_http(
            "POST", "/v1/analyses", payload=payload, correlation_id=correlation_id
        )
        return VisionAnalysisDTO(
            analysis_id=data["analysis_id"],
            session_id=data["session_id"],
            epoch=data["epoch"],
            state=data["state"],
        )

    def select_target(
        self,
        *,
        analysis_id: str,
        candidate_id: str,
        expected_epoch: int,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> VisionTargetSelectionDTO:
        payload = {
            "candidate_id": candidate_id,
            "expected_epoch": expected_epoch,
            "idempotency_key": idempotency_key,
        }
        data = self._execute_http(
            "POST",
            f"/v1/analyses/{analysis_id}/target",
            payload=payload,
            correlation_id=correlation_id,
        )
        return VisionTargetSelectionDTO(
            target_person_id=data["target_person_id"],
            epoch=data["epoch"],
            state=data["state"],
        )

    def get_analysis_status(
        self, *, analysis_id: str, correlation_id: str | None = None
    ) -> VisionAnalysisStatusDTO:
        data = self._execute_http(
            "GET", f"/v1/analyses/{analysis_id}", correlation_id=correlation_id
        )
        return VisionAnalysisStatusDTO(
            analysis_id=data["analysis_id"],
            session_id=data["session_id"],
            epoch=data["epoch"],
            state=data["state"],
            last_valid_at=data.get("last_valid_at"),
        )

    def list_candidates(
        self, *, analysis_id: str, correlation_id: str | None = None
    ) -> tuple[VisionCandidateDTO, ...]:
        data = self._execute_http(
            "GET", f"/v1/analyses/{analysis_id}/candidates", correlation_id=correlation_id
        )
        return tuple(
            VisionCandidateDTO(
                candidate_id=c["candidate_id"],
                bbox=tuple(c["bbox"]),
                confidence=c["confidence"],
                detected_at=c["detected_at"],
            )
            for c in data.get("candidates", [])
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
            session_id=data["session_id"],
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

    def poll_observations(
        self,
        *,
        analysis_id: str,
        after_cursor: str | None = None,
        limit: int = 50,
        correlation_id: str | None = None,
    ) -> VisionObservationsPageDTO:
        query = f"limit={limit}"
        if after_cursor:
            query += f"&after={after_cursor}"
        data = self._execute_http(
            "GET",
            f"/v1/analyses/{analysis_id}/observations?{query}",
            correlation_id=correlation_id,
        )
        observations = tuple(
            self.validate_observation_payload(obs) for obs in data.get("observations", [])
        )
        return VisionObservationsPageDTO(
            observations=observations,
            next_cursor=data.get("next_cursor"),
            has_more=bool(data.get("has_more", False)),
        )

    def delete_analysis(self, *, analysis_id: str, correlation_id: str | None = None) -> None:
        self._execute_http("DELETE", f"/v1/analyses/{analysis_id}", correlation_id=correlation_id)
