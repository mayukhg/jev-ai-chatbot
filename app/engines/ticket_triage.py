"""Support ticket triage: category (Choice), urgency (Score), and ambiguity (Noul)."""

from app.core.client import JevClient
from app.core.models import (
    ChoiceAnswer,
    ChoiceQuestion,
    DecisionRequest,
    NoulAnswer,
    NoulCriteria,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
    TicketInput,
    TriageDecision,
)
from app.engines import score_readout

AMBIGUITY_THRESHOLD = 0.40
CATEGORY_CONFIDENCE_THRESHOLD = 0.70

CATEGORIES = {
    "billing": "Invoices, payments, charges, refunds, pricing, and subscription tiers or plans.",
    "technical": "Bugs, errors, crashes, outages, and broken or slow functionality.",
    "security": "Compromised or hacked accounts, suspicious logins, password resets, and 2FA failures.",
    "feature": "New capability requests, enhancements, integrations, and UX suggestions.",
}

URGENCY_LABELS = ["P4 Low", "P3 Medium", "P2 High", "P1 Critical"]
URGENCY_GUIDANCE = [
    "P4 Low: questions, suggestions, or cosmetic issues with no business impact.",
    "P3 Medium: a single user is inconvenienced but a workaround exists.",
    "P2 High: core functionality broken or money at stake for a customer, no workaround.",
    "P1 Critical: security breach, data loss, or outage affecting many users; act immediately.",
]


def normalize_ticket(ticket: TicketInput) -> dict:
    """Normalizes ticket text and metadata into a compact state object."""
    state: dict = {"body": " ".join(ticket.text.split())}
    if ticket.subject:
        state["subject"] = ticket.subject.strip()
    meta = {k: v for k, v in {"customer_tier": ticket.customer_tier, "channel": ticket.channel}.items() if v}
    meta.update(ticket.metadata)
    if meta:
        state["metadata"] = meta
    return state


def build_triage_request(ticket: TicketInput, model: str) -> DecisionRequest:
    return DecisionRequest(
        model=model,
        state=normalize_ticket(ticket),
        questions={
            "category": ChoiceQuestion(instructions="Categorize the support ticket.", criteria=CATEGORIES),
            "urgency": ScoreQuestion(instructions="Rate the urgency of the ticket.", criteria=URGENCY_GUIDANCE),
            "ambiguity": NoulQuestion(
                instructions=(
                    "Is this support ticket too ambiguous or incomplete for an agent to act on "
                    "without first asking the customer a clarifying question?"
                ),
                criteria=NoulCriteria(
                    true=(
                        "The agent cannot tell what the problem or request is, which product area it "
                        "concerns, or what outcome the customer wants."
                    ),
                    false=(
                        "The customer's problem or request and the desired outcome are clear enough to "
                        "start working on; routine lookups such as account details are fine."
                    ),
                ),
            ),
        },
    )


def evaluate_escalation(category_confidence: float, ambiguity_probability: float) -> list[str]:
    """Calibration gate. Returns the reasons a human will review the ticket (empty = automate)."""
    reasons = []
    if ambiguity_probability > AMBIGUITY_THRESHOLD:
        reasons.append(f"ambiguity probability {ambiguity_probability:.2f} > {AMBIGUITY_THRESHOLD:.2f}")
    if category_confidence < CATEGORY_CONFIDENCE_THRESHOLD:
        reasons.append(f"category confidence {category_confidence:.2f} < {CATEGORY_CONFIDENCE_THRESHOLD:.2f}")
    return reasons


async def triage_ticket(client: JevClient, ticket: TicketInput) -> TriageDecision:
    result = await client.decide(build_triage_request(ticket, client.settings.jev_model))
    answers = result.response.answers
    category: ChoiceAnswer = answers["category"]
    urgency: ScoreAnswer = answers["urgency"]
    ambiguity: NoulAnswer = answers["ambiguity"]

    reasons = evaluate_escalation(category.confidence, ambiguity.noul)
    return TriageDecision(
        outcome=category.choice,
        category=category.choice,
        confidence=category.confidence,
        distribution=category.probabilities,
        urgency=score_readout(urgency, URGENCY_LABELS),
        ambiguity_probability=ambiguity.noul,
        requires_human_escalation=bool(reasons),
        escalation_reasons=reasons,
        latency_ms=result.latency_ms,
        model=result.response.model,
        mock_mode=result.mock,
        usage=result.response.usage,
        answers=answers,
    )
