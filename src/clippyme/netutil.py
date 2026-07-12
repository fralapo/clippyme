"""Bounded DNS resolution shared by the SSRF guards.

``socket.getaddrinfo`` has no timeout parameter, and
``socket.setdefaulttimeout`` does NOT apply to it — it only affects socket
objects created afterwards. The old guards in ``download`` and
``social_publisher`` mutated that process-wide default around their
getaddrinfo calls, which bounded nothing and transiently changed the
default socket timeout for every other thread in the FastAPI executor.

Here the lookup runs in a daemon thread joined with a timeout: the calling
thread is freed even if the resolver hangs, the hung thread can't block
interpreter shutdown, and no global state is touched.
"""
import ipaddress
import socket
import threading


def resolve_host_addresses(host: str, timeout: float = 5.0) -> list:
    """Return the ``ipaddress`` objects ``host`` resolves to, within ``timeout``.

    Raises ``TimeoutError`` when the resolver exceeds the bound and re-raises
    ``socket.gaierror``/``OSError`` from getaddrinfo — callers treat all of
    those as "could not verify" and keep their existing best-effort policy.
    """
    result: dict = {}

    def _worker() -> None:
        try:
            result["infos"] = socket.getaddrinfo(host, None)
        except BaseException as exc:  # propagated to the caller below
            result["exc"] = exc

    worker = threading.Thread(target=_worker, daemon=True)
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
        except ValueError:
            continue
    return addresses
