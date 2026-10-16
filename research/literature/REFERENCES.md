---
id: LITERATURE
title: References and what each one feeds
status: living
updated: 2026-10-16
---

# Literature

Key numbers are as reported by the sources (or by summaries of them, marked). "Feeds" = which
hypothesis, study or rule uses it. Verify against the original paper before relying on a number.

## Intraday return predictability

| Paper | Key finding | Feeds |
|---|---|---|
| Gao, Han, Li, Zhou (2018), *Market intraday momentum*, Journal of Financial Economics 129(2) | SPY: the first half-hour return (from the prior close) predicts the last half-hour; stronger on volatile, high-volume, news days. Reported no intraday momentum in commodity futures in their setup (unclear open/close) | H001, H007, K7.4 |
| Baltussen, Da, Lammers, Martens (2021), *Hedging demand and market intraday momentum*, JFE 142, 377-403 ([pdf](https://www3.nd.edu/~zda/intramom.pdf)) | 60+ futures (equity, bond, commodity, FX), 1974-2020: the rest-of-day return predicts the last 30 minutes in every asset class; driven by short-gamma hedging; reverses over following days. A summary reports strategy Sharpe 0.87-1.73 per asset class | H001, K7.1 |
| Wen, Cho, Ma, Xu (2019?), crude oil intraday momentum (USO, 2006-2018) (summary: [Quantpedia](https://vvv.quantpedia.com/?p=4247)) | First half-hour return from the previous close predicts the last half-hour, in and out of sample | H001, H002, K7.2 |
| Wen, Indriawan, Lien, Xu (2023), *Intraday return predictability in the crude oil market: the role of EIA inventory announcements*, The Energy Journal 44(5) ([summary](https://www.iaee.org/ej/ejexec/ej44-5-Xu-exsum.pdf)) | On EIA days the third half-hour (10:30 release) predicts the last half-hour; on other days the first half-hour; the first half-hour's power comes mostly from the overnight part | H002, H005, K7.2 |
| Heston, Korajczyk, Sadka (2010), *Intraday patterns in the cross-section of stock returns*, Journal of Finance ([pdf](https://www.bauer.uh.edu/departments/finance/documents/Heston_Korajczyk_Sadka_paper_UH.pdf)) | Half-hour returns continue at daily lags (same slot on previous days) for 40+ days; stocks only | H014 |
| Zarattini, Aziz, Barbon (2024/2025), *Beat the market: an effective intraday momentum strategy for S&P500 ETF (SPY)* ([pdf](https://alexandria.unisg.ch/server/api/core/bitstreams/a99aba00-f967-49b3-aceb-f544dc386e0b/content)) | "Noise area" from time-of-day average moves (14 days); trend entries on breakouts, trailing stops, volatility sizing; 2007-2024 Sharpe 1.33 net (SPY only, untested on futures) | H010 |
| Boyarchenko, Larsen, Whelan, *The overnight drift* (NY Fed Staff Report; [link](https://fedinprint.org/item/fednls/92064)) | US equity index futures: most of the premium earned 2:00-3:00 ET, from resolving end-of-day order imbalances; larger reversals after late sell-offs; faded since 2021 | H009 |

## Crude oil announcements

| Paper | Key finding | Feeds |
|---|---|---|
| Li, Geman (2018), Journal of Energy Markets 11(2) ([link](https://www.risk.net/journal-of-energy-markets/5728636/an-analysis-of-intraday-market-response-to-crude-oil-inventory-shocks)) | WTI reacts to EIA inventory surprises within moments; effects last ~25 minutes; prices then retrace quickly | H003, K7.3 |
| Ederington, Lee (1993), *How markets process information: news releases and volatility*, Journal of Finance | Price discovery concentrates in the first minutes after scheduled releases | H003 |
| Halova, Kurov, Kucher (2014), *Noisy inventory announcements and energy prices*, Journal of Futures Markets 34(10) | Energy prices respond to inventory surprises; noise in announcements matters | H003 (background) |
| Kurov, Sancetta, Strasser, Wolfe (2019), *Price drift before U.S. macroeconomic news*, JFQA | Pre-announcement drift in the direction of the surprise for some releases | H002/H003 (background) |

## Commodity term structure and trend

| Paper | Key finding | Feeds |
|---|---|---|
| Gorton, Hayashi, Rouwenhorst (2013), *The fundamentals of commodity futures returns*, Review of Finance | Backwardation / inventories relate to futures risk premia | H004, H005, H013 |
| Moskowitz, Ooi, Pedersen (2012), *Time series momentum*, JFE | 1-12 month trends persist across futures (diversified portfolios) | H011 |
| Koijen, Moskowitz, Pedersen, Vrugt (2018), *Carry*, JFE | Carry (term-structure slope) predicts returns across asset classes | H004 |
| Mou (2011), *Limits to arbitrage and commodity index investment: front-running the Goldman roll* | Predictable spread pressure during index roll windows | H016 |
| Working (1949); Bessembinder et al. (1995) | Theory of storage; mean reversion in the futures term structure | H015, H016 |

## Statistics and backtest overfitting

| Paper | Use here |
|---|---|
| White (2000), *A reality check for data snooping*, Econometrica | best-of-candidates test (PROTOCOL §4.3) |
| Hansen (2005), *A test for superior predictive ability*, JBES | SPA test |
| Romano, Wolf (2005), *Stepwise multiple testing as formalized data snooping*, Econometrica | family-wise max-t step-down |
| Politis, Romano (1994), *The stationary bootstrap*, JASA | resampling with dependence |
| Benjamini, Hochberg (1995), JRSS-B | false discovery rate for exploratory tables |
| Bailey, López de Prado (2014), *The deflated Sharpe ratio*, Journal of Portfolio Management | DSR (V4) |
| Bailey, Borwein, López de Prado, Zhu (2017), *The probability of backtest overfitting*, Journal of Computational Finance | PBO (V3) |
| Harvey, Liu, Zhu (2016), *... and the cross-section of expected returns*, RFS | why t ≈ 2 is not enough after many tries |
| López de Prado (2018), *Advances in Financial Machine Learning* | purged / embargoed cross-validation (S003) |
| Lo, MacKinlay (1988), *Stock market prices do not follow random walks*, RFS | variance ratio test (S002) |
| Magdon-Ismail et al. (2004), *On the maximum drawdown of a Brownian motion*, Journal of Applied Probability | drawdown sanity checks (S001) |
