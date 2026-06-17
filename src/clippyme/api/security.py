"""Trust/origin helpers for ClippyMe config endpoints."""
import ipaddress
import os
import time
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException, Request

DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
)


def parse_allowed_origins(raw_value: Optional[str] = None) -> List[str]:
    """Parse a comma-separated ALLOWED_ORIGINS env var with safe localhost defaults."""
    if raw_value is None:
        return list(DEFAULT_ALLOWED_ORIGINS)

    origins = [origin.strip().rstrip("/") for origin in raw_value.split(",") if origin.strip()]
    return origins or list(DEFAULT_ALLOWED_ORIGINS)


ALLOWED_ORIGINS = parse_allowed_origins(os.environ.get("ALLOWED_ORIGINS"))


def is_trusted_origin(origin: Optional[str]) -> bool:
    if not origin:
        return False
    return origin.rstrip("/") in ALLOWED_ORIGINS


def is_trusted_client_host(client_host: Optional[str]) -> bool:
    if not client_host:
        return False

    normalized_host = client_host.strip().lower()
    if normalized_host in {"127.0.0.1", "::1", "localhost"}:
        return True

    try:
        address = ipaddress.ip_address(normalized_host)
    except ValueError:
        return False

    return address.is_loopback or address.is_private


def require_trusted_config_request(request: Request) -> None:
    """Protect config endpoints from cross-site browser access."""
    origin = request.headers.get("origin")
    if origin:
        if is_trusted_origin(origin):
            return
        raise HTTPException(status_code=403, detail="Origin not allowed for config access.")

    client_host = request.client.host if request.client else ""
    if is_trusted_client_host(client_host):
        return

    raise HTTPException(status_code=403, detail="Config access requires a trusted local origin.")


# --- in-process rate limiting ----------------------------------------------
# Dependency-free per-client token bucket. Protects the compute-heavy endpoints
# (process/batch/publish) from a flood that would exhaust the job queue or
# Zernio quota. Status polling is intentionally NOT limited. State is in-memory
# (single-process self-host model); not shared across replicas.
_rate_state: Dict[Tuple[str, str], Tuple[float, float]] = {}


def _rate_limit_allow(key: Tuple[str, str], capacity: float, refill_per_sec: float, now: float) -> bool:
    """Token-bucket check. Returns True if a token was available (and consumed)."""
    tokens, last = _rate_state.get(key, (capacity, now))
    tokens = min(capacity, tokens + max(0.0, now - last) * refill_per_sec)
    if tokens < 1.0:
        _rate_state[key] = (tokens, now)
        return False
    _rate_state[key] = (tokens - 1.0, now)
    return True


def enforce_rate_limit(request: Request, bucket: str, capacity: float, refill_per_sec: float) -> None:
    """Raise HTTP 429 when the per-client bucket is empty.

    Disabled by setting RATE_LIMIT_ENABLED=0 (e.g. for load tests). Keyed by
    client IP + bucket name so different endpoints don't share a budget.
    """
    if os.environ.get("RATE_LIMIT_ENABLED", "1") != "1":
        return
    client_host = request.client.host if request.client else "unknown"
    if not _rate_limit_allow((bucket, client_host), capacity, refill_per_sec, time.monotonic()):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please slow down and retry shortly.",
        )
