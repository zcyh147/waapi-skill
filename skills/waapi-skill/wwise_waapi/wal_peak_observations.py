"""Bounded retained projections for WAL and Peak reads."""
from __future__ import annotations

from dataclasses import dataclass
import hmac
import re
import time
from typing import Any, Mapping

from .canonical import canonical_sha256
from .media_pool_continuation import MediaPoolContinuationError, MediaPoolQueryStore


@dataclass(frozen=True, slots=True)
class NativePageLocator:
    kind: str
    observed_at: int
    offset: int
    handle: str
    token: str


class WalPeakObservationStore(MediaPoolQueryStore):
    DIRECTORY = "wal-peak-observations-v1"
    CONTRACT = "waapi-skill.wal-peak-observation/v1"
    PREFIX = "wp1-"
    _HANDLE = re.compile(r"^wp1-[0-9a-f]{32}$")
    MAX_RECORD_BYTES = 4 * 1024 * 1024

    @staticmethod
    def validate_plan(plan: Mapping[str, Any]) -> None:
        if (set(plan) != {"request_sha256", "native_result_sha256", "observation"}
                or not isinstance(plan["observation"], dict)
                or any(not isinstance(plan[key], str) or not re.fullmatch(r"[0-9a-f]{64}", plan[key])
                       for key in ("request_sha256", "native_result_sha256"))):
            raise MediaPoolContinuationError("Stored WAL or Peak observation has an invalid shape")

    def resolve_page(self, page: NativePageLocator, *, request_sha256: str) -> tuple[dict[str, Any], str]:
        record = self.resolve(page.handle)
        seal = canonical_sha256(record)
        if (record["expires_at"] != page.observed_at + 900
                or record["plan"]["request_sha256"] != request_sha256
                or not hmac.compare_digest(page.token, native_page_token(
                    page.kind, page.observed_at, page.offset, page.handle, seal))):
            raise MediaPoolContinuationError("Page does not match the retained observation and original request")
        return record, seal


def native_page_token(kind: str, observed_at: int, offset: int, handle: str, seal: str) -> str:
    unsigned = f"{kind}.{observed_at}.{offset}.{handle}"
    return unsigned + "." + canonical_sha256([unsigned, seal])


def parse_native_page(token: str, *, kind: str, maximum_offset: int) -> NativePageLocator:
    try:
        if not isinstance(token, str) or len(token) > 160:
            raise ValueError("token bound")
        prefix, stamp, position, handle, digest = token.split(".")
        observed_at, offset = int(stamp), int(position)
        valid = (prefix == kind and str(observed_at) == stamp and str(offset) == position
                 and 0 < offset < maximum_offset and observed_at <= time.time() <= observed_at + 900
                 and WalPeakObservationStore._HANDLE.fullmatch(handle) is not None
                 and re.fullmatch(r"[0-9a-f]{64}", digest) is not None)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise MediaPoolContinuationError("Page locator is malformed or expired; restart the bounded read")
    return NativePageLocator(kind, observed_at, offset, handle, token)
