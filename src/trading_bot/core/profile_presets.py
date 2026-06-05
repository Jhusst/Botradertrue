from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ProfilePreset:
    profile_type: str
    display_name: str
    description: str
    default_balance: Decimal
    risk_setup_a: Decimal
    risk_setup_b: Decimal
    max_leverage: int
    min_setup_grade: str  # A = solo setups A; B = permite B también


CONSERVATIVE = ProfilePreset(
    profile_type="conservative",
    display_name="Conservador",
    description="Riesgo mínimo, solo setups A. Lev máx 10x en cripto.",
    default_balance=Decimal("2"),
    risk_setup_a=Decimal("0.25"),
    risk_setup_b=Decimal("0.15"),
    max_leverage=10,
    min_setup_grade="A",
)

AGGRESSIVE = ProfilePreset(
    profile_type="aggressive",
    display_name="Agresivo",
    description="Riesgo moderado. Permite setups A y B. Lev máx 20x.",
    default_balance=Decimal("2"),
    risk_setup_a=Decimal("0.75"),
    risk_setup_b=Decimal("0.5"),
    max_leverage=20,
    min_setup_grade="B",
)

PRESETS = {CONSERVATIVE.profile_type: CONSERVATIVE, AGGRESSIVE.profile_type: AGGRESSIVE}
