from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from kinetiq.modules.catalog.domain.entities import RoutineTemplate
from kinetiq.modules.routines.domain.entities import RoutineEligibilityCriteria
from kinetiq.modules.routines.domain.errors import InvalidCoachingOutputError


@dataclass(frozen=True, slots=True)
class CoachingProposalOutput:
    recommended_template_code: str
    rationale: str

    def __post_init__(self) -> None:
        if not self.recommended_template_code.strip():
            raise ValueError("Recommended template code cannot be empty")
        if not self.rationale.strip():
            raise ValueError("Rationale cannot be empty")


class RoutineCoachingProvider(Protocol):
    """Protocol for ranking eligible templates and providing an athlete explanation."""

    def rank_and_explain(
        self,
        eligible_templates: Sequence[RoutineTemplate],
        criteria: RoutineEligibilityCriteria,
    ) -> CoachingProposalOutput: ...


def validate_coaching_output(
    output: CoachingProposalOutput,
    eligible_templates: Sequence[RoutineTemplate],
) -> CoachingProposalOutput:
    """Validate provider output against catalog rules.

    Rejects:
    - Recommendations referring to template codes not in the eligible catalog list.
    - Empty, truncated, or excessively long rationales.
    """
    eligible_codes = {t.code for t in eligible_templates}
    if output.recommended_template_code not in eligible_codes:
        raise InvalidCoachingOutputError(
            f"Provider recommended template '{output.recommended_template_code}' "
            f"which is not among the eligible catalog templates: {sorted(eligible_codes)}"
        )

    clean_rationale = output.rationale.strip()
    if len(clean_rationale) < 10:
        raise InvalidCoachingOutputError("Provider rationale is too short to be informative")
    if len(clean_rationale) > 2000:
        raise InvalidCoachingOutputError("Provider rationale exceeds maximum allowed length")

    return CoachingProposalOutput(
        recommended_template_code=output.recommended_template_code,
        rationale=clean_rationale,
    )


class DeterministicCoachingProvider:
    """Built-in deterministic provider used directly or as safe fallback.

    Selects the highest ranked template by duration match and formats a structured explanation.
    """

    def rank_and_explain(
        self,
        eligible_templates: Sequence[RoutineTemplate],
        criteria: RoutineEligibilityCriteria,
    ) -> CoachingProposalOutput:
        if not eligible_templates:
            raise ValueError("Cannot rank or explain an empty sequence of templates")

        selected = eligible_templates[0]
        equipment_desc = (
            ", ".join(sorted(criteria.available_equipment))
            if criteria.available_equipment
            else "no equipment"
        )
        rationale = (
            f"Selected '{selected.title}' ({selected.estimated_duration_minutes} min) "
            f"to align with your target of {criteria.target_duration_minutes} minutes per workout. "
            f"Calibrated for {criteria.experience_level.lower()} experience level "
            f"with {equipment_desc}."
        )

        return CoachingProposalOutput(
            recommended_template_code=selected.code,
            rationale=rationale,
        )
