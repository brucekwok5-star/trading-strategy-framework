"""
TinyDB NoSQL store for trading signals and backtest results.
DB: ~/.tjl_signals/signals.json
"""
from tinydb import TinyDB, Query
from pathlib import Path
from functools import reduce
import pandas as pd

DB_PATH = Path("~/.tjl_signals/signals.json").expanduser()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

db = TinyDB(str(DB_PATH))
signals_tbl = db.table('signals')
backtests_tbl = db.table('backtests')
Q = Query()


def insert_signal(sig) -> dict:
    """Store a Signal dataclass in TinyDB."""
    # Build remark from strategy + metadata
    strat = sig.strategy
    meta = sig.metadata or {}
    remark_parts = []
    if strat == 'lighthouse-overnight':
        remark_parts.append(
            f"Day gain {meta.get('day_gain', 0):.1f}% | "
            f"vol_ratio {meta.get('vol_ratio', 0):.1f}x | "
            f"MA20={meta.get('ma20', 0):.2f}"
        )
        remark_parts.append(
            f"TP1={sig.tp_price} TP2={meta.get('tp2')} SL={sig.sl_price}"
        )
    elif strat == 'dtat-scalper':
        remark_parts.append(
            f"15m candle_range={meta.get('candle_range', 0):.2f} | "
            f"ATR={sig.atr:.4f} | RR 2:1"
        )
        remark_parts.append(f"TP={sig.tp_price} SL={sig.sl_price}")
    elif strat == 'orb':
        meta_str = ' | '.join(f"{k}={v}" for k, v in meta.items())
        remark_parts.append(meta_str or 'orb signal')

    now_iso = pd.Timestamp('now').isoformat()
    doc = {
        'ticker': sig.ticker,
        'name': sig.name,
        'direction': sig.direction,
        'entry': round(sig.entry_price, 4),          # absolute price at entry
        'entry_time': sig.entry_time,                 # ISO timestamp
        'tp': round(sig.tp_price, 4),                # take-profit price
        'sl': round(sig.sl_price, 4),                # stop-loss price
        'atr': sig.atr,
        'score': sig.score,
        'strategy': sig.strategy,
        'market': sig.market,
        'metadata': sig.metadata or {},
        'status': 'open',                             # open | closed | cancelled
        'exit': None,                                # exit price when closed
        'exit_time': None,
        'pnl_pct': None,
        'remark': ' | '.join(remark_parts),          # free-text notes
        'created': now_iso,                          # ISO date + timestamp
    }
    signals_tbl.insert(doc)
    return doc


def close_signal(ticker, entry_time, exit_price, exit_time, pnl_pct,
                  remark=None):
    """Mark a signal as closed with P/L. Optionally append remark.

    If remark is provided, fetches the existing remark, appends the new
    remark with timestamp, and saves back. This avoids the
    'remark_append' field typo that was previously a silent no-op.
    """
    update = {
        'status': 'closed',
        'exit': exit_price,
        'exit_time': exit_time,
        'pnl_pct': pnl_pct,
    }

    if remark:
        # Fetch existing remark, append new, save back
        existing = signals_tbl.search(
            (Q.ticker == ticker) & (Q.entry_time == entry_time)
        )
        if existing:
            old_remark = existing[0].get('remark', '')
            new_remark = (old_remark + ' | ' if old_remark else '') + remark
            update['remark'] = new_remark

    signals_tbl.update(
        update,
        (Q.ticker == ticker) & (Q.entry_time == entry_time)
    )


def get_open_signals(strategy=None, market=None):
    """Return all open signals, optionally filtered."""
    conds = [Q.status == 'open']
    if strategy:
        conds.append(Q.strategy == strategy)
    if market:
        conds.append(Q.market == market)
    if len(conds) == 1:
        return signals_tbl.search(conds[0])
    return signals_tbl.search(reduce(lambda a, b: a & b, conds))


def get_all_signals(strategy=None, market=None, limit=500):
    """Return all signals, newest first."""
    conds = []
    if strategy:
        conds.append(Q.strategy == strategy)
    if market:
        conds.append(Q.market == market)
    q = reduce(lambda a, b: a & b, conds) if conds else Q.status.exists()
    return signals_tbl.search(q, limit=limit)


def strategy_stats(strategy, start_date=None, end_date=None) -> dict:
    """
    Aggregate closed-signal stats for a strategy.
    Returns win_rate, avg_pnl, profit_factor, max_dd.
    """
    conds = [Q.status == 'closed', Q.strategy == strategy]
    if start_date:
        conds.append(Q.entry_time >= start_date)
    if end_date:
        conds.append(Q.entry_time <= end_date)
    rows = signals_tbl.search(reduce(lambda a, b: a & b, conds))
    if not rows:
        return {'trades': 0, 'win_rate': 0, 'avg_pnl': 0, 'pf': 0, 'max_dd': 0}

    wins = [r for r in rows if r['pnl_pct'] > 0]
    losses = [r for r in rows if r['pnl_pct'] <= 0]
    wr = len(wins) / len(rows) * 100
    avg_win = sum(r['pnl_pct'] for r in wins) / len(wins) if wins else 0
    avg_loss = abs(sum(r['pnl_pct'] for r in losses) / len(losses)) if losses else 0
    pf = avg_win / avg_loss if avg_loss else float('inf')
    return {
        'strategy': strategy,
        'trades': len(rows),
        'win_rate': round(wr, 1),
        'avg_pnl': round(sum(r['pnl_pct'] for r in rows) / len(rows), 3),
        'profit_factor': round(pf, 2),
        'max_dd': round(min(r['pnl_pct'] for r in rows), 2),
    }


def record_backtest(strategy, params, results_summary):
    """Store backtest run metadata."""
    backtests_tbl.insert({
        'strategy': strategy,
        'params': params,
        'summary': results_summary,
        'run_at': pd.Timestamp('now').isoformat(),
    })
