"""Typed schemas for Jev questions, OpenRouter Decisions payloads, and engine results.

Question and answer shapes follow the OpenRouter Decisions API reference
(`POST /api/alpha/decisions`).
"""

from typing import Annotated, Any, Literal, Union

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

Guidance = Union[str, dict[str, Any], list[Any]]


# --------------------------------------------------------------------------- questions


class NoulCriteria(BaseModel):
    """Guidance for the true / false sides of a Noul question."""

    true: Guidance = "Yes, the statement holds for the given state."
    false: Guidance = "No, the statement does not hold for the given state."


class NoulQuestion(BaseModel):
    """A calibrated yes/no question. The answer will be the probability of `true`."""

    type: Literal["noul"] = "noul"
    instructions: Guidance
    criteria: NoulCriteria = Field(default_factory=NoulCriteria)


class ChoiceQuestion(BaseModel):
    """A categorical question. `criteria` maps each label to its guidance text."""

    type: Literal["choice"] = "choice"
    instructions: Guidance
    criteria: dict[str, Guidance | None]

    @field_validator("criteria")
    @classmethod
    def _at_least_two_options(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) < 2:
            raise ValueError("a choice question needs at least two options")
        return value


class ScoreQuestion(BaseModel):
    """An ordered-scale question. Each `criteria` item describes one level, lowest first.

    `scale` is accepted as an alias for `criteria`.
    """

    model_config = ConfigDict(populate_by_name=True)

    type: Literal["score"] = "score"
    instructions: Guidance
    criteria: list[Guidance] = Field(
        min_length=1, validation_alias=AliasChoices("criteria", "scale")
    )


Question = Annotated[Union[NoulQuestion, ChoiceQuestion, ScoreQuestion], Field(discriminator="type")]
State = Union[str, dict[str, Any], list[Any]]


class DecisionRequest(BaseModel):
    """The request body sent to the Decisions API."""

    model: str
    state: State
    questions: dict[str, Question] = Field(min_length=1)


# --------------------------------------------------------------------------- upstream answers


class NoulAnswer(BaseModel):
    type: Literal["noul"] = "noul"
    noul: float = Field(ge=0, le=1, description="Probability that the answer is true.")


class ChoiceAnswer(BaseModel):
    type: Literal["choice"] = "choice"
    choice: str
    confidence: float
    probabilities: dict[str, float]


class ScoreAnswer(BaseModel):
    type: Literal["score"] = "score"
    score: float = Field(description="Probability-weighted level, numbered from 0.")
    confidence: float
    probabilities: dict[str, float]
    legend: dict[str, Any] | None = None


Answer = Annotated[Union[NoulAnswer, ChoiceAnswer, ScoreAnswer], Field(discriminator="type")]


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None


class UpstreamDecisionResponse(BaseModel):
    """The Decisions API 200 response."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    model: str
    provider: str | None = None
    answers: dict[str, Answer]
    usage: Usage = Field(default_factory=Usage)


class DecisionResult(BaseModel):
    """An upstream response plus client-side execution metadata."""

    response: UpstreamDecisionResponse
    latency_ms: float
    mock: bool
    attempts: int = 1


# --------------------------------------------------------------------------- engine outputs


class EngineDecision(BaseModel):
    """Standardized output shared by every decision engine."""

    outcome: str
    confidence: float
    distribution: dict[str, float]
    requires_human_escalation: bool
    escalation_reasons: list[str] = Field(default_factory=list)
    latency_ms: float
    model: str
    mock_mode: bool
    usage: Usage = Field(default_factory=Usage)
    answers: dict[str, Answer]


class UrgencyReadout(BaseModel):
    label: str
    level: int
    expected_level: float
    confidence: float
    distribution: dict[str, float]


class TriageDecision(EngineDecision):
    category: str
    urgency: UrgencyReadout
    ambiguity_probability: float


class RouteDecision(EngineDecision):
    queue: str
    suggested_queue: str
    complexity: UrgencyReadout
    human_judgment_probability: float


class ClipDecision(EngineDecision):
    standalone_probability: float
    hook_score: float
    hook_distribution: dict[str, float]


class CustomDecision(BaseModel):
    """Generic playground output: raw typed answers plus a calibration summary."""

    answers: dict[str, Answer]
    requires_human_escalation: bool
    escalation_reasons: list[str] = Field(default_factory=list)
    latency_ms: float
    model: str
    mock_mode: bool
    usage: Usage = Field(default_factory=Usage)


# --------------------------------------------------------------------------- engine inputs


class TicketInput(BaseModel):
    text: str = Field(min_length=1)
    subject: str | None = None
    customer_tier: str | None = None
    channel: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskInput(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    requester: str | None = None
    deadline: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TranscriptInput(BaseModel):
    segment: str = Field(min_length=1)
    video_title: str | None = None
    start: str | None = None
    end: str | None = None


class CustomDecisionInput(BaseModel):
    state: State
    questions: dict[str, Question] = Field(min_length=1)
    confidence_threshold: float = Field(default=0.70, ge=0, le=1)
