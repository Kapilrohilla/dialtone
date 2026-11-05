"""Agent -> dashboard authentication: a LiveKit-signed JWT whose identity names the caller's role."""

import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from livekit import api

logger = logging.getLogger(__name__)

if not (settings.LIVEKIT_API_KEY and settings.LIVEKIT_API_SECRET):
    # An empty secret would let anyone sign tokens, so refuse to start.
    raise ImproperlyConfigured("LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be set")

verifier = api.TokenVerifier(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)

REPORT_IDENTITY = "agent-report"
RUNTIME_IDENTITY = "agent-runtime"


def verify_agent(request, identity: str) -> bool:
    """True only for a valid bearer token signed with our LiveKit secret and issued to exactly `identity`."""
    bearer = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not bearer:
        return False
    try:
        claims = verifier.verify(bearer)
    except Exception:
        return False
    return claims is not None and claims.identity == identity
