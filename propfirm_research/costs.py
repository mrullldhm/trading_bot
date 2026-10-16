"""CL costs (D004: CL only). Constants come from the frozen propsim module so they can never drift."""

from propfirm_backtest.propsim import FEE_USD, TICK_USD

BASE_SLIP = 1.0  # ticks per side
STRESS_SLIP = 2.0  # +1 tick per side (gate G4 / check V6)


def round_trip_usd(contracts: float = 1, slip_ticks: float = BASE_SLIP) -> float:
    """Fee + slippage on entry and exit, in $."""
    return contracts * (FEE_USD + 2 * slip_ticks * TICK_USD)


def round_trip_ticks(slip_ticks: float = BASE_SLIP) -> float:
    return round_trip_usd(1, slip_ticks) / TICK_USD


BASE_USD = round_trip_usd(1, BASE_SLIP)  # 24.02
STRESS_USD = round_trip_usd(1, STRESS_SLIP)  # 44.02
