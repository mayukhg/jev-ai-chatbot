"""Specialized System 1 decision engines built on Jev's Noul / Choice / Score primitives."""

from app.core.models import ScoreAnswer, UrgencyReadout


def score_readout(answer: ScoreAnswer, labels: list[str]) -> UrgencyReadout:
    """Converts a Score answer into a labeled readout using the most probable level."""
    distribution = {labels[int(level)]: p for level, p in answer.probabilities.items()}
    level = int(max(answer.probabilities, key=answer.probabilities.get))
    return UrgencyReadout(
        label=labels[level],
        level=level,
        expected_level=answer.score,
        confidence=answer.confidence,
        distribution=distribution,
    )
