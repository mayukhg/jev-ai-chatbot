"""Video transcript clipping: standalone coherence (Noul) and hook potential (Score, 1-5)."""

from app.core.client import JevClient
from app.core.models import (
    ClipDecision,
    DecisionRequest,
    NoulCriteria,
    NoulQuestion,
    ScoreQuestion,
    TranscriptInput,
)

STANDALONE_THRESHOLD = 0.60
HOOK_THRESHOLD = 3.5
BORDERLINE_BAND = (0.40, 0.60)

HOOK_GUIDANCE = [
    "1: filler, logistics, or small talk with no hook.",
    "2: mildly informative but forgettable.",
    "3: a solid, useful point that some viewers will share.",
    "4: a surprising insight, strong opinion, or memorable story.",
    "5: an instantly gripping, quotable moment with viral potential.",
]


def build_clip_request(segment: TranscriptInput, model: str) -> DecisionRequest:
    state = {"segment": " ".join(segment.segment.split())}
    if segment.video_title:
        state["video_title"] = segment.video_title
    if segment.start or segment.end:
        state["timestamps"] = {"start": segment.start, "end": segment.end}
    return DecisionRequest(
        model=model,
        state=state,
        questions={
            "standalone": NoulQuestion(
                instructions="Does this excerpt represent a complete, standalone concept?",
                criteria=NoulCriteria(
                    true="A viewer with no context will understand the point; it has a clear beginning and end.",
                    false="The excerpt depends on earlier context, trails off, or cuts a thought mid-way.",
                ),
            ),
            "hook": ScoreQuestion(instructions="Rate the viral hook potential of this excerpt.", criteria=HOOK_GUIDANCE),
        },
    )


async def clip_transcript(client: JevClient, segment: TranscriptInput) -> ClipDecision:
    result = await client.decide(build_clip_request(segment, client.settings.jev_model))
    answers = result.response.answers
    standalone, hook = answers["standalone"], answers["hook"]

    hook_score = round(hook.score + 1, 4)  # levels are numbered from 0; the scale is 1-5
    hook_distribution = {str(int(level) + 1): p for level, p in hook.probabilities.items()}
    should_clip = standalone.noul >= STANDALONE_THRESHOLD and hook_score >= HOOK_THRESHOLD

    reasons = []
    low, high = BORDERLINE_BAND
    if low <= standalone.noul <= high:
        reasons.append(f"standalone probability {standalone.noul:.2f} is borderline")
    return ClipDecision(
        outcome="clip" if should_clip else "skip",
        confidence=standalone.noul if should_clip else 1 - standalone.noul,
        distribution={"standalone": standalone.noul, "not_standalone": round(1 - standalone.noul, 4)},
        standalone_probability=standalone.noul,
        hook_score=hook_score,
        hook_distribution=hook_distribution,
        requires_human_escalation=bool(reasons),
        escalation_reasons=reasons,
        latency_ms=result.latency_ms,
        model=result.response.model,
        mock_mode=result.mock,
        usage=result.response.usage,
        answers=answers,
    )
