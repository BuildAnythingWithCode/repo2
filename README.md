# Bitcoin Risk Metric

One number per day, from 0 to 1, that says where bitcoin sits in its market cycle.

- **0** means bitcoin looks the way it looked at past cycle lows.
- **1** means it looks the way it looked at past cycle highs.

Think of it as a thermometer for the market. It tells you how hot or cold things are against bitcoin's own history. It does not tell you what tomorrow brings, and none of this is financial advice.

**Snapshot, data through 24 November 2026:** the reading is **0.15**, in the Very low zone, with bitcoin at $59,791.

## How it did

The metric was backtested over bitcoin's whole history, one day at a time. Each day's reading uses only data that existed on that day.

| Cycle | Reading at the low (perfect is 0) | Reading at the high (perfect is 1) | Day-by-day match with hindsight (perfect is 1) |
| --- | --- | --- | --- |
| 2015 to 2018 | 0.05 | 0.98 | 0.90 |
| 2019 to 2022 | 0.07 | 0.84 | 0.91 |
| 2023 to October 2025 | 0.06 | 0.85 | 0.95 |

Four things to keep in mind:

- **It marks seasons, not days.** The top zone first lit up 11 to 19 months before each of the last three highs.
- **Three cycles is three data points.** A recipe that fits them well can still be fooled by the fourth.
- **Hindsight flatters it a little.** Rebuilt blind, using only what was known before each cycle, it read 0.76 and 0.77 at the last two highs instead of 0.84 and 0.85.
- **It is a gauge, not a money machine.** A simple trading rule built on it had smaller drops than just holding, and made far less money over the long run.

The full story, with every table and every caveat, is in [WRITEUP.md](WRITEUP.md).

## Run it yourself

You need Python 3 (tested on 3.13). No accounts or API keys are needed, because everything comes from free public sources.

```bash
pip install -r requirements.txt
python3 -I scripts/refresh.py            # download, score, backtest, export: about 2 minutes
python3 -I scripts/check_no_peeking.py   # prove that no reading uses later data
```

`refresh.py` stops at the first problem. When all is well it ends with a line like this:

```
OK  data through 2026-11-24  price $59,791  reading 0.147  zone Very low
```

## How the score is made

1. **Collect.** Free public data is downloaded fresh on every run: price, market value, what holders paid for their coins, mining and network activity.
2. **Measure.** The data is turned into indicators, such as price against its 4-year average. Distances are counted in bitcoin's own typical swings, not raw percent.
3. **Give each indicator its own ruler.** The level of its past lows is marked 0 and the level of its past highs is marked 1. Old marks fade slowly, and the ruler is read with a one-year delay so it cannot stretch during the very move it is measuring.
4. **Blend.** Indicators that ask the same question are averaged into a lens, and the three lenses get one equal vote each.
5. **Smooth the ends.** A gentle S-curve lets the result approach 0 and 1 without ever sticking to them.

Seven indicators make the score:

| Lens | Indicators |
| --- | --- |
| Trend | Price / 4-year average, Price / 2-year average, Power-law trend deviation, Price / Top price |
| On-chain | MVRV |
| Range | Drawdown from record high, Position in 2-year range |

They were chosen by one rule, not by hand: keep every indicator whose own reading followed past cycles with a correlation of at least 0.75. Another 38 indicators are computed every day for context, and 4 were left out on purpose. The halving calendar gets its own dial beside the score and is not part of it.

## What is in this repository

| Path | What it is |
| --- | --- |
| `WRITEUP.md` | The plain-English write-up: method, backtest, blind test, limits |
| `src/btcrisk/fetch.py` | Downloads the raw data from the free sources |
| `src/btcrisk/dataset.py` | Builds one clean daily table from the downloads |
| `src/btcrisk/features.py` | The 49 indicators |
| `src/btcrisk/scoring.py` | The rulers and the S-curve |
| `src/btcrisk/model.py` | The metric itself: the lenses, the settings and the selection rule |
| `src/btcrisk/clock.py` | The halving clock, a separate calendar-only dial |
| `src/btcrisk/labels.py` | The hindsight answer key the metric is graded against |
| `src/btcrisk/evaluate.py` | The grading: tracking, timing, zones and the trading-rule test |
| `scripts/refresh.py` | One command that runs the four steps below in order and checks the result |
| `scripts/update_data.py` | Step 1: download the data |
| `scripts/run_backtest.py` | Step 2: run the model and the full backtest |
| `scripts/export_dashboard.py` | Step 3: write the dashboard's data files |
| `scripts/pack_dashboard.py` | Step 4: wrap the dashboard's page files |
| `scripts/check_no_peeking.py` | Proves that no reading depends on later data |
| `dashboard/` | The dashboard page: HTML, CSS and JavaScript |
| `out/backtest/` | The backtest's result tables, kept here so you can read them without running anything |

The three files at the top level (`index.html`, `script.js` and `style.css`) were in this repository before the metric and are not part of it.

## Where the data comes from

| Source | What it provides |
| --- | --- |
| [Coin Metrics community data](https://community-api.coinmetrics.io/v4) | Daily price since July 2010, market value, MVRV, supply, mining and network activity |
| [Blockchain.com charts](https://api.blockchain.info/charts) | Extra mining and transaction series |
| [Coinbase Exchange](https://api.exchange.coinbase.com) | Daily candles, kept as a second opinion on price. No indicator uses them. |
| [alternative.me](https://api.alternative.me/fng/) | The Fear & Greed index, from February 2018 |
| [DefiLlama](https://stablecoins.llama.fi/stablecoincharts/all) | Stablecoin supply |
| [CBBI](https://colintalkscrypto.com/cbbi/) | A public index used as a benchmark to compare against. It is never an input. |

## The dashboard and the daily refresh

A [live dashboard](https://claude.ai/artifact/QUg3TC853LDcuCjmDA5R6Z) shows today's reading, bitcoin's price history coloured by risk, and what every indicator says. It is a private page, so the link opens only for people its owner has shared it with.

The dashboard rebuilds itself every day at 04:32 UTC. A scheduled task takes a fresh copy of this repository, runs `python3 -I scripts/refresh.py`, and swaps in the new data files only if every check passes. If anything fails, the dashboard keeps the previous day's numbers.
