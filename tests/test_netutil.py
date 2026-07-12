"""Tests for netutil.resolve_host_addresses — the bounded DNS helper.

Replaces the old socket.setdefaulttimeout mutation in the SSRF guards
(which never applied to getaddrinfo and leaked a changed default to every
other thread). getaddrinfo is monkeypatched — no real DNS.
"""
import ipaddress
import socket
import time

import pytest

from clippyme import netutil


def test_returns_parsed_addresses(monkeypatch):
    infos = [
        (socket.AF_INET, None, None, "", ("93.184.216.34", 0)),
        (socket.AF_INET6, None, None, "", ("2606:2800:220:1:248:1893:25c8:1946", 0, 0, 0)),
        (socket.AF_INET, None, None, "", ("not-an-ip", 0)),  # skipped, not fatal
    ]
    monkeypatch.setattr(netutil.socket, "getaddrinfo", lambda h, p: infos)
    addrs = netutil.resolve_host_addresses("example.com")
    assert ipaddress.ip_address("93.184.216.34") in addrs
    assert len(addrs) == 2


def test_resolver_errors_propagate(monkeypatch):
    def boom(host, port):
        raise socket.gaierror("NXDOMAIN")

    monkeypatch.setattr(netutil.socket, "getaddrinfo", boom)
    with pytest.raises(socket.gaierror):
        netutil.resolve_host_addresses("nope.invalid")


def test_hung_resolver_raises_timeout_quickly(monkeypatch):
    def hang(host, port):
        time.sleep(5)
        return []

    monkeypatch.setattr(netutil.socket, "getaddrinfo", hang)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        netutil.resolve_host_addresses("slow.example", timeout=0.1)
    # The caller is freed at the bound, not when the resolver finishes.
    assert time.monotonic() - started < 2.0
