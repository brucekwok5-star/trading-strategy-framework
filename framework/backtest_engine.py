#!/usr/bin/python3
"""
Backtest Engine — scan + param sweep orchestrator for the trading strategy framework.

Usage:
  /usr/bin/python3 backtest_engine.py --strategy dtat-scalper --scan --tickers AAPL,META,NVDA
  /usr/bin/python3 backtest_engine.py --strategy dtat-scalper --sweep --tickers AAPL,META,NVDA
  /usr/bin/python3 backtest_engine.py --strategy dtat-scalper --full --tickers AAPL,META,NVDA
  /usr/bin/python3 backtest_engine.py --strategy dtat-scalper --stats --days 30
"""
import os, sys
# Unset broken PYTHONPATH that injects hermes venv (python3.11) into system python3.9
os.environ.pop('PYTHONPATH', None)
os.environ.pop('PYTHONHOME', None)
# Also strip venv paths from sys.path (they persist even after unsetting env)
_venv = '/.hermes/hermes-agent/'
sys.path = [p for p in sys.path if _venv not in p]

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.dtat_scalper import DTATScalperStrategy
from strategies.orb import ORBStrategy
from strategies.lighthouse_overnight import LighthouseOvernightStrategy
from strategies.quality_screen import QualityScreenStrategy
from signal_db import insert_signal, strategy_stats
from reviewer import review_signals
from output import daily_report


STRATEGIES = {
    'dtat-scalper': DTATScalperStrategy(),
    'orb': ORBStrategy(),
    'lighthouse-overnight': LighthouseOvernightStrategy(),
    'quality-screen': QualityScreenStrategy(),
}


def scan(strategy_name, tickers, date=None):
    """Run live scan and store signals in TinyDB."""
    if strategy_name not in STRATEGIES:
        print(f"[framework] Unknown strategy: {strategy_name}")
        return []
    strat = STRATEGIES[strategy_name]
    signals = strat.scan(tickers, date)
    for sig in signals:
        insert_signal(sig)
    return signals


def sweep(strategy_name, tickers, start_date, end_date, param_grid):
    """Run param sweep and print ranked results."""
    if strategy_name not in STRATEGIES:
        print(f"[framework] Unknown strategy: {strategy_name}")
        return
    strat = STRATEGIES[strategy_name]
    df = strat.param_sweep(tickers, start_date, end_date, param_grid)
    print(f"\n[framework] {strategy_name} param sweep results:")
    print(df.to_string(index=False))
    return df


def full_pipeline(strategy_name, tickers):
    """Scan → review → post Discord."""
    if strategy_name not in STRATEGIES:
        print(f"[framework] Unknown strategy: {strategy_name}")
        return
    strat = STRATEGIES[strategy_name]

    # Scan
    signals = scan(strategy_name, tickers)
    print(f"[framework] {strategy_name}: {len(signals)} signals generated")

    if not signals:
        print("[framework] No signals — skipping review")
        return

    # Review
    print(f"[framework] Reviewing {len(signals)} signals with MiniMax M3.0...")
    review = review_signals(signals, strategy_name, strat.market, strat.data_source)
    print(f"\n[framework] Review:\n{review}")

    # Stats
    stats = strategy_stats(strategy_name)
    print(f"\n[framework] Historical stats: {stats}")

    # Post Discord
    data = {strategy_name: {'signals': signals, 'review': review, 'stats': stats}}
    report = daily_report(data)
    print(f"\n[framework] Report posted to Discord")


def show_stats(strategy_name, days=30):
    """Print historical stats for a strategy."""
    from datetime import datetime, timedelta
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    stats = strategy_stats(strategy_name, start_date, end_date)
    print(f"\n[framework] {strategy_name} stats ({days}d):")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return stats


def run_framework_with_charts_and_social(strategy_name, tickers,
                                          open_charts=True, do_social=True):
    """
    Full pipeline (Steps 1 → 3.5):
      1. Scan → insert to TinyDB
      2. AI Review (MiniMax M3.0)
      3. Stats aggregation
      3.4. Build TradingView chart links + open Chrome tabs
      3.5. Social sentiment scan (Futu + Xueqiu) on signal tickers
      4. Discord post (consolidated)
    """
    strat = STRATEGIES[strategy_name]

    # === Step 1: Scan ===
    print(f"[framework] Step 1: Scan {strategy_name} on {len(tickers)} tickers...")
    signals = scan(strategy_name, tickers)
    print(f"  → {len(signals)} signals")

    if not signals:
        print("[framework] No signals — aborting pipeline")
        return

    # === Step 2: AI Review ===
    print(f"\n[framework] Step 2: AI Review...")
    review = review_signals(signals, strategy_name, strat.market, strat.data_source)

    # === Step 3: Stats ===
    stats = strategy_stats(strategy_name)

    # === Step 3.4: TradingView charts ===
    tv_table = ""
    if open_charts:
        from chart_links import build_tv_links, open_chrome_tabs
        signal_tickers = list({s.ticker for s in signals})  # dedupe
        print(f"\n[framework] Step 3.4: TradingView links for {len(signal_tickers)} tickers...")
        tv_table = build_tv_links(signal_tickers, interval='5')
        print(tv_table)
        print(f"\n[framework] Opening Chrome tabs...")
        open_chrome_tabs(signal_tickers, interval='5')

    # === Step 3.5: Social sentiment scan ===
    social = None
    if do_social:
        from social_scan import scan_signal_stocks_social
        signal_tickers = list({s.ticker for s in signals})
        print(f"\n[framework] Step 3.5: Social scan (Futu + Xueqiu) for {len(signal_tickers)} tickers...")
        social = scan_signal_stocks_social(signal_tickers)
        print(social.get('summary', ''))

    # === Step 4: Discord post ===
    data = {
        strategy_name: {
            'signals': signals,
            'review': review,
            'stats': stats,
            'tv_table': tv_table,
            'social': social,
        }
    }
    daily_report(data)
    print(f"\n[framework] Full pipeline complete — Discord post sent")


if __name__ == '__main__':
    import argparse
    import json

    parser = argparse.ArgumentParser(description='[framework] Trading Strategy Engine')
    parser.add_argument('--strategy', required=True,
                        choices=list(STRATEGIES.keys()),
                        help='Strategy to run')
    parser.add_argument('--scan', action='store_true', help='Run live scan, store in TinyDB')
    parser.add_argument('--sweep', action='store_true', help='Run parameter sweep')
    parser.add_argument('--full', action='store_true',
                        help='Scan → review → post Discord (use --with-charts/--with-social for full)')
    parser.add_argument('--with-charts', action='store_true',
                        help='Step 3.4: generate TradingView links + open Chrome tabs')
    parser.add_argument('--with-social', action='store_true',
                        help='Step 3.5: scan Futu + Xueqiu for signal tickers')
    parser.add_argument('--charts-only', action='store_true',
                        help='Just generate TradingView links (no scan)')
    parser.add_argument('--stats', action='store_true', help='Show historical stats')
    parser.add_argument('--tickers', default='', help='Comma-separated ticker list')
    parser.add_argument('--start-date', default='2026-01-01')
    parser.add_argument('--end-date', default='2026-09-01')
    parser.add_argument('--days', type=int, default=30, help='Days for stats query')
    parser.add_argument('--interval', default='5',
                        help='TV chart interval: 5|15|60|D (default 5m)')

    args = parser.parse_args()
    tickers = [t.strip() for t in args.tickers.split(',') if t.strip()]

    # Default pools
    if not tickers:
        if STRATEGIES[args.strategy].market == 'US':
            tickers = ['AAPL', 'META', 'NVDA', 'TSLA', 'AMZN']
        else:
            tickers = ['00700', '09988', '01810']

    # Default param sweep grid
    param_grid = {
        'tp_level': [0.236, 0.382, 0.5],
        'rr_ratio': [1.5, 2.0, 2.5],
    }

    if args.scan:
        sigs = scan(args.strategy, tickers)
        print(f"[framework] {args.strategy}: {len(sigs)} signals")
        for s in sigs:
            print(f"  {s.direction} {s.ticker} @ {s.entry_price} "
                  f"TP={s.tp_price} SL={s.sl_price} score={s.score}")

    elif args.sweep:
        sweep(args.strategy, tickers, args.start_date, args.end_date, param_grid)

    elif args.charts_only:
        from chart_links import build_tv_links, open_chrome_tabs
        print(build_tv_links(tickers, interval=args.interval))
        open_chrome_tabs(tickers, interval=args.interval)

    elif args.full:
        if args.with_charts or args.with_social:
            run_framework_with_charts_and_social(
                args.strategy, tickers,
                open_charts=args.with_charts,
                do_social=args.with_social,
            )
        else:
            full_pipeline(args.strategy, tickers)

    elif args.stats:
        show_stats(args.strategy, args.days)

    else:
        parser.print_help()
