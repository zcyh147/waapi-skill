"""Subscription placeholder for bounded WAAPI event listeners."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class SubscriptionManager:
    """Placeholder subscription registry with explicit lifecycle hooks."""

    active_topics: set[str] = field(default_factory=set)

    def subscribe(self, topic: str) -> None:
        self.active_topics.add(topic)

    def unsubscribe(self, topic: str) -> None:
        self.active_topics.discard(topic)

    def clear(self) -> None:
        self.active_topics.clear()
