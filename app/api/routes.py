"""REST endpoints for the decision engines."""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.client import JevAPIError, JevClient
from app.core.models import (
    ClipDecision,
    CustomDecision,
    CustomDecisionInput,
    RouteDecision,
    TaskInput,
    TicketInput,
    TranscriptInput,
    TriageDecision,
)
from app.engines.custom_eval import run_custom
from app.engines.task_router import route_task
from app.engines.ticket_triage import triage_ticket
from app.engines.transcript_clipper import clip_transcript

router = APIRouter(prefix="/api/v1")


def get_client(request: Request) -> JevClient:
    return request.app.state.jev_client


async def _run(coro):
    try:
        return await coro
    except JevAPIError as exc:
        status = 504 if exc.status_code is None else 502
        raise HTTPException(status_code=status, detail={"message": str(exc), "upstream_status": exc.status_code})


@router.get("/health")
async def health(client: JevClient = Depends(get_client)) -> dict:
    settings = client.settings
    return {
        "status": "ok",
        "model": settings.jev_model,
        "mock_mode": client.mock_mode,
        "mock_reason": settings.mock_reason,
        "decisions_url": settings.openrouter_decisions_url,
    }


@router.post("/triage", response_model=TriageDecision)
async def triage(ticket: TicketInput, client: JevClient = Depends(get_client)):
    return await _run(triage_ticket(client, ticket))


@router.post("/route", response_model=RouteDecision)
async def route(task: TaskInput, client: JevClient = Depends(get_client)):
    return await _run(route_task(client, task))


@router.post("/clip", response_model=ClipDecision)
async def clip(segment: TranscriptInput, client: JevClient = Depends(get_client)):
    return await _run(clip_transcript(client, segment))


@router.post("/decide", response_model=CustomDecision)
async def decide(payload: CustomDecisionInput, client: JevClient = Depends(get_client)):
    return await _run(run_custom(client, payload))
