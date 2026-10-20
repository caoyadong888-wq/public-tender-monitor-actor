"""Push one dataset item, then charge one tender-item event.

Charging is optional. A run with no pricing configured must keep going.
A charge result with event_charge_limit_reached stops further pushes.
"""

from __future__ import annotations


def charge_limit_reached(result) -> bool:
    if result is None:
        return False
    if isinstance(result, dict):
        return bool(result.get("event_charge_limit_reached") or result.get("eventChargeLimitReached"))
    return bool(getattr(result, "event_charge_limit_reached", False))


async def push_notice(actor, item: dict) -> bool:
    """Push one notice and charge. Return False when the run should stop."""
    await actor.push_data(item)
    try:
        result = await actor.charge(event_name="tender-item", count=1)
    except Exception as exc:
        log = getattr(actor, "log", None)
        if log is not None:
            log.warning("tender-item charge failed (continuing without charge): %s", exc)
        return True
    if charge_limit_reached(result):
        log = getattr(actor, "log", None)
        if log is not None:
            log.info("tender-item charge limit reached; stopping")
        return False
    return True
