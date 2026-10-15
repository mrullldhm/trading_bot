from types import SimpleNamespace

import numpy as np
import pytest

from propfirm_backtest import orb_search as O

SMALL = {**O.DIMS, "anchor": ["et0900"], "range_min": [5, 15], "trigger": ["stop"], "buffer": [0],
         "stop": ["mid", "opposite", "15", "20", "30"], "target": ["1R", "none"], "window_min": [30, 60, 120],
         "flat": ["+60", "+120"], "direction": ["both1"], "width": ["none"], "breakeven": ["off"]}


def at(grid, **lv):
    idx = [list(grid.dims[k]).index(lv.get(k, grid.dims[k][0])) for k in grid.dims]
    return int(np.ravel_multi_index(idx, grid.shape))


def test_full_grid_size():
    g = O.Grid()
    assert g.n == 1_152_000 and int(g.canonical.sum()) == 1_056_000


def test_twin_is_the_capped_window():
    g = O.Grid(SMALL)
    dup = at(g, window_min=120, flat="+60")
    assert not g.canonical[dup] and g.twin[dup] == at(g, window_min=60, flat="+60")
    assert g.canonical[at(g, window_min=120, flat="+120")]


def test_neighbours_never_self_and_respect_stop_families():
    g = O.Grid(SMALL)
    nb = g.neighbours
    assert not (nb == np.arange(g.n)[:, None]).any()
    c = at(g, window_min=60, flat="+60")  # its window-120 neighbour is its own twin: dropped
    assert c not in set(nb[c])
    assert sorted(i for i in nb[c] if i >= 0 and g.labels.loc[i, "flat"] == "+60"
                  and g.labels.loc[i, "stop"] == "mid" and g.labels.loc[i, "range_min"] == 5
                  and g.labels.loc[i, "target"] == "1R") == [at(g, window_min=30, flat="+60")]
    opp = at(g, stop="opposite")
    stops = {g.labels.loc[i, "stop"] for i in nb[opp] if i >= 0 and g.labels.loc[i, "range_min"] == 5
             and g.labels.loc[i, "window_min"] == 30 and g.labels.loc[i, "flat"] == "+60" and g.labels.loc[i, "target"] == "1R"}
    assert stops == {"mid"}  # no adjacency between range-based and fixed stops


def test_plateau_median_and_share():
    g = O.Grid(SMALL)
    score = np.zeros(g.n)
    prof = np.zeros(g.n, bool)
    c = at(g, range_min=5, stop="20", target="1R", window_min=60, flat="+120")
    score[c] = 1.0  # a lone spike: its plateau is the neighbours' median
    med, share = O.plateau(g, score, prof)
    assert score[c] == 1.0 and med[c] == 0.0 and share[c] == 0.0
    score[:] = 0.5
    prof[:] = True
    med, share = O.plateau(g, score, prof)
    assert med[c] == 0.5 and share[c] == 1.0


def test_pbo_ties_are_neutral():
    daily = np.zeros((10, 160))
    daily[:, ::2] = 1.0  # identical streams: every OOS rank is a tie
    assert O.pbo_cscv(daily, n_blocks=8) == 0.0  # tie -> rank 0.5, not "worst"


def test_pbo_detects_pure_noise_selection():
    rng = np.random.default_rng(0)
    daily = rng.normal(0, 1, (200, 800))
    assert 0.3 < O.pbo_cscv(daily, n_blocks=8) < 0.7  # noise: in-sample winner is a coin flip out of sample


def test_lower_bound():
    assert O.lower_bound(np.array([0.5]), 2000)[0] == pytest.approx(0.5 - 1.645 * np.sqrt(0.25 / 2000))


def gate_inputs(**over):
    base = dict(trades=np.array([400.0]), trades_per_year=np.array([40.0]), total=np.array([5000.0]),
                total2=np.array([1000.0]), pos_frac=np.array([0.7]), best_year_share=np.array([0.3]),
                best_day_share=np.array([0.1]), p95dd=np.array([800.0]), min_trades=300)
    base.update(over)
    return base


@pytest.mark.parametrize("field,bad", [("trades", 299.0), ("trades_per_year", 24.0), ("total", -1.0),
                                       ("total2", -1.0), ("pos_frac", 0.5), ("best_year_share", 0.6),
                                       ("best_day_share", 0.3), ("p95dd", 1001.0)])
def test_each_gate_can_fail_alone(field, bad):
    assert O.gate_mask(**gate_inputs())[0]
    assert not O.gate_mask(**gate_inputs(**{field: np.array([bad])}))[0]


def small_frame(grid, rng):
    """Synthetic metrics where most configs pass the gates, so eligibility depends on neighbours too."""
    df = grid.labels.copy()
    n = grid.n
    df["trades"] = np.where(rng.random(n) < 0.05, 0, rng.integers(400, 3000, n)).astype(float)
    df["trades_per_year"] = df["trades"] / 11.5
    df["total_usd"] = rng.normal(3000, 3000, n)
    df["expectancy_slip2"] = rng.normal(2, 2, n)
    df["positive_year_frac"] = rng.uniform(0.55, 1.0, n)
    df["best_year_share"] = rng.uniform(0.1, 0.4, n)
    df["best_day_share"] = rng.uniform(0.0, 0.2, n)
    df["p95_drawdown"] = rng.uniform(300, 1100, n)
    df["score"] = rng.random(n)
    df["canonical"] = grid.canonical
    return df


def test_rank_is_complete_and_eligible_first():
    g = O.Grid(SMALL)
    df = O.rank(g, small_frame(g, np.random.default_rng(3)))
    ranked = df.dropna(subset=["rank"]).sort_values("rank")
    live = g.canonical & (df["trades"].to_numpy() > 0)
    assert len(ranked) == live.sum() and ranked["rank"].tolist() == list(range(1, len(ranked) + 1))
    elig = ranked["eligible"].to_numpy()
    assert elig.any() and not (np.diff(elig.astype(int)) > 0).any()  # all eligible before any non-eligible
    assert not df.loc[~g.canonical, "rank"].notna().any()


def test_walk_forward_uses_only_earlier_years():
    g = O.Grid(SMALL)
    rng = np.random.default_rng(5)
    years = np.arange(2010, 2022)
    dev = SimpleNamespace(years=years, fold_ends=np.array([(y - 2010) * 252 for y in O.WF_YEARS]))
    arr = {"ypnl": rng.normal(500, 2000, (g.n, 12)), "ytr": rng.integers(20, 200, (g.n, 12)),
           "ybest": rng.random((g.n, 12)) * 300, "wf": np.stack([rng.random((g.n, 8)), rng.random((g.n, 8)) * 900], axis=2),
           "ypnl2": rng.normal(300, 2000, (g.n, 12))}
    df = g.labels
    a = O.walk_forward(g, dev, df, arr)
    future = {k: v.copy() for k, v in arr.items()}
    cut = list(years).index(2018)
    for k in ("ypnl", "ytr", "ybest", "ypnl2"):
        future[k][:, cut:] = future[k][:, cut:][rng.permutation(g.n)]  # scramble 2018+
    future["wf"][:, 4:] = rng.random((g.n, 4, 2))  # folds 2018+ only
    b = O.walk_forward(g, dev, df, future)
    early = a["year"] < 2018
    assert a.loc[early, "champion"].tolist() == b.loc[early, "champion"].tolist()
    assert (a["qualified"] > 0).any()


def test_deflated_sharpe_penalises_more_trials():
    rng = np.random.default_rng(1)
    daily = rng.normal(20, 300, 2500)
    few, many = O.deflated_sharpe(daily, 0.001, 10), O.deflated_sharpe(daily, 0.001, 1_000_000)
    assert 0 <= many < few <= 1


def test_holm_and_nomination():
    from propfirm_backtest import family_program as FP
    assert FP.holm({"a": 0.01, "b": 0.04, "c": 0.5}, alpha=0.10) == {"a": True, "b": True, "c": False}
    assert FP.holm({"a": 0.06, "b": 0.07}, alpha=0.10) == {"a": False, "b": False}  # 0.06 > 0.10/2
    assert FP.holm({"a": 0.04}, alpha=0.10, m=3) == {"a": False}  # programme of 3: 0.04 > 0.10/3
    assert FP.holm({"a": 0.03}, alpha=0.10, m=3) == {"a": True}
    import pandas as pd
    fr = {"x": {"champion_eligible": True}, "y": {"champion_eligible": False}, "z": {"champion_eligible": True}}
    res = {"x": pd.DataFrame({"score": [0.3]}), "y": pd.DataFrame({"score": [0.9]}), "z": pd.DataFrame({"score": [0.4]})}
    assert FP.nominate(fr, res) == "z"
    assert FP.nominate({"y": fr["y"]}, {"y": res["y"]}) is None


def test_micro_stats_scale_and_fees():
    t = (np.array([0, 1]), None, None, np.array([1, -1]), np.array([100.0, 200.0]), np.array([110.0, 190.0]),
         np.array([3.0, 4.0]), None)
    st = O.micro_stats(t, 2, 3)
    assert st["expectancy_usd"] == pytest.approx(3 * (10 * O.MCL_TICK_USD - O.MCL_FEE_USD))



@pytest.mark.parametrize("name", ["zab", "crabel", "acd"])
def test_family_grid_rows_map_to_their_tables_and_survive_csv(name, tmp_path):
    import pandas as pd
    from propfirm_backtest import family_program as FP
    from propfirm_backtest import family_search as FS
    from propfirm_backtest import orb_family_engine as FE
    fam = FS.FAMILIES[name]
    g = O.Grid(family=fam)
    keys = [(a, L) for a in FE.FAMILY_ANCHORS for L in fam.market.RANGE_LENGTHS]
    got = [keys[t] for t in g.cfg[:, 0]]
    want = list(zip(g.labels["anchor"], g.labels["range_min"]))
    assert got == want
    assert (g.cfg[:, 1] == [FE.anchor_row(a) for a in g.labels["anchor"]]).all()
    path = tmp_path / "r.csv.gz"
    g.labels.iloc[::-1].to_csv(path, index=False)
    back = pd.read_csv(path)
    assert (FP.locate(g, back) == np.arange(g.n)[::-1]).all()
