"""Reconciliación de arranque: resuelve el estado tras un crash o reinicio.

1. Intents INTENT/SENT huérfanos → consultar exchange y fijar estado real.
2. Pasada completa de ReconciliationService.
3. Toda posición confirmada recupera su SL si falta.
4. Alerta PROCESS_RESTARTED con el resumen.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from trading_bot.config.settings import Settings, get_settings
from trading_bot.core.enums import AlertType, AuditAction
from trading_bot.db.models.broker_order import BrokerOrder
from trading_bot.features.alerts.telegram import TelegramNotifier
from trading_bot.features.broker.binance_broker import BinanceBroker
from trading_bot.features.reconciliation.service import ReconcileReport, ReconciliationService
from trading_bot.infrastructure.audit.logger import AuditLogger

logger = structlog.get_logger()


@dataclass
class StartupReport:
    orphan_intents_resolved: int = 0
    reconcile: ReconcileReport | None = None
    kill_switch_engaged: bool = False


async def reconcile_on_startup(
    session_factory: async_sessionmaker, settings: Settings | None = None
) -> StartupReport:
    settings = settings or get_settings()
    report = StartupReport()
    broker = BinanceBroker(settings)
    if not settings.reconcile_on_startup or not broker.is_configured():
        return report

    notifier = TelegramNotifier(settings)
    async with session_factory() as session:
        # 1) Resolver intents huérfanos
        result = await session.execute(
            select(BrokerOrder).where(
                BrokerOrder.status.in_(
                    [BrokerOrder.STATUS_INTENT, BrokerOrder.STATUS_SENT, BrokerOrder.STATUS_UNKNOWN]
                )
            )
        )
        orphans = result.scalars().all()
        for intent in orphans:
            try:
                existing = await asyncio.to_thread(
                    broker.fetch_order_by_client_id, intent.symbol, intent.client_order_id
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "startup_intent_check_failed", coid=intent.client_order_id, error=str(exc)
                )
                continue
            if existing is None:
                intent.status = BrokerOrder.STATUS_REJECTED
                intent.error = "Resuelto al arrancar: la orden nunca llegó al exchange"
            else:
                status = str(existing.get("status") or "").lower()
                if status in ("closed", "filled"):
                    intent.status = BrokerOrder.STATUS_FILLED
                elif status in ("canceled", "cancelled", "expired"):
                    intent.status = BrokerOrder.STATUS_CANCELED
                else:
                    intent.status = BrokerOrder.STATUS_ACKED
                intent.exchange_order_id = str(existing.get("id", ""))
            report.orphan_intents_resolved += 1
        await session.commit()
        if report.orphan_intents_resolved:
            AuditLogger.log(
                "startup", AuditAction.RECONCILE_FIX,
                f"{report.orphan_intents_resolved} intents huérfanos resueltos",
            )

        # 2+3) Pasada completa (cierra trades, repone SLs, cancela huérfanas)
        recon = ReconciliationService(session, settings, broker=broker, notifier=notifier)
        report.reconcile = await recon.run()
        report.kill_switch_engaged = report.reconcile.kill_switch_triggered

        AuditLogger.log("startup", AuditAction.PROCESS_STARTED, "Reconciliación de arranque completa")

        # 4) Alerta de reinicio con resumen
        if settings.startup_alert_enabled and notifier.is_configured:
            recon_summary = report.reconcile
            extra = (
                f"Intents resueltos: {report.orphan_intents_resolved} | "
                f"Trades cerrados: {len(recon_summary.closed_trades)} | "
                f"SL repuestos: {len(recon_summary.sl_restored)} | "
                f"Equity: {recon_summary.equity or 'n/a'} USDT"
            )
            try:
                await notifier.send_alert(
                    AlertType.PROCESS_RESTARTED, symbol="SYSTEM", direction="-", extra=extra
                )
            except Exception:  # noqa: BLE001
                pass

    return report
