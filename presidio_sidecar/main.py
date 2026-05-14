"""Presidio sidecar: anonymize endpoint.

Exposes POST /anonymize and GET /health.
Runs as a persistent ECS Fargate service so the ~200MB spaCy model
stays resident between requests (CLAUDE.md §7 Redactor).

High-sensitivity entities are redacted and tokenised.
Contextual entities (LOCATION, PERSON, etc.) are left raw.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI
from presidio_analyzer import AnalyzerEngine  # type: ignore[import-untyped]
from presidio_anonymizer import AnonymizerEngine  # type: ignore[import-untyped]
from presidio_anonymizer.entities import OperatorConfig  # type: ignore[import-untyped]
from pydantic import BaseModel

from presidio_sidecar.recognisers import get_singapore_recognizers

# Entities to redact (high-sensitivity — see architecture.md §PII redaction)
_REDACT_ENTITIES = {
    "SG_NRIC", "SG_FIN", "SG_UEN", "SG_PASSPORT",
    "CREDIT_CARD", "IBAN_CODE",
}

app = FastAPI(title="Presidio Sidecar")

# Initialise once at startup — spaCy model load is expensive
_analyzer: AnalyzerEngine | None = None
_anonymizer: AnonymizerEngine | None = None


@app.on_event("startup")
async def startup() -> None:
    global _analyzer, _anonymizer  # noqa: PLW0603
    _analyzer = AnalyzerEngine()
    for rec in get_singapore_recognizers():
        _analyzer.registry.add_recognizer(rec)
    _anonymizer = AnonymizerEngine()


class AnonymizeRequest(BaseModel):
    text: str
    correlation_id: str


class AnonymizeResponse(BaseModel):
    redacted_text: str
    entity_types: list[str]
    entity_count: int
    tokens: dict[str, str]


@app.post("/anonymize", response_model=AnonymizeResponse)
async def anonymize(request: AnonymizeRequest) -> AnonymizeResponse:
    assert _analyzer is not None and _anonymizer is not None

    results = _analyzer.analyze(
        text=request.text,
        entities=list(_REDACT_ENTITIES),
        language="en",
    )

    if not results:
        return AnonymizeResponse(
            redacted_text=request.text,
            entity_types=[],
            entity_count=0,
            tokens={},
        )

    # Generate stable tokens per entity occurrence
    token_map: dict[str, str] = {}
    operators: dict[str, Any] = {}
    for result in results:
        token = f"VAULT_{uuid.uuid4().hex[:12].upper()}"
        original = request.text[result.start:result.end]
        token_map[token] = original
        operators[result.entity_type] = OperatorConfig("replace", {"new_value": token})

    anonymized = _anonymizer.anonymize(
        text=request.text,
        analyzer_results=results,
        operators=operators,
    )

    entity_types = list({r.entity_type for r in results})

    return AnonymizeResponse(
        redacted_text=anonymized.text,
        entity_types=entity_types,
        entity_count=len(results),
        tokens=token_map,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
