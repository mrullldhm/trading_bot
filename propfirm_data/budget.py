"""Cost guard: refuse any download that could exceed the budget."""

import math

from .config import QUOTE_SAFETY_MARGIN


class BudgetError(Exception):
    pass


def check_budget(
    new_quotes: dict[str, float],
    already_reserved: float,
    max_budget: float,
    margin: float = QUOTE_SAFETY_MARGIN,
) -> float:
    """Return the worst-case total spend, or raise BudgetError if it is over budget.

    already_reserved = worst-case cost (quote x margin) of every job ever submitted,
    even failed ones, so retries can never sneak past the cap.
    """
    numbers = [max_budget, margin, already_reserved, *new_quotes.values()]
    if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in numbers):
        raise BudgetError(f"invalid number in budget check: {numbers}")  # NaN would pass every comparison
    if max_budget <= 0:
        raise BudgetError("max budget must be positive")
    if margin < 1 or already_reserved < 0 or any(q < 0 for q in new_quotes.values()):
        raise BudgetError(f"invalid margin/spend/quotes: margin={margin}, reserved={already_reserved}, {new_quotes}")

    worst_case = already_reserved + sum(new_quotes.values()) * margin
    if worst_case > max_budget:
        raise BudgetError(
            f"worst-case spend ${worst_case:.2f} (already reserved ${already_reserved:.2f} "
            f"+ new quotes x{margin}) exceeds budget ${max_budget:.2f}"
        )
    return worst_case
