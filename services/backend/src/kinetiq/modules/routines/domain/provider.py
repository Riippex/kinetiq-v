from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from kinetiq.modules.catalog.domain.entities import RoutineTemplate
from kinetiq.modules.progress.domain.entities import EvidenceSource
from kinetiq.modules.routines.domain.entities import RoutineEligibilityCriteria
from kinetiq.modules.routines.domain.errors import InvalidCoachingOutputError

if TYPE_CHECKING:
    from kinetiq.modules.progress.domain.entities import ProgressSummary


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
        progress_summary: ProgressSummary | None = None,
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

    Ranks eligible templates and formats evidence-backed explanations when progress data exists.
    """

    def rank_and_explain(
        self,
        eligible_templates: Sequence[RoutineTemplate],
        criteria: RoutineEligibilityCriteria,
        progress_summary: ProgressSummary | None = None,
    ) -> CoachingProposalOutput:
        if not eligible_templates:
            raise ValueError("Cannot rank or explain an empty sequence of templates")

        # 1. Determine template selection based on progress evidence
        selected = eligible_templates[0]
        evidence_notes: list[str] = []

        if progress_summary is not None and progress_summary.consistency.completed_count > 0:
            c = progress_summary.consistency
            consistency_pct = int(c.consistency_ratio * 100)

            # Check performance trends
            improving_exercises = [
                p.exercise_name
                for p in progress_summary.performance_projections
                if p.trend.value == "IMPROVING"
            ]

            if c.consistency_ratio >= 0.75 or len(improving_exercises) > 0:
                # High consistency / improving trend -> prefer progressive templates if available
                progressive = [
                    t
                    for t in eligible_templates
                    if "progressive" in t.code.lower()
                    or "advanced" in t.code.lower()
                    or "challenge" in t.code.lower()
                ]
                if progressive:
                    selected = progressive[0]

                count_str = f"{c.completed_count} completed sessions"
                note = f"Based on your {consistency_pct}% consistency ({count_str}"
                if c.current_streak_days > 0:
                    note += f", {c.current_streak_days}-day streak"
                note += ")"
                if improving_exercises:
                    note += f" and improving rep-volume trends in {', '.join(improving_exercises)}"
                evidence_notes.append(note)

            elif c.consistency_ratio < 0.5 or c.abandoned_count > 0:
                # Lower consistency -> prefer shorter / lighter volume templates
                shorter = sorted(eligible_templates, key=lambda t: t.estimated_duration_minutes)
                if shorter:
                    selected = shorter[0]

                evidence_notes.append(
                    f"Selected a manageable {selected.estimated_duration_minutes}-minute volume "
                    "to help rebuild workout consistency after recent skipped or incomplete "
                    "sessions"
                )

            gp = progress_summary.goal_progress
            if (
                gp
                and gp.progress_ratio is not None
                and gp.evidence_source is not EvidenceSource.MISSING
            ):
                g_pct = int(gp.progress_ratio * 100)
                evidence_notes.append(
                    f"You have reached {g_pct}% of your active goal ('{gp.description}')"
                )

        # 2. Build structured rationale combining criteria and evidence notes
        equipment_desc = (
            ", ".join(sorted(criteria.available_equipment))
            if criteria.available_equipment
            else "no equipment"
        )
        base_rationale = (
            f"Selected '{selected.title}' ({selected.estimated_duration_minutes} min) "
            f"to align with your target of {criteria.target_duration_minutes} minutes per workout. "
            f"Calibrated for {criteria.experience_level.lower()} experience level "
            f"with {equipment_desc}."
        )

        if evidence_notes:
            rationale = base_rationale + " " + " ".join(evidence_notes) + "."
        else:
            rationale = base_rationale

        return CoachingProposalOutput(
            recommended_template_code=selected.code,
            rationale=rationale,
        )
