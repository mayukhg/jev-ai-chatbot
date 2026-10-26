import pytest

from app.core.client import JevClient
from app.core.models import DecisionResult, TicketInput, UpstreamDecisionResponse
from app.engines import ticket_triage
from app.engines.ticket_triage import evaluate_escalation, triage_ticket


@pytest.mark.parametrize(
    ("confidence", "ambiguity", "escalate"),
    [
        (0.95, 0.10, False),
        (0.70, 0.40, False),  # exactly on both thresholds → automated
        (0.6999, 0.10, True),  # confidence just under the gate
        (0.95, 0.4001, True),  # ambiguity just over the gate
        (0.50, 0.80, True),
    ],
)
def test_calibration_gate_boundaries(confidence, ambiguity, escalate):
    assert bool(evaluate_escalation(confidence, ambiguity)) is escalate


def test_gate_reports_each_failed_check():
    reasons = evaluate_escalation(0.5, 0.8)
    assert len(reasons) == 2
    assert any("ambiguity" in r for r in reasons) and any("category" in r for r in reasons)


class FakeClient(JevClient):
    """Returns a fixed upstream response so engine logic can be tested in isolation."""

    def __init__(self, settings, answers):
        super().__init__(settings)
        self._answers = answers

    async def decide(self, request):
        assert set(request.questions) == {"category", "urgency", "ambiguity"}
        response = UpstreamDecisionResponse.model_validate({"model": request.model, "answers": self._answers})
        return DecisionResult(response=response, latency_ms=42.0, mock=False)


def _answers(confidence: float, ambiguity: float) -> dict:
    rest = (1 - confidence) / 3
    return {
        "category": {
            "type": "choice",
            "choice": "technical",
            "confidence": confidence,
            "probabilities": {"technical": confidence, "billing": rest, "security": rest, "feature": rest},
        },
        "urgency": {
            "type": "score",
            "score": 2.4,
            "confidence": 0.6,
            "probabilities": {"0": 0.05, "1": 0.1, "2": 0.25, "3": 0.6},
        },
        "ambiguity": {"type": "noul", "noul": ambiguity},
    }


async def test_low_confidence_flips_escalation(mock_settings):
    client = FakeClient(mock_settings, _answers(confidence=0.55, ambiguity=0.05))
    decision = await triage_ticket(client, TicketInput(text="Something is off with the app"))
    assert decision.requires_human_escalation is True
    assert decision.category == "technical"
    assert decision.latency_ms == 42.0


async def test_high_ambiguity_flips_escalation(mock_settings):
    client = FakeClient(mock_settings, _answers(confidence=0.92, ambiguity=0.65))
    decision = await triage_ticket(client, TicketInput(text="app crashed again"))
    assert decision.requires_human_escalation is True
    assert decision.ambiguity_probability == 0.65


async def test_confident_clear_ticket_is_automated(mock_settings):
    client = FakeClient(mock_settings, _answers(confidence=0.92, ambiguity=0.08))
    decision = await triage_ticket(client, TicketInput(text="Export fails with error 500 on step 3"))
    assert decision.requires_human_escalation is False
    assert decision.escalation_reasons == []
    assert decision.urgency.label == "P1 Critical"
    assert decision.urgency.level == 3


def test_ticket_normalization_includes_metadata():
    state = ticket_triage.normalize_ticket(
        TicketInput(text="  charged   twice ", subject="Refund", customer_tier="pro", metadata={"region": "EU"})
    )
    assert state == {"body": "charged twice", "subject": "Refund", "metadata": {"customer_tier": "pro", "region": "EU"}}


async def test_mock_mode_presets_behave_sensibly(mock_settings):
    client = JevClient(mock_settings)
    billing = await triage_ticket(
        client,
        TicketInput(text="My card was charged twice for invoice #4821. Please refund the duplicate payment for my subscription."),
    )
    assert billing.category == "billing"
    cryptic = await triage_ticket(client, TicketInput(text="app crashed again"))
    assert cryptic.requires_human_escalation is True
