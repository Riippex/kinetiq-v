import pytest

from kinetiq.modules.catalog.domain.entities import RoutineTemplate, RoutineTemplateItem
from kinetiq.modules.routines.domain.entities import RoutineEligibilityCriteria
from kinetiq.modules.routines.domain.errors import InvalidCoachingOutputError
from kinetiq.modules.routines.domain.provider import (
    CoachingProposalOutput,
    DeterministicCoachingProvider,
    validate_coaching_output,
)


@pytest.fixture
def sample_template() -> RoutineTemplate:
    return RoutineTemplate(
        code="template-foundation-v1",
        version=1,
        title="Full Body Foundation",
        description="Foundation workout",
        target_goal_code="goal-habit",
        estimated_duration_minutes=15,
        items=(
            RoutineTemplateItem(
                exercise_code="ex-squat",
                order=1,
                sets=3,
                repetitions=10,
            ),
        ),
    )


def test_validate_coaching_output_accepts_valid_recommendation(
    sample_template: RoutineTemplate,
) -> None:
    output = CoachingProposalOutput(
        recommended_template_code="template-foundation-v1",
        rationale="Structured bodyweight routine matching your consistency goals.",
    )

    validated = validate_coaching_output(output, [sample_template])
    assert validated.recommended_template_code == "template-foundation-v1"
    assert "consistency goals" in validated.rationale


def test_validate_coaching_output_rejects_hallucinated_template_code(
    sample_template: RoutineTemplate,
) -> None:
    output = CoachingProposalOutput(
        recommended_template_code="template-invented-by-llm",
        rationale="A magical unverified routine.",
    )

    with pytest.raises(InvalidCoachingOutputError) as exc:
        validate_coaching_output(output, [sample_template])
    assert "template-invented-by-llm" in str(exc.value)


def test_validate_coaching_output_rejects_empty_or_short_rationale(
    sample_template: RoutineTemplate,
) -> None:
    output = CoachingProposalOutput(
        recommended_template_code="template-foundation-v1",
        rationale="Too short",
    )

    with pytest.raises(InvalidCoachingOutputError) as exc:
        validate_coaching_output(output, [sample_template])
    assert "too short" in str(exc.value)


def test_validate_coaching_output_rejects_excessively_long_rationale(
    sample_template: RoutineTemplate,
) -> None:
    output = CoachingProposalOutput(
        recommended_template_code="template-foundation-v1",
        rationale="A" * 2001,
    )

    with pytest.raises(InvalidCoachingOutputError) as exc:
        validate_coaching_output(output, [sample_template])
    assert "maximum allowed length" in str(exc.value)


def test_deterministic_coaching_provider_generates_coherent_rationale(
    sample_template: RoutineTemplate,
) -> None:
    provider = DeterministicCoachingProvider()
    criteria = RoutineEligibilityCriteria(
        available_equipment=frozenset({"NONE"}),
        target_duration_minutes=15,
        experience_level="RETURNING",
        target_goal_code="goal-habit",
    )

    output = provider.rank_and_explain([sample_template], criteria)
    assert output.recommended_template_code == "template-foundation-v1"
    assert "Full Body Foundation" in output.rationale
    assert "15 min" in output.rationale
    assert "returning" in output.rationale


def test_deterministic_coaching_provider_rejects_empty_templates() -> None:
    provider = DeterministicCoachingProvider()
    criteria = RoutineEligibilityCriteria(
        available_equipment=frozenset({"NONE"}),
        target_duration_minutes=15,
        experience_level="RETURNING",
    )

    with pytest.raises(ValueError) as exc:
        provider.rank_and_explain([], criteria)
    assert "empty sequence" in str(exc.value)
