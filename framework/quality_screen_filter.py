"""
Quality screen filter — runs quality-screen strategy and returns
list of tickers that pass the minimum score threshold.

Used as Stage 1 in a two-stage filter pipeline (quality-screen →
trading strategy).
"""
from typing import List
from strategies.quality_screen import QualityScreenStrategy
from output import signal_table


def screen_filter(tickers: List[str], min_score: float = 50.0) -> List[str]:
    """
    Run quality-screen on tickers, return tickers that pass (score >= min_score).
    """
    strat = QualityScreenStrategy()
    signals = strat.scan(tickers)

    passed = []
    failed = []
    for s in signals:
        if s.score >= min_score:
            passed.append(s.ticker)
        else:
            failed.append(s.ticker)

    print(f"[quality-screen] {len(passed)} passed / {len(failed)} failed (min_score={min_score})")
    print(f"\n=== Passed ({len(passed)}) ===")
    if passed:
        from datasources.tencent_qt import fetch_realtime
        qmap = fetch_realtime(passed)
        for ticker in passed:
            if ticker in qmap:
                q = qmap[ticker]
                pe = q.get('pe_ttm', 0)
                pb = q.get('pb', 0)
                div = q.get('dividend_yield', 0)
                print(f"  ✅ {ticker} {q.get('name','')} | PE={pe:.1f} PB={pb:.1f} div={div:.1f}%")
            else:
                print(f"  ✅ {ticker}")

    if failed:
        print(f"\n=== Failed (excluded) ===")
        from datasources.tencent_qt import fetch_realtime
        qmap = fetch_realtime(failed)
        for ticker in failed:
            if ticker in qmap:
                q = qmap[ticker]
                pe = q.get('pe_ttm', 0)
                pb = q.get('pb', 0)
                print(f"  ❌ {ticker} {q.get('name','')} | PE={pe:.1f} PB={pb:.1f}")
            else:
                print(f"  ❌ {ticker}")

    return passed
