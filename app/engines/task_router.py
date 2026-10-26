"""Work-item routing: target queue (Choice), complexity (Score), and human-judgment check (Noul)."""

from app.core.client import JevClient
from app.core.models import (
    ChoiceQuestion,
    DecisionRequest,
    NoulCriteria,
    NoulQuestion,
    RouteDecision,
    ScoreQuestion,
    TaskInput,
)
from app.engines import score_readout

HUMAN_REVIEW_QUEUE = "human_review"
QUEUE_CONFIDENCE_THRESHOLD = 0.65
HUMAN_JUDGMENT_THRESHOLD = 0.50

QUEUES = {
    "engineering": "Code changes, bugs, deployments, infrastructure, APIs, and integrations.",
    "data_analytics": "Reports, dashboards, metrics, SQL queries, data exports, and forecasting.",
    "finance_ops": "Invoices, budgets, expenses, procurement, payroll, and vendor payments.",
    "legal_compliance": "Contracts, NDAs, privacy, GDPR, audits, policy, and regulatory questions.",
    "customer_success": "Customer onboarding, renewals, account health, escalations, and training.",
}

COMPLEXITY_LABELS = ["S", "M", "L", "XL"]
COMPLEXITY_GUIDANCE = [
    "S: a quick, well-defined task under an hour.",
    "M: a scoped task of a few hours to a day.",
    "L: multi-day work that touches several systems or people.",
    "XL: a cross-team project lasting weeks with significant risk.",
]


def build_route_request(task: TaskInput, model: str) -> DecisionRequest:
    state = {"title": task.title.strip(), "description": " ".join(task.description.split())}
    for key in ("requester", "deadline"):
        if getattr(task, key):
            state[key] = getattr(task, key)
    if task.metadata:
        state["metadata"] = task.metadata
    return DecisionRequest(
        model=model,
        state=state,
        questions={
            "queue": ChoiceQuestion(instructions="Which execution queue will own this work item?", criteria=QUEUES),
            "complexity": ScoreQuestion(instructions="Estimate the size of the work item.", criteria=COMPLEXITY_GUIDANCE),
            "human_judgment": NoulQuestion(
                instructions="Does this task require human judgment before it is executed?",
                criteria=NoulCriteria(
                    true="Sensitive, irreversible, legal, financial approval, or policy-exception work.",
                    false="Routine, reversible work that a queue can execute directly.",
                ),
            ),
        },
    )


def evaluate_routing(queue_confidence: float, human_judgment_probability: float) -> list[str]:
    """Returns the reasons the work item will go to human review (empty = dispatch)."""
    reasons = []
    if queue_confidence < QUEUE_CONFIDENCE_THRESHOLD:
        reasons.append(f"queue confidence {queue_confidence:.2f} < {QUEUE_CONFIDENCE_THRESHOLD:.2f}")
    if human_judgment_probability > HUMAN_JUDGMENT_THRESHOLD:
        reasons.append(
            f"human-judgment probability {human_judgment_probability:.2f} > {HUMAN_JUDGMENT_THRESHOLD:.2f}"
        )
    return reasons


async def route_task(client: JevClient, task: TaskInput) -> RouteDecision:
    result = await client.decide(build_route_request(task, client.settings.jev_model))
    answers = result.response.answers
    queue, complexity, judgment = answers["queue"], answers["complexity"], answers["human_judgment"]

    reasons = evaluate_routing(queue.confidence, judgment.noul)
    target = HUMAN_REVIEW_QUEUE if reasons else queue.choice
    return RouteDecision(
        outcome=target,
        queue=target,
        suggested_queue=queue.choice,
        confidence=queue.confidence,
        distribution=queue.probabilities,
        complexity=score_readout(complexity, COMPLEXITY_LABELS),
        human_judgment_probability=judgment.noul,
        requires_human_escalation=bool(reasons),
        escalation_reasons=reasons,
        latency_ms=result.latency_ms,
        model=result.response.model,
        mock_mode=result.mock,
        usage=result.response.usage,
        answers=answers,
    )
