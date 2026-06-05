from decimal import Decimal

from trading_bot.features.dashboard.routes import _entry_state, _format_ttl
from trading_bot.core.enums import SignalStatus


def test_enter_now_long_only_when_price_at_or_below_entry() -> None:
    state = _entry_state("LONG", Decimal("100"), Decimal("99.5"), SignalStatus.WATCHING.value, 3600)
    assert state["action"] == "ENTER_NOW"
    assert state["can_enter"] is True

    state_above = _entry_state("LONG", Decimal("100"), Decimal("100.05"), SignalStatus.WATCHING.value, 3600)
    assert state_above["action"] != "ENTER_NOW"
    assert state_above["can_enter"] is False


def test_enter_now_short_only_when_price_at_or_above_entry() -> None:
    state = _entry_state("SHORT", Decimal("100"), Decimal("100.5"), SignalStatus.WATCHING.value, 3600)
    assert state["action"] == "ENTER_NOW"

    state_below = _entry_state("SHORT", Decimal("100"), Decimal("99.9"), SignalStatus.WATCHING.value, 3600)
    assert state_below["action"] != "ENTER_NOW"


def test_active_allows_manual_not_auto_enter() -> None:
    state = _entry_state("LONG", Decimal("100"), Decimal("99"), SignalStatus.ACTIVE.value, 3600)
    assert state["action"] == "ACTIVE"
    assert state["can_enter"] is False
    assert state["can_enter_manual"] is True


def test_expired_signal_cannot_enter() -> None:
    state = _entry_state("LONG", Decimal("100"), Decimal("99"), SignalStatus.EXPIRED.value, 0)
    assert state["action"] == "EXPIRED"
    assert state["can_enter"] is False


def test_format_ttl() -> None:
    assert _format_ttl(3661) == "1h 1m"
    assert _format_ttl(0) == "Caducada"
    assert _format_ttl(45) == "45s"
