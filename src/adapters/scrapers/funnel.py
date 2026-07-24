"""Shared helpers for adaptive scraper funneling (price bisect + seen-id filter)."""

from __future__ import annotations

from typing import Any, Callable, Hashable, Iterator, TypeVar

T = TypeVar("T")


def bisect_price(min_p: int, max_p: int) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """Split ``[min_p, max_p]`` into two non-empty halves, or ``None`` if atomic.

    Returns ``((min_p, mid), (mid + 1, max_p))`` when ``mid > min_p`` and
    ``mid < max_p`` (strictly room to split). When ``min_p >= max_p`` or the
    midpoint collapses onto an endpoint, returns ``None``.
    """
    if min_p >= max_p:
        return None
    mid = (min_p + max_p) // 2
    if mid <= min_p or mid >= max_p:
        return None
    return (min_p, mid), (mid + 1, max_p)


def unique_by(
    items: Iterator[T] | list[T],
    key_fn: Callable[[T], Hashable | None],
    seen: set[Hashable] | None = None,
) -> Iterator[T]:
    """Yield items whose ``key_fn`` value has not been seen yet.

    Items whose key is ``None`` are always yielded (cannot dedupe).
    Mutates ``seen`` in place when provided; otherwise starts empty.
    """
    seen_ids = seen if seen is not None else set()
    for item in items:
        key = key_fn(item)
        if key is None:
            yield item
            continue
        if key in seen_ids:
            continue
        seen_ids.add(key)
        yield item


def listing_id_from_raw(raw: dict[str, Any]) -> str | None:
    """Best-effort platform listing id from OLX / QuintoAndar raw dicts."""
    for key in ("list_id", "listId", "id"):
        value = raw.get(key)
        if value is not None and value != "":
            return str(value)
    return None
