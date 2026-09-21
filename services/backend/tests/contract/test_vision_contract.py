import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
CONTRACTS_DIR = REPOSITORY_ROOT / "contracts" / "vision" / "v1"
SCHEMA_DIR = CONTRACTS_DIR / "schema"
FIXTURES_DIR = CONTRACTS_DIR / "fixtures"
NEGATIVE_FIXTURES_DIR = FIXTURES_DIR / "negative"


def load_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as file:
        return json.load(file)


@pytest.fixture(scope="module")
def capabilities_schema() -> dict[str, Any]:
    schema_path = SCHEMA_DIR / "vision-capabilities.v1.schema.json"
    assert schema_path.exists(), f"Missing schema at {schema_path}"
    return load_json(schema_path)


@pytest.fixture(scope="module")
def observation_schema() -> dict[str, Any]:
    schema_path = SCHEMA_DIR / "vision-observation.v1.schema.json"
    assert schema_path.exists(), f"Missing schema at {schema_path}"
    return load_json(schema_path)


def test_capabilities_schema_is_valid_draft_2020_12(capabilities_schema: dict[str, Any]) -> None:
    Draft202012Validator.check_schema(capabilities_schema)


def test_observation_schema_is_valid_draft_2020_12(observation_schema: dict[str, Any]) -> None:
    Draft202012Validator.check_schema(observation_schema)


def test_capabilities_fixture_validates_against_schema(
    capabilities_schema: dict[str, Any],
) -> None:
    fixture_path = FIXTURES_DIR / "capabilities.v1.json"
    assert fixture_path.exists()
    payload = load_json(fixture_path)

    validator = Draft202012Validator(capabilities_schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    assert not errors, f"Capabilities validation failed: {errors}"


@pytest.mark.parametrize(
    "fixture_name",
    [
        "observation_repetition.v1.json",
        "observation_hold.v1.json",
        "observation_target_ambiguous.v1.json",
        "observation_visibility_lost.v1.json",
    ],
)
def test_observation_fixtures_validate_against_schema(
    observation_schema: dict[str, Any], fixture_name: str
) -> None:
    fixture_path = FIXTURES_DIR / fixture_name
    assert fixture_path.exists()
    payload = load_json(fixture_path)

    validator = Draft202012Validator(observation_schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    assert not errors, f"Observation fixture {fixture_name} validation failed: {errors}"


@pytest.mark.parametrize(
    ("fixture_name", "expected_error_substr"),
    [
        ("invalid_missing_reason_code.v1.json", "reason_code"),
        ("invalid_missing_sequence.v1.json", "sequence"),
        ("invalid_confidence_out_of_bounds.v1.json", "maximum"),
        ("invalid_exercise_key_format.v1.json", "pattern"),
        ("invalid_negative_epoch.v1.json", "minimum"),
        ("invalid_zero_sequence.v1.json", "minimum"),
        ("invalid_unknown_tracking_state.v1.json", "enum"),
        ("invalid_extra_properties.v1.json", "additionalProperties"),
    ],
)
def test_negative_fixtures_fail_schema_validation(
    observation_schema: dict[str, Any], fixture_name: str, expected_error_substr: str
) -> None:
    fixture_path = NEGATIVE_FIXTURES_DIR / fixture_name
    assert fixture_path.exists(), f"Negative fixture {fixture_name} missing"
    payload = load_json(fixture_path)

    validator = Draft202012Validator(observation_schema)
    errors = list(validator.iter_errors(payload))
    assert errors, f"Expected validation failure for {fixture_name}, but passed successfully"
    error_messages = (
        " ".join([e.message for e in errors]) + " " + " ".join([str(e.validator) for e in errors])
    )
    assert expected_error_substr.lower() in error_messages.lower(), (
        f"Expected '{expected_error_substr}' in error messages, got: {error_messages}"
    )
