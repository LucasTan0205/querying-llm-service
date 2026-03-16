from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def canonicalise_event_ids(event_ids: List[str]) -> List[str]:
    cleaned: List[str] = []
    seen = set()
    for value in event_ids:
        if value is None:
            continue
        value = value.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    cleaned.sort()
    return cleaned


class SummaryGenerateRequest(BaseModel):
    clubId: str = Field(min_length=1)
    eventIds: List[str] = Field(min_length=1)
    insights: List[Dict[str, Any]] = Field(default_factory=list)
    # promptId removed - using internal configuration

    @field_validator('clubId')
    @classmethod
    def trim_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('must be non-blank')
        return value


class SummaryGenerateResponse(BaseModel):
    summaryText: str
    # promptIdUsed removed - internal detail
    modelName: str
    temperature: float
    clubId: str
    eventIds: List[str]
    insightCount: int
    generatedAt: str


class CurrentPromptResponse(BaseModel):
    promptId: str
    version: str
    lastUpdated: str


PROMPT_BASE_URL = os.getenv('QUERYING_LLM_PROMPT_BASE_URL', 'http://localhost:8091')
LLM_BASE_URL = os.getenv('QUERYING_LLM_LLM_BASE_URL', 'http://localhost:8093')
TIMEOUT_MS = int(os.getenv('QUERYING_LLM_TIMEOUT_MS', '15000'))
TIMEOUT = httpx.Timeout(TIMEOUT_MS / 1000.0)

# New prompt configuration
DEFAULT_PROMPT_ID = os.getenv('QUERYING_LLM_DEFAULT_PROMPT_ID', 'summary-v2.1')
PROMPT_VERSION = os.getenv('QUERYING_LLM_PROMPT_VERSION', '2.1.0')

app = FastAPI(title='querying-llm', version='1.0.0')


async def fetch_prompt(client: httpx.AsyncClient, prompt_id: str) -> Dict[str, Any]:
    try:
        response = await client.get(f'{PROMPT_BASE_URL}/api/v1/prompts/{prompt_id}')
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail='Prompt not found') from exc
        raise HTTPException(status_code=502, detail=f'Prompt service error: {exc.response.text}') from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f'Prompt service unavailable: {exc}') from exc
    return response.json()


def build_user_prompt(club_id: str, event_ids: List[str], insights: List[Dict[str, Any]]) -> str:
    instruction = (
        'Using only the supplied insights, produce a concise summary of the most important themes, '
        'issues, and actionable follow-ups. Do not invent facts. If evidence is mixed, say so.'
    )
    insights_json = json.dumps(insights, ensure_ascii=False, indent=2)
    return (
        f'Club ID: {club_id}\n'
        f'Event IDs: {", ".join(event_ids)}\n'
        f'{instruction}\n\n'
        f'Insights JSON:\n{insights_json}'
    )


async def call_llm(client: httpx.AsyncClient, *, system_prompt: str, user_prompt: str, model_name: str,
                   temperature: float, max_tokens: int, metadata: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        'systemPrompt': system_prompt,
        'userPrompt': user_prompt,
        'model': model_name,
        'temperature': temperature,
        'maxTokens': max_tokens,
        'metadata': metadata,
    }
    try:
        response = await client.post(f'{LLM_BASE_URL}/api/v1/llm/generate', json=payload)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f'LLM service error: {exc.response.text}') from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f'LLM service unavailable: {exc}') from exc
    return response.json()


@app.get('/health')
def health() -> dict:
    return {'status': 'ok', 'service': 'querying-llm'}


@app.get('/api/v1/querying-llm/config/current-prompt-id', response_model=CurrentPromptResponse)
def get_current_prompt_id() -> CurrentPromptResponse:
    """Get the current prompt ID used for summary generation.
    
    This endpoint is used by manage-insights for cache fingerprinting.
    """
    return CurrentPromptResponse(
        promptId=DEFAULT_PROMPT_ID,
        version=PROMPT_VERSION,
        lastUpdated=utc_now()
    )


@app.post('/api/v1/querying-llm/summary:generate', response_model=SummaryGenerateResponse)
async def summarise(payload: SummaryGenerateRequest) -> SummaryGenerateResponse:
    event_ids = canonicalise_event_ids(payload.eventIds)
    if not event_ids:
        raise HTTPException(status_code=400, detail='eventIds must contain at least one non-blank value')

    insights = payload.insights
    # Use internal prompt configuration instead of request parameter
    current_prompt_id = DEFAULT_PROMPT_ID

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        prompt_cfg = await fetch_prompt(client, current_prompt_id)

        if not insights:
            return SummaryGenerateResponse(
                summaryText='No insights available for the selected events.',
                # promptIdUsed removed from response
                modelName=prompt_cfg['modelName'],
                temperature=float(prompt_cfg['temperature']),
                clubId=payload.clubId,
                eventIds=event_ids,
                insightCount=0,
                generatedAt=utc_now(),
            )

        user_prompt = build_user_prompt(payload.clubId, event_ids, insights)
        llm_result = await call_llm(
            client,
            system_prompt=prompt_cfg['template'],
            user_prompt=user_prompt,
            model_name=prompt_cfg['modelName'],
            temperature=float(prompt_cfg['temperature']),
            max_tokens=int(prompt_cfg['maxTokens']),
            metadata={
                'clubId': payload.clubId,
                'eventIds': event_ids,
                'promptId': current_prompt_id,  # Internal use only
                'insightCount': len(insights),
            },
        )

    return SummaryGenerateResponse(
        summaryText=llm_result['text'],
        # promptIdUsed removed from response
        modelName=prompt_cfg['modelName'],
        temperature=float(prompt_cfg['temperature']),
        clubId=payload.clubId,
        eventIds=event_ids,
        insightCount=len(insights),
        generatedAt=llm_result.get('generatedAt', utc_now()),
    )
