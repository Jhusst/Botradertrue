import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from trading_bot.config.settings import Settings, get_settings
from trading_bot.core.asset_catalog import is_futures_symbol
from trading_bot.infrastructure.market_data.ccxt_client import DataCollector
from trading_bot.infrastructure.resilience import with_retry


def _is_duplicate_order_error(exc: Exception) -> bool:
    """Binance -4015 / 'Duplicate' al reusar clientOrderId: la orden YA existe."""
    text = str(exc).lower()
    return "-4015" in text or "duplicate" in text


@dataclass
class BrokerOrderResult:
    ok: bool
    order_id: str | None = None
    symbol: str | None = None
    side: str | None = None
    amount: str | None = None
    message: str = ""
    raw: dict[str, Any] | None = None


@dataclass
class BrokerAccountSnapshot:
    connected: bool
    exchange: str
    testnet: bool
    usdt_balance: str | None
    available_balance: str | None
    positions: list[dict[str, Any]]
    message: str = ""


class BinanceBroker:
    """Conector Binance Futures vía CCXT — lectura de cuenta y órdenes opcionales."""

    ACCOUNT_CACHE_TTL_SECONDS = 30
    _account_cache: tuple["BrokerAccountSnapshot", float] | None = None

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._collector = DataCollector("binance")

    @property
    def exchange(self):
        return self._collector.exchange

    def is_configured(self) -> bool:
        return bool(self.settings.binance_api_key and self.settings.binance_api_secret)

    def can_execute(self) -> tuple[bool, str]:
        if not self.settings.broker_enabled:
            return False, "BROKER_ENABLED=false — activa el broker en .env"
        if not self.is_configured():
            return False, "Faltan BINANCE_API_KEY y BINANCE_API_SECRET en .env"
        if not self.settings.auto_execute_on_enter and not self.settings.autonomous_trading_enabled:
            return False, "AUTO_EXECUTE_ON_ENTER=false y modo autónomo desactivado"
        if not self.settings.live_mode_enabled:
            return False, "LIVE_MODE_ENABLED=false — candado de seguridad activo"
        return True, "Listo para ejecutar en Binance"

    def resolve_futures_symbol(self, symbol: str) -> str:
        return self._collector._resolve_symbol(symbol)

    def fetch_account(self, *, use_cache: bool = True) -> BrokerAccountSnapshot:
        if use_cache and self._account_cache is not None:
            cached, cached_at = self._account_cache
            if time.time() - cached_at < self.ACCOUNT_CACHE_TTL_SECONDS:
                return cached

        if not self.is_configured():
            return BrokerAccountSnapshot(
                connected=False,
                exchange="binance",
                testnet=self.settings.binance_testnet,
                usdt_balance=None,
                available_balance=None,
                positions=[],
                message="API keys no configuradas",
            )
        try:
            balance = self.exchange.fetch_balance()
            usdt = balance.get("USDT") or balance.get("total", {}).get("USDT")
            free = balance.get("free", {}).get("USDT")
            if isinstance(usdt, dict):
                total = usdt.get("total")
                free = usdt.get("free", free)
            else:
                total = usdt

            positions_raw = self.exchange.fetch_positions()
            positions = []
            for pos in positions_raw:
                contracts = float(pos.get("contracts") or 0)
                if contracts == 0:
                    continue
                positions.append(
                    {
                        "symbol": pos.get("symbol"),
                        "side": pos.get("side"),
                        "contracts": str(contracts),
                        "entry_price": str(pos.get("entryPrice") or ""),
                        "unrealized_pnl": str(pos.get("unrealizedPnl") or ""),
                        "leverage": pos.get("leverage"),
                    }
                )

            snapshot = BrokerAccountSnapshot(
                connected=True,
                exchange="binance",
                testnet=self.settings.binance_testnet,
                usdt_balance=str(total) if total is not None else None,
                available_balance=str(free) if free is not None else None,
                positions=positions,
                message="Conectado a Binance Futures",
            )
            self._account_cache = (snapshot, time.time())
            return snapshot
        except Exception as exc:
            snapshot = BrokerAccountSnapshot(
                connected=False,
                exchange="binance",
                testnet=self.settings.binance_testnet,
                usdt_balance=None,
                available_balance=None,
                positions=[],
                message=f"Error conectando: {exc}",
            )
            return snapshot

    # ------------------------------------------------------------------
    # Primitivas idempotentes (todas aceptan client_order_id determinístico)
    # ------------------------------------------------------------------

    def market_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        *,
        client_order_id: str,
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        """Orden a mercado idempotente: si Binance reporta id duplicado,
        consulta y devuelve la orden existente en lugar de fallar."""
        resolved = self.resolve_futures_symbol(symbol)
        params: dict[str, Any] = {"clientOrderId": client_order_id}
        if reduce_only:
            params["reduceOnly"] = True
        try:
            return self.exchange.create_order(resolved, "market", side, amount, None, params)
        except Exception as exc:
            if _is_duplicate_order_error(exc):
                existing = self.fetch_order_by_client_id(symbol, client_order_id)
                if existing is not None:
                    return existing
            raise

    def place_stop_loss(
        self, symbol: str, side: str, stop_price: Decimal, *, client_order_id: str
    ) -> dict[str, Any]:
        """SL con closePosition=True: cierra el 100% sin importar la cantidad."""
        resolved = self.resolve_futures_symbol(symbol)
        px = self.exchange.price_to_precision(resolved, float(stop_price))
        params = {"stopPrice": px, "closePosition": True, "clientOrderId": client_order_id}
        try:
            return self.exchange.create_order(resolved, "stop_market", side, None, None, params)
        except Exception as exc:
            if _is_duplicate_order_error(exc):
                existing = self.fetch_order_by_client_id(symbol, client_order_id)
                if existing is not None:
                    return existing
            raise

    def place_take_profit(
        self, symbol: str, side: str, tp_price: Decimal, *, client_order_id: str
    ) -> dict[str, Any]:
        resolved = self.resolve_futures_symbol(symbol)
        px = self.exchange.price_to_precision(resolved, float(tp_price))
        params = {"stopPrice": px, "closePosition": True, "clientOrderId": client_order_id}
        try:
            return self.exchange.create_order(
                resolved, "take_profit_market", side, None, None, params
            )
        except Exception as exc:
            if _is_duplicate_order_error(exc):
                existing = self.fetch_order_by_client_id(symbol, client_order_id)
                if existing is not None:
                    return existing
            raise

    def fetch_order_by_client_id(self, symbol: str, client_order_id: str) -> dict[str, Any] | None:
        import ccxt

        resolved = self.resolve_futures_symbol(symbol)
        try:
            return self.exchange.fetch_order(None, resolved, {"origClientOrderId": client_order_id})
        except ccxt.OrderNotFound:
            return None

    @with_retry()
    def fetch_open_orders_safe(self, symbol: str | None = None) -> list[dict[str, Any]]:
        resolved = self.resolve_futures_symbol(symbol) if symbol else None
        return self.exchange.fetch_open_orders(resolved)

    @with_retry()
    def fetch_positions_safe(self) -> list[dict[str, Any]]:
        """Posiciones con contratos != 0."""
        positions = self.exchange.fetch_positions()
        return [p for p in positions if float(p.get("contracts") or 0) != 0]

    @with_retry()
    def fetch_my_trades_since(self, symbol: str, since_ms: int) -> list[dict[str, Any]]:
        resolved = self.resolve_futures_symbol(symbol)
        return self.exchange.fetch_my_trades(resolved, since=since_ms)

    @with_retry()
    def fetch_equity(self) -> Decimal:
        """Equity total (balance + PnL no realizado) en USDT."""
        balance = self.exchange.fetch_balance()
        info = balance.get("info", {})
        total_margin = info.get("totalMarginBalance")
        if total_margin is not None:
            return Decimal(str(total_margin))
        usdt = balance.get("USDT") or {}
        total = usdt.get("total") if isinstance(usdt, dict) else usdt
        return Decimal(str(total or "0"))

    def cancel_all_orders(self, symbol: str) -> None:
        resolved = self.resolve_futures_symbol(symbol)
        self.exchange.cancel_all_orders(resolved)

    def close_position_market(self, symbol: str, *, client_order_id: str) -> dict[str, Any] | None:
        """Cierra la posición real del símbolo a mercado (reduceOnly).

        Lee la cantidad real de fetch_positions: cierra lo que de verdad
        hay abierto, no lo que la DB cree que hay.
        """
        resolved = self.resolve_futures_symbol(symbol)
        positions = self.fetch_positions_safe()
        for pos in positions:
            if pos.get("symbol") != resolved:
                continue
            contracts = abs(float(pos.get("contracts") or 0))
            if contracts == 0:
                return None
            side = "sell" if pos.get("side") == "long" else "buy"
            return self.market_order(
                symbol, side, contracts, client_order_id=client_order_id, reduce_only=True
            )
        return None

    def set_leverage_safe(self, leverage: int, symbol: str) -> None:
        resolved = self.resolve_futures_symbol(symbol)
        self.exchange.set_leverage(leverage, resolved)

    def _amount_from_position_usdt(
        self, symbol: str, position_size_usdt: Decimal, entry_price: Decimal
    ) -> str:
        if entry_price <= 0:
            raise ValueError("Precio de entrada inválido")
        raw_amount = float(position_size_usdt / entry_price)
        resolved = self.resolve_futures_symbol(symbol)
        return self.exchange.amount_to_precision(resolved, raw_amount)

    def open_position(
        self,
        *,
        symbol: str,
        direction: str,
        entry_price: Decimal,
        position_size_usdt: Decimal,
        leverage: int,
        stop_loss: Decimal | None = None,
        take_profit_1: Decimal | None = None,
    ) -> BrokerOrderResult:
        can, reason = self.can_execute()
        if not can:
            return BrokerOrderResult(ok=False, message=reason)

        resolved = self.resolve_futures_symbol(symbol)
        if not is_futures_symbol(resolved) and ":" not in resolved:
            return BrokerOrderResult(ok=False, message=f"Símbolo {symbol} no es futuro USDT-M")

        side = "buy" if direction == "LONG" else "sell"
        try:
            self.exchange.set_leverage(leverage, resolved)
            amount = self._amount_from_position_usdt(symbol, position_size_usdt, entry_price)
            if float(amount) <= 0:
                return BrokerOrderResult(
                    ok=False,
                    message=f"Tamaño de orden demasiado pequeño ({amount}). Sube balance o riesgo.",
                )

            order = self.exchange.create_order(resolved, "market", side, float(amount))
            order_id = str(order.get("id", ""))

            if stop_loss:
                sl_side = "sell" if direction == "LONG" else "buy"
                sl_price = self.exchange.price_to_precision(resolved, float(stop_loss))
                self.exchange.create_order(
                    resolved,
                    "stop_market",
                    sl_side,
                    float(amount),
                    None,
                    {"stopPrice": sl_price, "reduceOnly": True},
                )

            if take_profit_1:
                tp_side = "sell" if direction == "LONG" else "buy"
                tp_price = self.exchange.price_to_precision(resolved, float(take_profit_1))
                self.exchange.create_order(
                    resolved,
                    "take_profit_market",
                    tp_side,
                    float(amount),
                    None,
                    {"stopPrice": tp_price, "reduceOnly": True},
                )

            return BrokerOrderResult(
                ok=True,
                order_id=order_id,
                symbol=resolved,
                side=side,
                amount=amount,
                message=f"Orden {side} ejecutada en Binance ({resolved})",
                raw=order,
            )
        except Exception as exc:
            return BrokerOrderResult(ok=False, message=f"Error ejecutando en Binance: {exc}")
