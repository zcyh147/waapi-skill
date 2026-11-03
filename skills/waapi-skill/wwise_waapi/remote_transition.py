"""Observable remote target identity, independent of native call success.

The five native Authoring catalogs expose console.host and console.appName in
getConnectionStatus. They do not expose a connected port there. Console name,
host names and IPs are distinct facts; no DNS or name equivalence is inferred.
"""
from __future__ import annotations

import ipaddress
from typing import Any, Mapping

from .builders.schema import validate_semantic_result

VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
STATUS_URI = "ak.wwise.core.remote.getConnectionStatus"
DISCOVERY_URI = "ak.wwise.core.remote.getAvailableConsoles"
MAX_DISCOVERED_CONSOLES = 256
CONSOLE_DESCRIPTOR_FIELDS = ("host", "appName", "name", "platform", "customPlatform")


def remote_connection_snapshot(version: str, read) -> dict[str, Any]:
    """Retain native omission and every status fact for Preview drift checks."""
    result = read(STATUS_URI, {}, {})
    if not isinstance(result, Mapping):
        raise ValueError("Remote connection status must be an object")
    validate_semantic_result(STATUS_URI, result, version=version)
    return dict(result)


def remote_target(version: str, args: Mapping[str, Any]) -> dict[str, Any]:
    """Retain only the exact Gateway-constructed requested selector."""
    if version not in VERSIONS or not isinstance(args.get("host"), str) or not args["host"]:
        raise ValueError("Remote verification requires its versioned requested host")
    target = {"version": version, **{key: args[key] for key in ("host", "appName", "commandPort", "notificationPort") if key in args}}
    # Only 2022+ documents an IPv4:PORT host selector. This is lexical
    # decomposition of that documented form, never hostname/IP resolution.
    if version != "2021.1" and args["host"].count(":") == 1:
        host, port = args["host"].split(":")
        if _ipv4(host) and port.isascii() and port.isdecimal() and 0 <= int(port) <= 65535:
            if "commandPort" in target and target["commandPort"] != int(port):
                raise ValueError("Remote host port and command_port select different targets")
            target["host_observer"] = host
            target["commandPort"] = int(port)
    return target


def needs_remote_discovery(target: Mapping[str, Any]) -> bool:
    return "commandPort" in target or target.get("version") == "2021.1" and "notificationPort" in target


def _ipv4(value: str) -> str | None:
    try:
        return str(ipaddress.IPv4Address(value))
    except ipaddress.AddressValueError:
        return None


def observe_remote_target(target: Mapping[str, Any], status: Mapping[str, Any], *,
                          discovery: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Compare independently returned facts; unresolved facts never mean PASS."""
    checks: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    corroboration: list[dict[str, Any]] = []
    console = status.get("console")
    if not isinstance(console, Mapping):
        return {"checks": checks, "unresolved": [{"field": "console", "reason": "connected_console_not_observed"}]}
    expected_host, actual_host = target.get("host_observer", target["host"]), console.get("host")
    if expected_host == actual_host:
        checks.append({"field": "host", "passed": True, "expected": expected_host, "actual": actual_host})
    elif isinstance(actual_host, str) and _ipv4(expected_host) and _ipv4(actual_host):
        checks.append({"field": "host", "passed": False, "expected": expected_host, "actual": actual_host})
    else:
        unresolved.append({"field": "host", "reason": "no_observed_host_alias_binding",
            "expected": expected_host, "actual": actual_host})
    if "appName" in target:
        actual_app = console.get("appName")
        checks.append({"field": "application_name", "passed": actual_app == target["appName"],
            "expected": target["appName"], "actual": actual_app})
    if needs_remote_discovery(target):
        # Discovery descriptors are not a documented process-unique key, and
        # discovery does not certify that every connected instance is listed.
        # Even one matching row cannot prove the actually connected port.
        unresolved.append({"field": "ports", "reason": "connected_status_has_no_port_or_process_identity",
            "requested": {key: target[key] for key in ("commandPort", "notificationPort")
                if key in target and (key != "notificationPort" or target.get("version") == "2021.1")}})
        rows = discovery.get("consoles") if isinstance(discovery, Mapping) else None
        if not isinstance(rows, list) or len(rows) > MAX_DISCOVERED_CONSOLES:
            unresolved.append({"field": "ports", "reason": "fresh_bounded_discovery_unavailable"})
        else:
            matches = [row for row in rows if isinstance(row, Mapping)
                and all(isinstance(console.get(key), str) and console.get(key) == row.get(key)
                        for key in CONSOLE_DESCRIPTOR_FIELDS)]
            if len(matches) != 1:
                unresolved.append({"field": "ports", "reason": "console_descriptors_do_not_match_exactly_one_discovery_row",
                    "matching_rows": len(matches)})
            else:
                for field in ("commandPort", "notificationPort"):
                    # Native 2022+ documents notificationPort as unused. It
                    # cannot certify a target and has no promised posteffect.
                    if field not in target or field == "notificationPort" and target.get("version") != "2021.1":
                        continue
                    actual = matches[0].get(field)
                    corroboration.append({"field": field, "matches_requested": type(actual) is int and actual == target[field],
                        "expected": target[field], "discovered": actual, "observer": "matching_fresh_discovery_row",
                        "connected_instance_identity_proven": False})
    return {"checks": checks, "unresolved": unresolved,
        "corroboration": corroboration,
        "ignored_native_fields": (["notificationPort"] if "notificationPort" in target and target.get("version") != "2021.1" else [])}
