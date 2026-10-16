#!/usr/bin/env python3
"""Small mechanical checks for the independent S001 replication."""

import numpy as np

import replicate as r


def main():
    # DLL touches count, and liquidation loses one additional tick per contract.
    p, low, hit = r.apply_dll(np.array([50.0, -900.0]), np.array([-1_000.0, -999.0]), 1_000.0)
    np.testing.assert_allclose(p, [-1_010.0, -900.0])
    np.testing.assert_allclose(low, [-1_010.0, -999.0])
    assert hit.tolist() == [True, False]

    starts = np.zeros((10, r.MAX_DAYS // r.BLOCK + 1), dtype=np.int32)
    # Constant gains pass in 30 days; consistency is satisfied.
    outcome, days, _ = r.simulate(np.array([100.0]), np.array([0.0]), starts,
                                   3_000.0, 2_000.0, .55)
    assert (outcome == 1).all() and (days == 30).all()
    # A touch of the starting MLL fails on day 20 (comparison is <=).
    outcome, days, _ = r.simulate(np.array([-100.0]), np.array([-100.0]), starts,
                                   3_000.0, 2_000.0, .55)
    assert (outcome == -1).all() and (days == 20).all()

    # Conditional Brownian minimum is never above either endpoint.
    x = np.array([-100.0, 0.0, 100.0])
    u = np.array([.2, .5, .8])
    bridge_min = (x - np.sqrt(x * x - 2 * 150.0**2 * np.log(u))) / 2
    assert (bridge_min <= np.minimum(x, 0.0)).all()
    print("verification checks passed")


if __name__ == "__main__":
    main()
