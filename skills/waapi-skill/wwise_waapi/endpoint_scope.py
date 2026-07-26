"""Pure WAAPI endpoint-scope predicates shared by path boundaries."""

from __future__ import annotations

import ipaddress


def is_loopback_waapi_host(value: str) -> bool:
    """Accept only ``localhost`` or a literal loopback IPv4/IPv6 address."""

    normalized = value.strip().casefold()
    if normalized == "localhost":
        return True
    if (
        len(normalized) >= 2
        and normalized[0] == "["
        and normalized[-1] == "]"
    ):
        normalized = normalized[1:-1]
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


__all__ = ["is_loopback_waapi_host"]
