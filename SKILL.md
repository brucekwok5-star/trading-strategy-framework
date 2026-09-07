---
name: trading-strategy-framework
description: >
  Framework: scan, backtest, review, post. Tag [framework].
triggers:
  - trading strategy framework
  - add new trading strategy
  - strategy backtest parameter sweep
  - trading signal review
---

# Trading Strategy Framework

Unified framework for building, backtesting, reviewing, and publishing trading signals.
Tag all output with `[framework]`.

---

## Architecture

```
FRAMEWORK CORE
  DataSrc Registry │ Strategy Registry │ Backtest Engine
  SignalDB (TinyDB) │ AI Reviewer (MiniMax M3) │ Output (Discord/Telegram)

DATA SOURCES
  Futu OpenD (HK) │ Tencent qt.gtimg.cn (HK+US) │ yfinance (US)
```

---

## 1. Data Source Registry

Each source implements: `fetch(tickers, start, end, interval) -> DataFrame`

### HK: Futu OpenD
```python
# framework/datasources/futu_opend.py
"""
HK real-time + historical via Futu OpenD daemon.
Start: cd ~/.hermes/bin && ./FutuOpenD &
"""
from futu import OpenQuoteContext

HOST, PORT = "127.0.0.1", 11111
KTYPE = {"1m":"K_1M","5m":"K_5M","15m":"K_15M","30m":"K_30M","1h":"K_1H","1d":"K_Day"}

def fetch(tickers, start_date=None, end_date=None, interval="1d"):
    results = {}
    with OpenQuoteContext(HOST, PORT) as ctx:
        for ticker in tickers:
            code = f"HK.{ticker.zfill(5)}"
            ret, data = ctx.request_history_kline(
                code=code, start=start_date, end=end_date,
                ktype=KTYPE.get(interval, "K_Day")
            )
            if ret == 0:
                results[ticker] = data
    return results
```

### HK+US: Tencent qt.gtimg.cn
```python
# framework/datasources/tencent_qt.py
"""
Tencent real-time quote API (web.ifzq.gtimg.cn).
HK: 'hk00XXXX' | US: 'usAAPL'
"""
import urllib.request, json, time, pandas as pd

def fetch_daily(tickers, days=320):
    results = {}
    for t in tickers:
        prefix = "hk" if t.isdigit() else "us"
        url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
               f"?_var=kline_dayhfq&param={prefix}{t},day,,,{days},qfq")
        with urllib.request.urlopen(url, timeout=10) as r:
            _, data = json.parse_known_types(r.read().decode())
        rows = data['data'][f"{prefix}{t}"]['qfqday']
        df = pd.DataFrame(rows, columns=['date','open','close','high','low','volume'])
        df = df.astype({'open':float,'close':float,'high':float,'low':float,'volume':int})
        results[t] = df
    return results

def fetch_realtime(tickers):
    q = ",".join(tickers)
    with urllib.request.urlopen(f"https://qt.gtimg.cn/q={q}", timeout=10) as r:
        raw = r.read().decode('gbk')
    results = {}
    for line in raw.strip().split('\n'):
        p = line.split('~')
        if len(p) < 10: continue
        ticker = p[0].split('_')[-1]
        results[ticker] = {
            'price': float(p[3]), 'open': float(p[5]),
            'high': float(p[33]), 'low': float(p[34]),
            'volume': int(p[36]), 'prev_close': float(p[4]),
        }
    return results
```

### US: yfinance
```python
# framework/datasources/yfinance_us.py
import yfinance as yf

def fetch(tickers, start_date=None, end_date=None, interval="1d"):
    if isinstance(tickers, str): tickers = [tickers]
    return yf.download(tickers, start=start_date, end=end_date,
                       interval=interval, auto_adjust=True, progress=False)
```

---

## 2. Strategy Registry

### Base Interface
```python
# framework/strategy_base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict
import pandas as pd

@dataclass
class Signal:
    ticker: str; name: str; direction: str   # 'LONG' or 'SHORT'
    entry_price: float; entry_time: str      # ISO timestamp
    tp_price: float; sl_price: float; atr: float
    score: float                               # 0–100
    strategy: str; market: str                 # 'HK' or 'US'
    metadata: Dict = field(default_factory=dict)

@dataclass
class BacktestResult:
    ticker: str; entry_time: str; exit_time: str; direction: str
    entry_price: float; exit_price: float; pnl_pct: float; win: bool; params: Dict

class Strategy(ABC):
    name: str = "BaseStrategy"
    market: str = "HK"
    data_source: str = "yfinance"  # 'futu' | 'tencent' | 'yfinance'

    def default_params(self) -> Dict: return {}

    @abstractmethod
    def scan(self, tickers: List[str], date: str = None) -> List[Signal]: pass

    @abstractmethod
    def backtest(self, tickers, start_date, end_date, params: Dict = None) -> List[BacktestResult]: pass

    def param_sweep(self, tickers, start_date, end_date, param_grid: Dict) -> pd.DataFrame:
        """Sweep all combos → ranked by win_rate DESC, profit_factor DESC."""
        import itertools
        keys, vals = list(param_grid.keys()), list(param_grid.values())
        results = []
        for combo in itertools.product(*vals):
            params = dict(zip(keys, combo))
            runs = self.backtest(tickers, start_date, end_date, params)
            wins = [r for r in runs if r.win]
            total = len(runs)
            if total == 0: continue
            wr = len(wins)/total*100
            avg_win  = sum(r.pnl_pct for r in wins)/len(wins) if wins else 0
            avg_loss = abs(sum(r.pnl_pct for r in runs if not r.win)/(total-len(wins))) if total>len(wins) else 0
            pf = abs(avg_win/avg_loss) if avg_loss else float('inf')
            results.append({'params':params,'trades':total,'win_rate':wr,
                            'avg_win':avg_win,'avg_loss':avg_loss,'profit_factor':pf})
        return pd.DataFrame(results).sort_values(['win_rate','profit_factor'], ascending=[False,False])
```

### Strategy A: D-TAT Scalper
```python
# framework/strategies/dtat_scalper.py
"""
D-TAT Scalper — Touch & Turn.
Rule: candle close < open → LONG (red swept lows) | close > open → SHORT (green swept highs)
Entry: range low (LONG) / range high (SHORT)
TP: Fibonacci level of opening range | SL: 2:1 R:R
Filters: liquidity ≥ 25% ATR, real body, volume confirm
"""
from framework.strategy_base import Strategy, Signal, BacktestResult
import yfinance as yf, pandas as pd

class DTATScalperStrategy(Strategy):
    name = "dtat-scalper"; market = "US"; data_source = "yfinance"

    def default_params(self):
        return {'or_pct':0.25,'tp_level':0.382,'rr_ratio':2.0,'atr_period':14,'entry_offset':0.0}

    def scan(self, tickers, date=None):
        signals = []
        for ticker in tickers:
            try:
                df_5m = yf.download(ticker, period='2d', interval='5m', auto_adjust=True, progress=False)
                df_d  = yf.download(ticker, period='1mo', interval='1d',  auto_adjust=True, progress=False)
                if df_5m.empty or df_d.empty: continue
                df_15m = df_5m.resample('15min').agg(
                    {'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}
                ).dropna()
                atr = float(df_d['Close'].diff().abs().rolling(14).mean().iloc[-1])
                if atr == 0: continue
                c = df_15m.iloc[0]; cr = c['High'] - c['Low']
                p = self.default_params()
                if cr < p['or_pct'] * atr: continue
                if c['Close'] < c['Open']:
                    direction, entry = 'LONG', c['Low'] - p['entry_offset']
                    tp = entry + p['tp_level'] * cr
                    sl = entry - (tp-entry)/p['rr_ratio']
                else:
                    direction, entry = 'SHORT', c['High'] + p['entry_offset']
                    tp = entry - p['tp_level'] * cr
                    sl = entry + (entry-tp)/p['rr_ratio']
                score = min(100, (cr/(p['or_pct']*atr))*50)
                signals.append(Signal(ticker=ticker, name=ticker, direction=direction,
                    entry_price=round(entry,2), entry_time=str(c.name),
                    tp_price=round(tp,2), sl_price=round(sl,2),
                    atr=round(atr,4), score=round(score,1),
                    strategy=self.name, market=self.market,
                    metadata={'candle_range':round(cr,4)}))
            except: continue
        return signals

    def backtest(self, tickers, start_date, end_date, params=None):
        # Loop each ticker + each day → build Signal → compute P/L → BacktestResult
        ...
        return []
```

### Strategy B: ORB
```python
# framework/strategies/orb.py
"""
Opening Range Breakout.
N-min OR (default 30min): LONG above range_high+breakout_pct, SHORT below range_low-breakout_pct
TP: entry ± ATR×atr_mult | SL: entry ∓ ATR×sl_mult
"""
from framework.strategy_base import Strategy, Signal, BacktestResult

class ORBStrategy(Strategy):
    name = "orb"; market = "US"; data_source = "yfinance"

    def default_params(self):
        return {'orb_minutes':30,'breakout_pct':0.0,'atr_multiplier':2.0,'sl_multiplier':1.0,'atr_period':14}

    def scan(self, tickers, date=None):
        signals = []
        # Fetch 5-min bars → build OR → check breakout → Signal
        ...
        return signals
```

### Strategy C: Lighthouse Overnight
```python
# framework/strategies/lighthouse_overnight.py
"""
灯塔 Overnight: buy last-30-min close, hold overnight.
Exit: +2.5% half / +4% full / -2% hard stop / 09:45 time stop.
Filters: gain ≥ threshold, vol surge ≥1.5x, close > MA20.
"""
from framework.strategy_base import Strategy, Signal, BacktestResult

class LighthouseOvernightStrategy(Strategy):
    name = "lighthouse-overnight"; market = "HK"; data_source = "yfinance"

    def default_params(self):
        return {'gain_threshold':3.0,'vol_ratio_min':1.5,'ma_period':20,
                'tp1_pct':2.5,'tp2_pct':4.0,'sl_pct':2.0}

    def scan(self, tickers, date=None):
        signals = []
        # ... scan logic
        return signals
```

---

## 3. Signal Database (TinyDB)

```python
# framework/signal_db.py
"""
TinyDB NoSQL for signals + backtest results.
DB: ~/.tjl_signals/signals.json
Schema: signals (open/closed), backtests (run metadata)
"""
from tinydb import TinyDB, Query
from pathlib import Path
from functools import reduce
import pandas as pd

DB = Path("~/.tjl_signals/signals.json").expanduser()
DB.parent.mkdir(parents=True, exist_ok=True)
db = TinyDB(str(DB))
sig_tbl = db.table('signals')
bt_tbl  = db.table('backtests')
Q = Query()

def insert_signal(sig) -> dict:
    doc = {
        'ticker':sig.ticker,'name':sig.name,'direction':sig.direction,
        'entry_price':sig.entry_price,'entry_time':sig.entry_time,
        'tp_price':sig.tp_price,'sl_price':sig.sl_price,'atr':sig.atr,
        'score':sig.score,'strategy':sig.strategy,'market':sig.market,
        'metadata':sig.metadata,'status':'open',
        'exit_price':None,'exit_time':None,'pnl_pct':None,
        'created_at':pd.Timestamp('now').isoformat(),
    }
    sig_tbl.insert(doc)
    return doc

def close_signal(ticker, entry_time, exit_price, exit_time, pnl_pct):
    sig_tbl.update({'status':'closed','exit_price':exit_price,
                    'exit_time':exit_time,'pnl_pct':pnl_pct},
                   (Q.ticker==ticker)&(Q.entry_time==entry_time))

def get_open(strategy=None, market=None):
    conds = [Q.status=='open']
    if strategy: conds.append(Q.strategy==strategy)
    if market:   conds.append(Q.market==market)
    return sig_tbl.search(reduce(lambda a,b: a&b, conds))

def strategy_stats(strategy, start_date=None, end_date=None) -> dict:
    conds = [Q.status=='closed', Q.strategy==strategy]
    if start_date: conds.append(Q.entry_time>=start_date)
    if end_date:   conds.append(Q.entry_time<=end_date)
    rows = sig_tbl.search(reduce(lambda a,b: a&b, conds))
    if not rows: return {'trades':0,'win_rate':0,'avg_pnl':0,'pf':0}
    wins=[r for r in rows if r['pnl_pct']>0]; losses=[r for r in rows if r['pnl_pct']<=0]
    wr = len(wins)/len(rows)*100
    avg_win  = sum(r['pnl_pct'] for r in wins)/len(wins) if wins else 0
    avg_loss = abs(sum(r['pnl_pct'] for r in losses)/len(losses)) if losses else 0
    return {'strategy':strategy,'trades':len(rows),'win_rate':round(wr,1),
            'avg_pnl':round(sum(r['pnl_pct'] for r in rows)/len(rows),3),
            'profit_factor':round(avg_win/avg_loss if avg_loss else float('inf'),2),
            'max_dd':round(min(r['pnl_pct'] for r in rows),2)}
```

---

## 4. Backtest Engine

```python
# framework/backtest_engine.py
"""
Scan + param sweep orchestrator.
CLI:
  --scan   : run live scan, store signals in TinyDB
  --sweep  : param sweep → ranked DataFrame
  --full   : scan → review → post Discord
"""
import argparse
from framework.strategies.dtat_scalper import DTATScalperStrategy
from framework.strategies.orb import ORBStrategy
from framework.strategies.lighthouse_overnight import LighthouseOvernightStrategy
from framework.signal_db import insert_signal
from framework.reviewer import review_signals
from framework.output import daily_report

STRATEGIES = {
    'dtat-scalper': DTATScalperStrategy(),
    'orb': ORBStrategy(),
    'lighthouse-overnight': LighthouseOvernightStrategy(),
}

def scan(name, tickers, date=None):
    sigs = STRATEGIES[name].scan(tickers, date)
    for s in sigs: insert_signal(s)
    return sigs

def sweep(name, tickers, start, end, grid):
    return STRATEGIES[name].param_sweep(tickers, start, end, grid)

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--strategy', required=True, choices=list(STRATEGIES.keys()))
    p.add_argument('--scan', action='store_true')
    p.add_argument('--sweep', action='store_true')
    p.add_argument('--full', action='store_true')
    p.add_argument('--tickers', default='')
    p.add_argument('--start-date', default='2026-01-01')
    p.add_argument('--end-date', default='2026-09-01')
    args = p.parse_args()
    tk = args.tickers.split(',') if args.tickers else []
    if args.scan:
        sigs = scan(args.strategy, tk)
        print(f"[framework] {args.strategy}: {len(sigs)} signals")
        for s in sigs:
            print(f"  {s.direction} {s.ticker} @ {s.entry_price} TP{s.tp_price} SL{s.sl_price}")
    elif args.sweep:
        df = sweep(args.strategy, tk, args.start_date, args.end_date,
                   {'tp_level':[0.236,0.382,0.5],'rr_ratio':[1.5,2.0,2.5]})
        print(df.to_string(index=False))
```

---

## 5. AI Reviewer (MiniMax M3.0)

```python
# framework/reviewer.py
"""
Spawns separate hermes agent (MiniMax M3.0) to review signals.
Checks: data correctness, criteria met, TP/SL plausible, best 3 long+short.
"""
import subprocess, json

REVIEW_PROMPT = """You are a quantitative trading reviewer. Tag all output with [framework].

## Strategy: {strategy} | Market: {market} | Data Source: {data_source}

## Signals
```json
{signals_json}
```

## Review Tasks
1. **Data correctness**: price within 10% of reasonable market price? volume > 0? timestamp valid trading hours?
2. **Criteria met**: ALL filter conditions from the strategy spec are satisfied?
3. **TP/SL plausible**: distances within ±3x ATR? entry reasonable?
4. **Best 3 LONG** and **Best 3 SHORT**: rank by score, must pass all criteria.
5. **Concerns**: flag any suspicious signal (penny-stock vol artifact, data glitch, etc.).

Respond:
[framework]
### Data Check
PASS/FAIL per signal

### Criteria Check
PASS/FAIL per signal

### TP/SL Analysis
PLAUSIBLE / SUSPICIOUS per signal

### Best 3 LONG
1. TICKER score reason
...

### Best 3 SHORT
1. TICKER score reason
...

### Concerns
list flagged signals
"""

def review_signals(signals, strategy_name, market, data_source):
    sj = json.dumps([{'ticker':s.ticker,'direction':s.direction,
                      'entry_price':s.entry_price,'tp_price':s.tp_price,
                      'sl_price':s.sl_price,'score':s.score,'atr':s.atr} for s in signals], indent=2)
    prompt = REVIEW_PROMPT.format(strategy=strategy_name, market=market,
                                  data_source=data_source, signals_json=sj)
    r = subprocess.run(['hermes','chat','-q','-m','minimax','--provider','minimax-cn','-p',prompt],
                       capture_output=True, text=True, timeout=120)
    return r.stdout

def review_and_rank_all():
    """Scan all strategies → review → return best LONGs + SHORTs across all."""
    from framework.signal_db import strategy_stats
    results = {}
    for name, strat in STRATEGIES.items():
        sigs = strat.scan([])
        review = review_signals(sigs, name, strat.market, strat.data_source)
        stats = strategy_stats(name)
        results[name] = {'signals':sigs, 'review':review, 'stats':stats}
    return results
```

---

## 6. Output (Discord / Telegram)

```python
# framework/output.py
import os
import subprocess
import json
from datetime import datetime

# Webhook URL MUST come from environment variable to keep secrets out of git.
# Set DISCORD_WEBHOOK_URL in your shell or .env file:
#   export DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
DISCORD_WEBHOOK = os.environ.get('DISCORD_WEBHOOK_URL', '')

def signal_table(signals):
    h = "| Ticker | Name | Score | Dir | Entry | TP | SL |\n|--------|------|------:|-----|------:|----:|----:|"
    rows = []
    for s in signals:
        emoji = "🟢" if s.direction=="LONG" else "🔴"
        rows.append(f"| {emoji} {s.ticker} | {s.name} | {s.score} | "
                    f"{s.direction} | {s.entry_price} | {s.tp_price} | {s.sl_price} |")
    return h + "\n" + "\n".join(rows)

def post_discord(title, content):
    payload = {"content": f"[framework] **{title}** {datetime.now().strftime('%H:%M')}",
               "embeds": [{"description": content, "color": 0x00ff00 if "LONG" in content else 0xff0000}]}
    subprocess.run(["curl","-s","-X","POST",DISCORD_WEBHOOK,
                    "-H","Content-Type: application/json","-d",json.dumps(payload)],
                   check=False)

def daily_report(signals_by_strategy):
    lines = [f"## [framework] Trading Signals — {datetime.now().strftime('%Y-%m-%d')}\n"]
    for name, data in signals_by_strategy.items():
        s = data['stats']
        lines.append(f"### {name} ({s['trades']} trades, WR {s['win_rate']}%, PF {s['profit_factor']})")
        lines.append(signal_table(data['signals']))
        lines.append(f"```\n{data['review']}\n```\n")
    report = "\n".join(lines)
    post_discord("Daily Signal Report", report)
    return report
```

---

## 7. Adding a New Strategy

### Step 1 — Create file
```
framework/strategies/my_strategy.py
```

### Step 2 — Implement class
```python
from framework.strategy_base import Strategy, Signal, BacktestResult

class MyStrategy(Strategy):
    name = "my-strategy"
    market = "HK"          # or "US"
    data_source = "tencent" # or "futu", "yfinance"

    def default_params(self):
        return {'param_a': 1.0, 'param_b': 0.5}

    def scan(self, tickers, date=None):
        signals = []
        # 1. fetch data via self.data_source
        # 2. apply entry filters
        # 3. generate Signal objects
        return signals

    def backtest(self, tickers, start_date, end_date, params=None):
        if params: self.params = {**self.default_params(), **params}
        results = []
        # loop tickers + days → compute entry/exit → BacktestResult
        return results
```

### Step 3 — Register in backtest_engine.py
```python
from framework.strategies.my_strategy import MyStrategy
STRATEGIES['my-strategy'] = MyStrategy()
```

### Step 4 — Run
```bash
# Scan only
python3 -m framework.backtest_engine --strategy my-strategy --scan --tickers HK.00700,HK.09988

# Param sweep
python3 -m framework.backtest_engine --strategy my-strategy --sweep --tickers HK.00700

# Full: scan → review → Discord
python3 -m framework.backtest_engine --strategy my-strategy --full --tickers HK.00700,HK.09988
```

---

## Directory Structure

```
~/.hermes/skills/trading-strategy-framework/
├── SKILL.md
├── framework/
│   ├── __init__.py
│   ├── strategy_base.py            ← Signal, BacktestResult, Strategy(ABC)
│   ├── datasources/
│   │   ├── futu_opend.py           ← HK: Futu OpenD
│   │   ├── tencent_qt.py           ← HK+US: Tencent qt.gtimg.cn
│   │   └── yfinance_us.py          ← US: yfinance
│   ├── strategies/
│   │   ├── dtat_scalper.py         ← Strategy A
│   │   ├── orb.py                  ← Strategy B
│   │   └── lighthouse_overnight.py ← Strategy C
│   ├── backtest_engine.py          ← scan / sweep / full orchestrator
│   ├── signal_db.py                ← TinyDB CRUD
│   ├── reviewer.py                 ← AI reviewer (MiniMax M3.0)
│   └── output.py                   ← Discord / Telegram
└── config/
    └── param_sweeps.yaml           ← per-strategy sweep grids
```

---

## Key Conventions

| Convention | Rule |
|------------|------|
| Signal direction | `LONG` = buy, `SHORT` = sell |
| Score | 0–100, higher = stronger setup |
| Win | `pnl_pct > 0` |
| Backtest gate | WR ≥ 50% AND PF ≥ 1.5 before going live |
| HK ticker | Futu: `HK.XXXXX` → converted per source |
| US ticker | Plain `AAPL` |
| Output tag | Always prefix: `[framework]` |
| Time format | ISO 8601: `2026-09-07T09:30:00-04:00` |
