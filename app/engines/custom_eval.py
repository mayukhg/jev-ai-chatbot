"""Generic playground: arbitrary state and user-defined Choice / Score / Noul questions."""

from app.core.client import JevClient
from app.core.models import ChoiceAnswer, CustomDecision, CustomDecisionInput, DecisionRequest, NoulAnswer, ScoreAnswer

NOUL_UNCERTAIN_BAND = (0.40, 0.60)


def calibration_reasons(answers: dict, confidence_threshold: float) -> list[str]:
    """Flags every answer that falls below the confidence threshold or is a near coin-flip."""
    reasons = []
    low, high = NOUL_UNCERTAIN_BAND
    for key, answer in answers.items():
        if isinstance(answer, (ChoiceAnswer, ScoreAnswer)) and answer.confidence < confidence_threshold:
            reasons.append(f"{key}: confidence {answer.confidence:.2f} < {confidence_threshold:.2f}")
        elif isinstance(answer, NoulAnswer) and low <= answer.noul <= high:
            reasons.append(f"{key}: probability {answer.noul:.2f} is near 0.5")
    return reasons


async def run_custom(client: JevClient, payload: CustomDecisionInput) -> CustomDecision:
    request = DecisionRequest(model=client.settings.jev_model, state=payload.state, questions=payload.questions)
    result = await client.decide(request)
    reasons = calibration_reasons(result.response.answers, payload.confidence_threshold)
    return CustomDecision(
        answers=result.response.answers,
        requires_human_escalation=bool(reasons),
        escalation_reasons=reasons,
        latency_ms=result.latency_ms,
        model=result.response.model,
        mock_mode=result.mock,
        usage=result.response.usage,
    )
