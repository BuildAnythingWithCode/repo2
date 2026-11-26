# Bitcoin Risk Metric: how it works and how it did

*This is a snapshot. Every figure comes from the backtest run on 25 November 2026, on data through 24 November 2026. The [live dashboard](https://buildanythingwithcode.github.io/repo2/) always shows today's numbers, and `python3 -I scripts/refresh.py` rebuilds all of this on today's data.*

## The short version

Bitcoin's risk reading is 0.15 out of 1, in the Very low zone, on data through 24 November 2026 when bitcoin closed at $59,791. The [live dashboard](https://buildanythingwithcode.github.io/repo2/) shows the current number and rebuilds itself every day.

The metric is one number per day. A reading of 0 means bitcoin looks the way it looked at past cycle lows, and 1 means it looks the way it looked at past cycle highs. Think of it as a thermometer for the market: it tells you how hot or cold things are against bitcoin's own history. It does not tell you what tomorrow brings.

It was graded on the three complete cycles it could score from start to finish:

- **Tops.** It read 0.98, 0.84 and 0.85 on the 2017, 2021 and 2025 highs. A perfect gauge would read 1.
- **Bottoms.** It read 0.05, 0.07 and 0.06 on the 2015, 2018 and 2022 lows. A perfect gauge would read 0.
- **Everything in between.** Day by day, it followed where price really sat inside each cycle with a correlation of 0.92, where 1.00 is a perfect match.

Three things to know before leaning on it:

- **It marks seasons, not days.** The Very high zone first lit up 11 to 19 months before each of the last three tops.
- **Three cycles is three data points.** The recipe fits them well and can still be fooled by the fourth.
- **Today's number is soft.** Nudging the design choices moves today's reading anywhere between 0.07 and 0.20. Low either way, but not a hard fact.

## How to read the number

The scale is cut into five zones, and history has treated them very differently. The table groups every scored day since January 2013 by its reading and shows what price did over the following 12 months.

| Zone | Reading | Days spent there | Typical change, next 12 months | Higher a year later | Typical worst dip on the way |
| --- | --- | --- | --- | --- | --- |
| Very low | 0.0 to 0.2 | 799 | +98% | 100% of days | −10% |
| Low | 0.2 to 0.4 | 820 | +110% | 85% | −18% |
| Neutral | 0.4 to 0.6 | 844 | +60% | 67% | −44% |
| High | 0.6 to 0.8 | 1,201 | +71% | 58% | −21% |
| Very high | 0.8 to 1.0 | 1,036 | −10% | 44% | −28% |

"Typical" means the median, the middle outcome of all the days in that zone.

The two ends are where the number earns its keep. Every one of the 799 days below 0.2 was followed by a higher price a year later, and the typical day above 0.8 was followed by a loss.

Read the pattern, not the decimals. These 4,700 days come from only a handful of cycles, so they are nowhere near 4,700 independent tests. It is like judging a restaurant from thousands of bites taken during four visits.

The zones are seasons, not alarms. The reading has sat above 0.8 on about one scored day in five, because bitcoin's bull markets are long and its top zone switches on early. Very high means "this is what late in a cycle has looked like", not "sell today".

## How the score is built

The score is made in five steps, and every step uses only the data that existed on the day being scored. That one rule is what makes the backtest honest: the reading for a day in 2017 never saw 2018.

1. **Collect.** Free public data is downloaded fresh every day: price, market value, what holders paid for their coins, mining and network activity.
2. **Measure.** The data is turned into indicators, such as price against its 4-year average. Distances are counted in bitcoin's own typical swings, not raw percent. A 50% jump was an ordinary month in 2013 and is a big event now, the way a wave is judged by how rough that sea usually is.
3. **Give each indicator its own ruler.** The level of its past lows is marked 0 and the level of its past highs is marked 1, like pencil marks on a door frame. Old marks fade slowly, so recent cycles count more.
4. **Blend.** Indicators that ask the same question are averaged into a lens. The three lenses are then averaged, each with an equal vote.
5. **Smooth the ends.** A gentle S-curve lets the result approach 0 and 1 without ever sticking to them. The most extreme day in history still gets the most extreme reading.

Two details in step 3 matter more than they look.

The ruler is read with a one-year delay. During a blow-off, an indicator makes new highs every week, and a ruler that updated instantly would stretch along with it. Reading last year's ruler is like not letting the runner move the finish line mid-race.

The ends of the ruler are not the single highest and lowest values ever seen. They are the levels the indicator stayed inside 96% of the time, with older history fading at a half-life of eight years. One freak day cannot bend the scale.

## What goes into it

Seven indicators make the score, chosen from 49 that were built and tested. They sit in three lenses so that four similar trend gauges cannot outvote the one on-chain gauge.

```
                             ┌── Price / 4-year average
                             ├── Price / 2-year average
           ┌── Trend ────────┤
           │   one third     ├── Power-law trend deviation
           │                 └── Price / Top price
           │
Reading ───┼── On-chain ─────── MVRV
0 to 1     │   one third
           │
           │                 ┌── Drawdown from record high
           └── Range ────────┤
               one third     └── Position in 2-year range
```

Read it from right to left: seven indicators are averaged into three lenses, and the three lenses into one reading.

| Lens | Indicator | The question it asks | On 24 Nov 2026 |
| --- | --- | --- | --- |
| Trend | Price / 4-year average | How far is price from its own 4-year average? | 0.90x its average |
| Trend | Price / 2-year average | The same question over 2 years. | 0.67x its average |
| Trend | Power-law trend deviation | How far is price from a long-run growth curve, refitted every day on past data only? | −59% vs. trend |
| Trend | Price / Top price | How close is price to a classic ceiling, 35 times its all-time average market value? | 8% of Top price |
| On-chain | MVRV | How far is price above the average price at which every coin last moved? | 1.13 |
| Range | Drawdown from record high | How far has price fallen from its record high? | −52% |
| Range | Position in 2-year range | Where does price sit between its 2-year low and high? | 3% of the way up |

**How the seven were chosen.** Not by hand. One rule did it: keep every indicator whose own reading followed past cycles with a correlation of at least 0.75. Seven passed, and the blind test further down re-runs that same rule on older data.

**What was watched but left out.** Another 38 indicators run every day and appear on the dashboard as grey dots: momentum, miners, network activity and sentiment. They followed the cycles less faithfully. The Puell Multiple scored 0.58, the Mayer Multiple 0.54, Fear & Greed 0.50 and NVT 0.20.

**What was left out on purpose.** Four were excluded before any testing. Two compare price with everything miners have ever earned, a yardstick that grows more slowly after each halving, so the ratio drifts upward for reasons unrelated to the cycle. Two are pure calendar counts.

**The halving clock.** The four-year halving calendar gets its own dial beside the score, not a seat inside it. Adding the calendar was tested and did not make the score better. On 24 November 2026 the clock read 0.02: by the timing of past cycles a low was due around late August 2026, and the next high around August 2029.

## How it was tested

The backtest asks one question of all 5,065 days since 12 January 2013: what would the metric have said that day, knowing only what was knowable then? Scores start in 2013 because the rulers need about two years of bitcoin's price history, which begins in July 2010, before they mean anything.

**The answer key.** Turning points were marked afterwards by a mechanical rule on price, not by eye. A fall of 70% or a rise of 233% marks a cycle turn, and a fall of 50% or a rise of 100% marks a smaller mid-cycle turn. Every day between two turns then gets a hindsight value: 0 at the bottom, 1 at the top, and in between according to where price stood on the way. The answer key is there for grading. No reading is ever calculated from it.

**The four grades.**

1. **Tops and bottoms.** Did it read near 1 on the real tops and near 0 on the real bottoms?
2. **Tracking.** Day by day, how closely did the reading follow the hindsight value? This is a correlation, where 1.00 is a perfect match.
3. **Timing.** On the 30 most extreme readings of each cycle, how close was price to the actual turn?
4. **Aftermath.** Did high readings come before poor returns, and low readings before good ones?

**Which cycles count.** The headline grades use the three cycles the metric scored from start to finish: 2015 to 2018, 2019 to 2022, and 2023 to the October 2025 high. The years 2013 and 2014 are reported separately, because the rulers were still young.

**Proof of no peeking.** The data was cut off at eight past dates and the whole model re-run each time. Every earlier reading came out identical to 14 decimal places, so no reading depends on anything that happened after it. Anyone can repeat this with one command in the code.

**Where hindsight did get in.** Once, in choosing which indicators to trust. The rule that picked the seven compared every indicator with the answer key over the whole history up to the October 2025 high. The blind test below measures how much that flatters the results.

## Results

On the three complete cycles the metric read 0.84 or higher on every top and 0.07 or lower on every bottom.

| Turning point | Date | Size | Price | Reading |
| --- | --- | --- | --- | --- |
| Bottom | 6 July 2013 | Cycle turn | $66 | 0.40 |
| Top | 4 December 2013 | Cycle turn | $1,135 | 0.98 |
| Bottom | 14 January 2015 | Cycle turn | $176 | 0.05 |
| Top | 16 December 2017 | Cycle turn | $19,641 | 0.98 |
| Bottom | 15 December 2018 | Cycle turn | $3,185 | 0.07 |
| Top | 26 June 2019 | Mid-cycle turn | $12,863 | 0.70 |
| Bottom | 12 March 2020 | Mid-cycle turn | $4,959 | 0.14 |
| Top | 13 April 2021 | Mid-cycle turn | $63,446 | 0.88 |
| Bottom | 20 July 2021 | Mid-cycle turn | $29,767 | 0.50 |
| Top | 8 November 2021 | Cycle turn | $67,542 | 0.84 |
| Bottom | 9 November 2022 | Cycle turn | $15,758 | 0.06 |
| Top | 6 October 2025 | Cycle turn | $124,824 | 0.85 |

Every turning point since the middle of 2013, with the reading the metric gave on that day. A perfect gauge would read 1.00 on every top and 0.00 on every bottom.

**The misses are honest.** The July 2013 low read 0.40. The metric was six months old, and that low was a 70% crash in the middle of a bull run, not the end of a bear market. Mid-cycle turns sit nearer the middle by design: a 50% dip inside a bull market is not a cycle low, and the reading does not pretend it is.

**Tops are getting quieter.** The 2013 and 2017 highs read 0.98, and the 2021 and 2025 highs about 0.85. Each cycle has been tamer than the one before, and a ruler built from the past always runs a little behind that.

**Tracking, period by period.**

| Period | Match with the hindsight value |
| --- | --- |
| 2013 to 2014 | 0.36 |
| 2015 to 2018 | 0.90 |
| 2019 to 2022 | 0.91 |
| 2023 to October 2025 | 0.95 |

Over the three complete cycles the match averages 0.92, and the typical gap between the reading and the hindsight value is 0.10. The weak first row is the young-ruler period.

**Timing.** At bottoms the metric was about as good as a gauge can be. On its 30 lowest readings of each cycle, price averaged 14% above the eventual low, and a perfect gauge would have managed 12%.

At tops it was early. On its 30 highest readings of each cycle, price averaged 79% of the eventual high, against 90% for a perfect gauge. In 2021 and 2025 the peak readings came 8 to 10 months before the final high.

## The blind test

Built blind, the metric read 0.76 and 0.77 on the last two cycle tops, against 0.84 and 0.85 for the final recipe. That gap of about 0.08 is the best single estimate of how much hindsight flatters the headline numbers.

The final recipe has an unfair advantage: its seven indicators were chosen by someone who had already seen every cycle. It is like a student who sat the exam after seeing the paper. So the selection rule was re-run the honest way, twice, each time with only the data that existed before the cycle it was graded on.

| Graded on | How the recipe was made | Reading at the top | Reading at the bottom | Match with the hindsight value |
| --- | --- | --- | --- | --- |
| 2018 to 2021 | Blind: rule run on data up to the December 2017 top, which picked 13 indicators | 0.76 | 0.17 | 0.86 |
| 2018 to 2021 | Blind: all 45 indicators averaged, no choosing | 0.61 | 0.11 | 0.86 |
| 2018 to 2021 | Not blind: the final recipe | 0.84 | 0.07 | 0.90 |
| 2022 to 2025 | Blind: rule run on data up to the November 2021 top, which picked 6 indicators | 0.77 | 0.07 | 0.93 |
| 2022 to 2025 | Blind: all 45 indicators averaged, no choosing | 0.58 | 0.14 | 0.79 |
| 2022 to 2025 | Not blind: the final recipe | 0.85 | 0.07 | 0.96 |

Three things follow.

- **Expect the next top to read around 0.7 to 0.8, not 1.** The blind rows are the fair forecast of how the metric behaves on a cycle it has not seen.
- **Bottoms survived the blind test better than tops.** Both blind lows landed inside the Very low zone.
- **Choosing indicators is what makes the gauge work.** Averaging everything reads about 0.6 at a top, because dozens of weak indicators water down the few good ones.

One reassurance: run on the full history, the rule picks exactly the seven indicators in the final recipe. Nothing was added by hand, and the only things dropped by hand are the four exclusions described earlier.

Two caveats on the blind test itself.

- **The bar was set with hindsight.** The 0.75 cut-off in the rule is itself a choice made after seeing every cycle. A looser bar of 0.70 gave nearly the same blind readings at the two tops, 0.76 and 0.78. A stricter bar of 0.80 kept only 8 and then 3 indicators and did worse: 0.71 and 0.65 at the tops, and 0.23 at the 2018 low.
- **A top is only known afterwards.** The rule used data up to each top, yet nobody could have run it until bitcoin had halved from that high, in February 2018 and May 2022. Both graded bottoms and both graded tops came after those dates, so the readings in the table are blind in the strict sense.

## How it compares with other gauges

CBBI, the best-known public index of this kind, grades slightly better than this metric on every measure and reads 0.31 today against 0.15. Every gauge below was put on the same kind of 0 to 1 ruler and graded the same way on the same three cycles.

| Gauge | Match with the hindsight value | Average at cycle tops | Average at cycle bottoms | On 24 Nov 2026 |
| --- | --- | --- | --- | --- |
| **Bitcoin Risk Metric** | 0.92 | 0.89 | 0.06 | 0.15 |
| [CBBI](https://colintalkscrypto.com/cbbi/), a public index | 0.96 | 0.92 | 0.04 | 0.31 |
| Price / 4-year average alone | 0.97 | 0.78 | 0.05 | 0.10 |
| Power-law trend deviation alone | 0.95 | 0.78 | 0.08 | 0.03 |
| MVRV alone | 0.90 | 0.92 | 0.08 | 0.29 |
| Monthly RSI alone | 0.89 | 0.85 | 0.56 | 0.48 |
| Plain average of all 45 indicators | 0.83 | 0.70 | 0.14 | 0.23 |
| Halving calendar alone | 0.62 | 0.83 | 0.02 | 0.02 |
| Puell Multiple alone | 0.61 | 0.69 | 0.06 | 0.22 |
| Mayer Multiple alone | 0.51 | 0.73 | 0.09 | 0.17 |
| Fear & Greed alone | 0.48 | 0.70 | 0.18 | 0.19 |

**CBBI is the fair rival, with two asterisks.** Its scale is fitted to the whole history with hindsight, so its past readings are not a blind test. It also draws on coin-age data that is not free for the full history. This metric uses only free data and never looks ahead, and lands within a few hundredths of it.

**The two disagree about today.** Both say low. CBBI says 0.31 and this metric says 0.15, so treat the truth as somewhere in that range.

**No single indicator does every job.** The two trend gauges follow the cycle's path best, yet read only 0.78 at tops. MVRV reads high at tops and follows the path less well. Blending them gives a decathlete, not a sprinter: never the best at one event, good at all of them.

**The calendar alone is a stopped clock.** It looks fine on the day of each turn and poor in between, with a match of 0.62. That is why it stays a separate dial.

## What it cannot do

The metric can tell you the season. It cannot tell you the day, the size of the next move, or anything that has never happened before.

**It arrives early, especially at tops.** The table shows the first day the reading entered its extreme zone before each cycle turn, and where price stood that day.

| Turn | First day in the extreme zone | Days before the turn | Price that day against the turn |
| --- | --- | --- | --- |
| December 2017 top | 4 January 2017 | 346 | 94% below the top |
| November 2021 top | 17 December 2020 | 326 | 66% below the top |
| October 2025 top | 28 February 2024 | 586 | 50% below the top |
| January 2015 bottom | 1 November 2014 | 74 | 85% above the low |
| December 2018 bottom | 19 November 2018 | 26 | 50% above the low |
| November 2022 bottom | 13 June 2022 | 149 | 42% above the low |

Selling on the first Very high reading in January 2017 would have meant missing a seventeen-fold rise. The zones are a warning light, not a sell-by date.

**It is a gauge, not a money machine.** A mechanical rule was tested: keep a share of your money in bitcoin equal to one minus the reading, adjust daily, and pay 0.1% on every trade.

| Starting | Money multiplied, rule | Money multiplied, just holding | Worst drop, rule | Worst drop, just holding |
| --- | --- | --- | --- | --- |
| July 2013 | 15.8x | 668x | −60% | −85% |
| January 2015 | 15.5x | 186x | −50% | −84% |
| January 2018 | 4.5x | 4.3x | −50% | −81% |

Holding won by a mile over the long run, because the rule sells early in bull markets. What the rule bought was a smaller worst drop. A second rule, all in below a reading of 0.3 and all out above 0.7, did worse than this one in every period.

**Three cycles is three data points.** A recipe that fits three cycles this well can still be fooled by the fourth, and bitcoin's cycles have been getting tamer in ways a backward-looking ruler only catches up with later.

**Today's number is soft.** Every design choice was nudged in turn, 24 variations in all. Today's reading moved between 0.07 and 0.20, and the average reading at tops between 0.86 and 0.94.

**Some data could not be used.** Coin-age data, which tracks how long coins have sat still, is not free for the full history. Interest rates, the dollar and money supply could not be reached from the machine that runs this. Futures data such as funding rates was blocked too.

**It cannot see what has never happened.** It measures where price sits against its own past. News, regulation and anything new to this cycle are outside its view. It is a thermometer, not a doctor, and none of this is financial advice.

## How it stays current

The [website](https://buildanythingwithcode.github.io/repo2/) rebuilds itself every day at about 05:17 UTC, which is 1:17 PM in UTC+8, with nobody involved, and tries again twelve hours later. Bitcoin's trading day closes at midnight UTC, and the run waits a few hours for the data sites to publish the finished day.

1. A scheduled GitHub Actions job starts and fetches the latest code.
2. It downloads the whole history again from the free sources. Nothing is cached, so a corrected figure upstream is picked up automatically.
3. It re-runs the model and the entire backtest, then checks the result: a fresh date, a reading between 0 and 1, every file present.
4. It rebuilds the website around the ten new data files and publishes it.

The whole run takes a few minutes. If any step fails, nothing is published: the website keeps the previous day's numbers, and says so once they are more than two days old.

**Where the data comes from.** All of it is free and needs no account.

| Source | What it provides |
| --- | --- |
| [Coin Metrics community data](https://community-api.coinmetrics.io/v4) | Daily price since July 2010, market value, MVRV, supply, mining and network activity |
| [Blockchain.com charts](https://api.blockchain.info/charts) | Extra mining and transaction series |
| [Coinbase Exchange](https://api.exchange.coinbase.com) | Daily candles, kept as a second opinion on price. No indicator uses them. |
| [alternative.me](https://api.alternative.me/fng/) | The Fear & Greed index, from February 2018 |
| [DefiLlama](https://stablecoins.llama.fi/stablecoincharts/all) | Stablecoin supply |
| [CBBI](https://colintalkscrypto.com/cbbi/) | A benchmark to compare against. It is never an input. |

**Where the code lives.** Everything is in the GitHub repository [BuildAnythingWithCode/repo2](https://github.com/BuildAnythingWithCode/repo2), and its [README](README.md) says what each file does. It is about 2,300 lines of Python and needs only three common packages.

- `python3 -I scripts/refresh.py` rebuilds everything from scratch in about two minutes.
- `python3 -I scripts/check_no_peeking.py` re-runs the proof that no reading uses later data.

Every number on the dashboard comes from ten data files published beside it, such as [today.json](https://buildanythingwithcode.github.io/repo2/data/today.json) and [history.json](https://buildanythingwithcode.github.io/repo2/data/history.json), so anyone can check them.
