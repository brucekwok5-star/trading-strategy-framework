#!/usr/bin/python3
"""
Two-stage filter pipeline:
  Stage 1: quality-screen → filter out non-first-class stocks
  Stage 2: dtat-scalper / lighthouse-overnight → trading signals on remaining

Usage:
  /usr/bin/python3 filter_pipeline.py --screen-then-scan --tickers 00700,09988,...
  /usr/bin/python3 filter_pipeline.py --strategy lighthouse-overnight --tickers 00700,...
"""
import os, sys
os.environ.pop('PYTHONPATH', None); os.environ.pop('PYTHONHOME', None)
sys.path = [p for p in sys.path if '/hermes-agent/' not in p]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest_engine import STRATEGIES, insert_signal
from quality_screen_filter import screen_filter

import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tickers', required=True)
    parser.add_argument('--strategy', default='lighthouse-overnight',
                        choices=['dtat-scalper', 'orb', 'lighthouse-overnight'])
    parser.add_argument('--screen-min-score', type=float, default=50.0,
                        help='Min quality-screen score to pass filter')
    parser.add_argument('--screen-only', action='store_true',
                        help='Run only quality-screen, skip trading scan')
    args = parser.parse_args()

    tickers = [t.strip() for t in args.tickers.split(',') if t.strip()]
    print(f"[filter_pipeline] {len(tickers)} tickers input")
    print(f"[filter_pipeline] Strategy: {args.strategy}")
    print(f"[filter_pipeline] Min score: {args.screen_min_score}\n")

    # Stage 1: quality-screen filter
    screened = screen_filter(tickers, min_score=args.screen_min_score)

    if args.screen_only:
        print("\n[filter_pipeline] --screen-only: skipping trading scan")
        return

    # Stage 2: trading strategy scan
    print(f"\n[filter_pipeline] Stage 2: {args.strategy} scan on {len(screened)} surviving tickers...")
    if not screened:
        print("[filter_pipeline] No tickers survived screen — aborting")
        return

    strat = STRATEGIES[args.strategy]
    signals = strat.scan(screened)

    # Persist
    for sig in signals:
        insert_signal(sig)

    print(f"\n[filter_pipeline] {len(signals)} signals from {args.strategy}:")
    for s in signals:
        print(f"  {s.direction} {s.ticker} @ {s.entry_price} TP={s.tp_price} SL={s.sl_price} score={s.score}")


if __name__ == '__main__':
    main()
