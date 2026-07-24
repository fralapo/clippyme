"""Bounded DNS resolution shared by the SSRF guards.

``socket.getaddrinfo`` has no timeout parameter. Running it in a daemon thread
lets callers enforce a deadline without mutating process-wide socket defaults.
A small semaphore also caps the number of resolver threads that may remain
blocked inside the system resolver, preventing attacker-controlled hostnames
from creating an unbounded thread leak.
"""
import ipaddress
import socket
import threading

_DNS_MAX_INFLIGHT = 8
_dns_slots = threading.BoundedSemaphore(_DNS_MAX_INFLIGHT)


def resolve_host_addresses(host: str, timeout: float = 5.0) -> list:
    """Return ``ipaddress`` objects for ``host`` within ``timeout`` seconds.

    Raises ``TimeoutError`` when the lookup exceeds the deadline or when the
    bounded resolver pool is already saturated. Resolver exceptions are
    propagated to the caller.
    """
    if not isinstance(host, str) or not host.strip():
        raise ValueError("host must be a non-empty string")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if not _dns_slots.acquire(blocking=False):
        raise TimeoutError("DNS resolver capacity exhausted")

    result: dict = {}

    def _worker() -> None:
        try:
            result["infos"] = socket.getaddrinfo(host, None)
        except BaseException as exc:  # propagated to the caller below
            result["exc"] = exc
        finally:
            _dns_slots.release()

    worker = threading.Thread(target=_worker, daemon=True, name="clippyme-dns")
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise TimeoutError(f"DNS resolution for {host!r} exceeded {timeout}s")
    if "exc" in result:
        raise result["exc"]

    addresses = []
    for info in result.get("infos", []):
        try:
            addresses.append(ipaddress.ip_address(info[4][0]))
        except (ValueError, IndexError, TypeError):
            continue
    return addresses
