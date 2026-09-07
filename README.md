# Trading Strategy Framework

Plug-in trading strategy framework: multi-source data, strategy registry, param sweep backtest, TinyDB signal store, AI reviewer, TradingView chart links, social sentiment scan, Discord/Telegram output.

All output tagged `[framework]`.

## Strategies

| Strategy | Market | Trigger Time | Status |
|----------|--------|--------------|--------|
| `dtat-scalper` | US | 21:30 HKT (US open) | ✅ tested |
| `orb` | US | 22:00 HKT | ⚠️ stub |
| `lighthouse-overnight` | HK | 15:15 HKT (HK close) | ✅ tested |
| `quality-screen` | HK/US | pre-market filter | ✅ tested |

## Data Sources

- **Tencent qt.gtimg.cn** — HK + US realtime (no delay)
- **yfinance** — US historical only (15-min delay on realtime)
- **Futu OpenD** — HK realtime (requires OpenD GUI + CDP port 18800)

## Quick Start

```bash
cd framework
/usr/bin/python3 backtest_engine.py --strategy lighthouse-overnight --scan --tickers 00700,09988
/usr/bin/python3 backtest_engine.py --strategy dtat-scalper --scan --tickers AAPL,META
/usr/bin/python3 backtest_engine.py --strategy quality-screen --scan --tickers 00700

# Two-stage filter (quality → trading)
/usr/bin/python3 filter_pipeline.py --strategy lighthouse-overnight \
    --screen-min-score 50 --tickers 00700,09988,00100,01347

# Full pipeline: scan + AI review + Discord
/usr/bin/python3 backtest_engine.py --strategy lighthouse-overnight --full \
    --with-charts --with-social
```

## Signal DB

TinyDB at `~/.tjl_signals/signals.json`. Schema:
- `ticker`, `name`, `direction`, `strategy`, `market`
- `entry`, `tp`, `sl`, `atr`, `score`
- `status` (open|closed|cancelled), `exit`, `exit_time`, `pnl_pct`
- `created` (ISO timestamp), `remark` (free text)
- `metadata` (strategy-specific extras)

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│  DataSrc Registry → Strategy Registry → Backtest Engine    │
│  SignalDB TinyDB → Reviewer (M3) → Output (Discord/TG)     │
└────────────────────────────────────────────────────────────┘
```

## Pipeline Steps

1. Scan → 2. AI Review → 3. Stats
3.4. TradingView links + Chrome tabs
3.5. Social scan (Futu + Xueqiu)
4. Discord post

See `SKILL.md` for full details.
