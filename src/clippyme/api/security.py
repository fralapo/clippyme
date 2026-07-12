"""Trust/origin helpers for ClippyMe config endpoints."""
import hmac
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


def _trust_proxy_enabled() -> bool:
    """Whether to honour X-Forwarded-For / X-Real-IP for client identity.

    OFF by default: when the app is reachable directly, those headers are
    fully attacker-controlled, so trusting them would let any client spoof
    its IP to dodge rate limiting or forge a "trusted" private address.
    Set TRUST_PROXY=1 only when ClippyMe sits behind exactly one reverse
    proxy (nginx/Traefik/uvicorn --proxy-headers). The proxy may either
    overwrite X-Forwarded-For or append to it (nginx's
    $proxy_add_x_forwarded_for) — client_ip reads the LAST hop, which is
    the address the proxy itself wrote, so a client-forged prefix is
    ignored either way.
    """
    return os.environ.get("TRUST_PROXY", "0") == "1"


def client_ip(request: Request) -> str:
    """Best-effort real client IP used for trust + rate-limit decisions.

    Forwarded headers (X-Forwarded-For / X-Real-IP) are honoured ONLY when
    both (a) TRUST_PROXY=1 and (b) the immediate TCP peer is itself a trusted
    private/loopback address — i.e. the reverse proxy. This second gate means
    that even if TRUST_PROXY is accidentally left on while the app is also
    reachable directly from the internet, a public attacker connecting
    straight to the socket cannot spoof its IP (its peer address is public, so
    its forged X-Forwarded-For is ignored and the real peer IP is used). A
    legitimate LAN client behind the proxy is unaffected: its real address
    arrives via X-Forwarded-For while the peer is the (private) proxy.
    Otherwise we use the socket peer address, which the client can't spoof.

    Within X-Forwarded-For we take the LAST hop, not the first. The shipped
    nginx.conf uses $proxy_add_x_forwarded_for, which APPENDS the peer to any
    incoming header instead of overwriting it — so the first hop is
    client-controlled ("X-Forwarded-For: 127.0.0.1" would spoof loopback
    trust and dodge per-IP rate limits), while the last hop is the value the
    trusted proxy itself appended: the real client address. With a proxy
    that overwrites the header there is only one hop and last == first, so
    this is safe for both proxy configurations. (Only a single trusted
    proxy is supported; a chain would need a trusted-hop count.)
    """
    peer = request.client.host if request.client else ""
    if _trust_proxy_enabled() and is_trusted_client_host(peer):
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[-1].strip()
        real = request.headers.get("x-real-ip")
        if real:
            return real.strip()
    return peer


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
    """Protect config + state-changing endpoints from cross-site browser access.

    Three layers, checked in order:

    1. ``Sec-Fetch-Site`` — a *forbidden* request header set by the browser and
       not writable from JavaScript. Any value of ``cross-site`` / ``same-site``
       means a different origin initiated the request, so we reject outright.
       This closes the CSRF hole where a plain HTML ``<form>`` POST (which omits
       ``Origin`` in some browser/network configs) would otherwise fall through
       to the private-IP branch below and be trusted.
    2. ``Origin`` — when present it must match the allow-list.
    3. Private/loopback client IP — only reached for non-browser clients (curl,
       CLI scripts) that send neither ``Sec-Fetch-Site`` nor ``Origin``.
    """
    sec_fetch_site = request.headers.get("sec-fetch-site")
    if sec_fetch_site in ("cross-site", "same-site"):
        raise HTTPException(status_code=403, detail="Cross-site requests are not allowed.")

    origin = request.headers.get("origin")
    if origin:
        if is_trusted_origin(origin):
            return
        raise HTTPException(status_code=403, detail="Origin not allowed for config access.")

    client_host = client_ip(request)
    if is_trusted_client_host(client_host):
        return

    raise HTTPException(status_code=403, detail="Config access requires a trusted local origin.")


# --- optional API token (deliberate LAN deployments) ------------------------
# The trust model above treats every private-network peer as an authorized
# client, so CLIPPYME_BIND=0.0.0.0 extends config/state access to the whole
# LAN. CLIPPYME_API_TOKEN restores per-client auth for that case: when set,
# every /api request must also carry the shared secret. Unset (the default,
# loopback self-host) the check is a no-op and behavior is unchanged.


def configured_api_token() -> Optional[str]:
    """The shared secret from CLIPPYME_API_TOKEN, or None when auth is off.

    Read per-request (not cached at import) so tests and container restarts
    with a changed env behave predictably.
    """
    token = os.environ.get("CLIPPYME_API_TOKEN", "").strip()
    return token or None


def enforce_api_token(request: Request) -> None:
    """Raise HTTP 401 unless the request carries the configured token.

    Accepts either ``X-API-Token: <token>`` or ``Authorization: Bearer
    <token>``. Comparison is constant-time (hmac.compare_digest) so the token
    can't be recovered byte-by-byte via timing. No-op when no token is set.
    """
    expected = configured_api_token()
    if expected is None:
        return

    supplied = request.headers.get("x-api-token", "").strip()
    if not supplied:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()

    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Valid API token required.")


# --- in-process rate limiting ----------------------------------------------
# Dependency-free per-client token bucket. Protects the compute-heavy endpoints
# (process/batch/publish) from a flood that would exhaust the job queue or
# Zernio quota. Status polling is intentionally NOT limited. State is in-memory
# (single-process self-host model); not shared across replicas.
_rate_state: Dict[Tuple[str, str], Tuple[float, float]] = {}
# Hard cap on tracked buckets so a flood of unique client IPs can't grow the
# dict without bound (memory-exhaustion DoS). When exceeded we evict the
# entries that are already refilled to capacity (idle clients) first.
_RATE_STATE_MAX = int(os.environ.get("RATE_LIMIT_MAX_BUCKETS", "10000"))


def _evict_rate_state(now: float) -> None:
    """Drop fully-refilled (idle) buckets when the table grows too large.

    Each entry's idle check uses its OWN bucket's capacity/refill (buckets
    have different capacities — process=20, publish/compose=30). Judging a
    process entry against the current request's capacity would either never
    see it as refilled or evict it while still draining.
    """
    if len(_rate_state) < _RATE_STATE_MAX:
        return
    stale = [
        k for k, (tokens, last) in _rate_state.items()
        if min(capacity_for(k), tokens + max(0.0, now - last) * refill_for(k))
        >= capacity_for(k)
    ]
    for k in stale:
        _rate_state.pop(k, None)
    # If still over budget (all buckets active), clear the oldest half.
    if len(_rate_state) >= _RATE_STATE_MAX:
        for k in sorted(_rate_state, key=lambda kk: _rate_state[kk][1])[: _RATE_STATE_MAX // 2]:
            _rate_state.pop(k, None)


# Per-bucket refill rates + capacities so eviction can recompute "is this
# idle" correctly for every entry, not just the current request's bucket.
_bucket_refill: Dict[str, float] = {}
_bucket_capacity: Dict[str, float] = {}


def refill_for(key: Tuple[str, str]) -> float:
    return _bucket_refill.get(key[0], 1.0)


def capacity_for(key: Tuple[str, str]) -> float:
    return _bucket_capacity.get(key[0], 1.0)


def _rate_limit_allow(key: Tuple[str, str], capacity: float, refill_per_sec: float, now: float) -> bool:
    """Token-bucket check. Returns True if a token was available (and consumed)."""
    _bucket_refill[key[0]] = refill_per_sec
    _bucket_capacity[key[0]] = capacity
    _evict_rate_state(now)
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
    client_host = client_ip(request) or "unknown"
    if not _rate_limit_allow((bucket, client_host), capacity, refill_per_sec, time.monotonic()):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please slow down and retry shortly.",
        )
