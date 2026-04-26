"""
Assumptions Tracker — audit trail for LLM judgment calls.

Every time the pipeline asks an LLM to make a decision (Stage 3 dictionary
drafting, Stage 6 value normalization), the decision is logged as an
assumption with confidence, impact, and rationale.

The tracker produces a JSON file that can be reviewed before delivery.
Critical assumptions (low confidence + high impact) are flagged for
human validation.

Inspired by nimrodfisher/data-analytics-skills analysis-assumptions-log.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


RISK_SCORES: dict[tuple[str, str], int] = {
    ("high", "critical"): 6,   ("high", "high"): 5,   ("high", "medium"): 3,
    ("medium", "critical"): 7, ("medium", "high"): 6,  ("medium", "medium"): 4,
    ("low", "critical"): 9,    ("low", "high"): 8,     ("low", "medium"): 5,
}

VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_IMPACT = {"low", "medium", "high", "critical"}
VALID_CATEGORIES = {"data", "business_logic", "normalization", "technical"}


@dataclass
class Assumption:
    """A single recorded assumption."""

    id: int
    stage: str
    category: str
    assumption: str
    rationale: str
    confidence: str
    impact_if_wrong: str
    validation_plan: str = ""
    validated: bool = False
    validation_result: str | None = None
    validation_notes: str | None = None

    @property
    def risk_score(self) -> int:
        return RISK_SCORES.get(
            (self.confidence, self.impact_if_wrong), 3
        )

    @property
    def is_critical(self) -> bool:
        return (
            not self.validated
            and self.confidence == "low"
            and self.impact_if_wrong in ("high", "critical")
        )


@dataclass
class AssumptionLog:
    """Container for all assumptions in a pipeline run."""

    pipeline_run: str = ""
    created: str = field(default_factory=lambda: str(date.today()))
    assumptions: list[Assumption] = field(default_factory=list)

    # -- mutators ----------------------------------------------------------

    def add(
        self,
        stage: str,
        category: str,
        assumption: str,
        rationale: str,
        confidence: str = "medium",
        impact_if_wrong: str = "medium",
        validation_plan: str = "",
    ) -> Assumption:
        """Add an assumption and return it."""
        entry = Assumption(
            id=len(self.assumptions) + 1,
            stage=stage,
            category=category,
            assumption=assumption,
            rationale=rationale,
            confidence=confidence,
            impact_if_wrong=impact_if_wrong,
            validation_plan=validation_plan,
        )
        self.assumptions.append(entry)
        return entry

    def validate(
        self, assumption_id: int, result: str, notes: str = ""
    ) -> None:
        """Mark an assumption as validated."""
        for a in self.assumptions:
            if a.id == assumption_id:
                a.validated = True
                a.validation_result = result
                a.validation_notes = notes
                return
        raise ValueError(f"Assumption {assumption_id} not found")

    # -- queries -----------------------------------------------------------

    @property
    def critical(self) -> list[Assumption]:
        """Unvalidated assumptions with low confidence and high+ impact."""
        return [a for a in self.assumptions if a.is_critical]

    @property
    def unvalidated(self) -> list[Assumption]:
        return [a for a in self.assumptions if not a.validated]

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "pipeline_run": self.pipeline_run,
            "created": self.created,
            "total_assumptions": len(self.assumptions),
            "validated_count": sum(1 for a in self.assumptions if a.validated),
            "critical_count": len(self.critical),
            "assumptions": [asdict(a) for a in self.assumptions],
        }
        # Inject computed risk_score into each assumption dict
        for ad, a in zip(d["assumptions"], self.assumptions):
            ad["risk_score"] = a.risk_score
            ad["is_critical"] = a.is_critical
        return d

    def save(self, path: str | Path) -> Path:
        """Write the log to a JSON file."""
        path = Path(path)
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path

    @classmethod
    def load(cls, path: str | Path) -> "AssumptionLog":
        """Load a previously saved log."""
        raw = json.loads(Path(path).read_text())
        log = cls(
            pipeline_run=raw.get("pipeline_run", ""),
            created=raw.get("created", ""),
        )
        for a in raw.get("assumptions", []):
            log.assumptions.append(
                Assumption(
                    id=a["id"],
                    stage=a["stage"],
                    category=a["category"],
                    assumption=a["assumption"],
                    rationale=a["rationale"],
                    confidence=a["confidence"],
                    impact_if_wrong=a["impact_if_wrong"],
                    validation_plan=a.get("validation_plan", ""),
                    validated=a.get("validated", False),
                    validation_result=a.get("validation_result"),
                    validation_notes=a.get("validation_notes"),
                )
            )
        return log

    def report(self) -> str:
        """Return a human-readable summary."""
        lines = [
            "=" * 60,
            f"ASSUMPTIONS LOG: {self.pipeline_run or '(unnamed run)'}",
            f"Created: {self.created}",
            "=" * 60,
            f"Total: {len(self.assumptions)} | "
            f"Validated: {sum(1 for a in self.assumptions if a.validated)} | "
            f"Critical: {len(self.critical)}",
        ]

        for a in self.assumptions:
            validated_str = (
                f"✓ {a.validation_result}" if a.validated else "✗ not validated"
            )
            marker = " ⚠ CRITICAL" if a.is_critical else ""
            lines.append(
                f"\n  #{a.id} [{a.stage}] "
                f"[{a.confidence.upper()} conf / {a.impact_if_wrong.upper()} impact "
                f"| risk={a.risk_score}]{marker}"
            )
            lines.append(f"    {a.assumption}")
            lines.append(f"    Rationale: {a.rationale}")
            lines.append(f"    Validation: {validated_str}")

        if self.critical:
            lines += [
                "",
                "⚠ CRITICAL ASSUMPTIONS REQUIRING VALIDATION:",
            ]
            for a in self.critical:
                lines.append(f"  #{a.id}: {a.assumption}")
                if a.validation_plan:
                    lines.append(f"    Plan: {a.validation_plan}")

        lines.append("=" * 60)
        return "\n".join(lines)
