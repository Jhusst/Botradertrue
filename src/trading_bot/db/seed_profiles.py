from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.core.profile_presets import PRESETS
from trading_bot.db.models.account import Account


async def ensure_profiles(session: AsyncSession) -> list[Account]:
    """Crea perfiles conservador y agresivo si no existen."""
    result = await session.execute(select(Account))
    existing = {a.profile_type: a for a in result.scalars().all()}
    profiles: list[Account] = []

    for preset in PRESETS.values():
        if preset.profile_type in existing:
            acc = existing[preset.profile_type]
            acc.max_leverage = preset.max_leverage
            acc.risk_setup_a = preset.risk_setup_a
            acc.risk_setup_b = preset.risk_setup_b
            profiles.append(acc)
            continue
        account = Account(
            name=preset.display_name,
            profile_type=preset.profile_type,
            balance_usdt=preset.default_balance,
            initial_balance_usdt=preset.default_balance,
            risk_setup_a=preset.risk_setup_a,
            risk_setup_b=preset.risk_setup_b,
            max_leverage=preset.max_leverage,
            min_setup_grade=preset.min_setup_grade,
        )
        session.add(account)
        profiles.append(account)

    await session.flush()
    return profiles
