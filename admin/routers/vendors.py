"""Vendor catalogue — live Bedrock inference profiles for APAC and US regions.

GET /admin/vendors

Fetches ListInferenceProfiles from ap-southeast-1 and us-east-1 in parallel,
filters to text/chat models only (strips image, video, embed providers), and
returns profiles grouped by region with human-readable labels.

IAM note: the admin role must allow bedrock:ListInferenceProfiles.
The existing deny on bedrock:InvokeModel* still prevents model invocation.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import boto3
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/admin/vendors", tags=["vendors"])

# ---------------------------------------------------------------------------
# Region config
# ---------------------------------------------------------------------------

_REGIONS: list[tuple[str, str, str]] = [
    (
        "ap-southeast-1",
        "APAC — ap-southeast-1",
        "Singapore region · data residency compliant",
    ),
    (
        "us-east-1",
        "US — us-east-1  (+~170 ms latency)",
        "Data processed outside SG — verify compliance before use",
    ),
]

# ---------------------------------------------------------------------------
# Text-model filter
# Strip profiles that are image generation, video, embedding, or other
# non-text modalities. Match against the full profile ID.
# ---------------------------------------------------------------------------

_SKIP = re.compile(
    r"stability|twelvelabs|\.embed|upscale|inpaint|erase-object"
    r"|outpaint|recolor|style-transfer|sketch|remove-background"
    r"|search-replace|search-recolor|image-control|image-style"
    r"|pegasus|marengo",
    re.IGNORECASE,
)


def _is_text_model(profile_id: str) -> bool:
    return not _SKIP.search(profile_id)


# ---------------------------------------------------------------------------
# Label derivation
# ---------------------------------------------------------------------------

_PROVIDER_NAMES: dict[str, str] = {
    "anthropic": "Anthropic",
    "amazon":    "Amazon",
    "meta":      "Meta",
    "mistral":   "Mistral",
    "deepseek":  "DeepSeek",
    "writer":    "Writer",
    "cohere":    "Cohere",
    "ai21":      "AI21",
}

# Suffixes to strip from model name segment
_VERSION_RE = re.compile(
    r"(-\d{8})?(-v\d+:\d+|-v\d+\.\d+)?$"
    r"|(-\d{8}-v\d+:\d+)$"
)
_INSTRUCT_RE = re.compile(r"-instruct$", re.IGNORECASE)


def _make_label(profile_id: str) -> str:
    """Derive a readable label from an inference profile ID.

    Examples
    --------
    apac.anthropic.claude-sonnet-4-20250514-v1:0  → Anthropic — Claude Sonnet 4
    us.meta.llama4-maverick-17b-instruct-v1:0     → Meta — Llama 4 Maverick 17B
    us.mistral.pixtral-large-2502-v1:0            → Mistral — Pixtral Large
    us.amazon.nova-premier-v1:0                   → Amazon — Nova Premier
    """
    parts = profile_id.split(".")
    if len(parts) < 3:
        return profile_id

    provider_key = parts[1].lower()
    provider = _PROVIDER_NAMES.get(provider_key, parts[1].capitalize())

    # Remaining parts form the model segment (join back with ".")
    model_raw = ".".join(parts[2:])

    # Strip version/date suffixes
    model_clean = _VERSION_RE.sub("", model_raw)
    model_clean = _INSTRUCT_RE.sub("", model_clean)

    # Collapse separators and title-case
    model_clean = re.sub(r"[-_]+", " ", model_clean).strip()

    return f"{provider} — {model_clean.title()}"


# ---------------------------------------------------------------------------
# Bedrock fetch (blocking — run in thread pool)
# ---------------------------------------------------------------------------


def _fetch_profiles(region: str) -> list[dict[str, Any]]:
    client = boto3.client("bedrock", region_name=region)
    paginator = client.get_paginator("list_inference_profiles")
    profiles: list[dict[str, Any]] = []
    for page in paginator.paginate():
        profiles.extend(page.get("inferenceProfileSummaries", []))
    return profiles


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class VendorModel(BaseModel):
    id: str
    label: str


class VendorGroup(BaseModel):
    region: str
    region_label: str
    note: str
    models: list[VendorModel]


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get("", response_model=list[VendorGroup])
async def list_vendors() -> list[VendorGroup]:
    """Return active text/chat Bedrock inference profiles grouped by region."""
    fetched = await asyncio.gather(
        *[asyncio.to_thread(_fetch_profiles, region) for region, _, _ in _REGIONS],
        return_exceptions=True,
    )

    groups: list[VendorGroup] = []
    for (region, region_label, note), result in zip(_REGIONS, fetched):
        profiles: list[dict[str, Any]] = result if not isinstance(result, Exception) else []

        models = [
            VendorModel(id=p["inferenceProfileId"], label=_make_label(p["inferenceProfileId"]))
            for p in profiles
            if p.get("status") == "ACTIVE" and _is_text_model(p.get("inferenceProfileId", ""))
        ]
        models.sort(key=lambda m: m.id)

        groups.append(VendorGroup(
            region=region,
            region_label=region_label,
            note=note,
            models=models,
        ))

    return groups
