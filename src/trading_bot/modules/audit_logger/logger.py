import structlog

from trading_bot.core.enums import AuditAction

logger = structlog.get_logger()


class AuditLogger:
    """Registro estructurado de decisiones del sistema."""

    @staticmethod
    def log(
        module: str,
        action: AuditAction,
        message: str,
        entity_type: str | None = None,
        entity_id: int | None = None,
        **context,
    ) -> None:
        logger.info(
            message,
            module=module,
            action=action.value,
            entity_type=entity_type,
            entity_id=entity_id,
            **context,
        )
