"""
Quality-Screen Strategy (from AI Berkshire framework).

A pre-scan filter that applies 7 "去劣" hard metrics to eliminate
non-first-class companies BEFORE running D-TAT / Lighthouse scan.

## 7 Quality Filters
| # | Metric                  | Threshold (Fail)         |
|---|-------------------------|--------------------------|
| 1 | 10Y avg ROE             | < 8%                     |
| 2 | 5Y cumulative FCF       | Negative                 |
| 3 | Interest coverage (EBIT/interest) | < 2x         |
| 4 | Long-term gross margin  | < 15%                    |
| 5 | OCF / Net income (5Y avg)        | < 0.7          |
| 6 | Long-term net margin    | < 5%                     |
| 7 | 5Y share dilution (non-M&A)     | > 20%         |

## 3 Exemptions
- **Exemption A (Strat investment)** — Rule 1 waived if:
  - Listed < 10 years, gross margin > 30%, OCF positive 2 years
- **Exemption B (Strategic low-margin)** — Rule 6 waived if:
  - Gross margin > 30%, net margin recovering to > 5% or rising
- **Exemption C (High-turnover low-margin)** — Rules 4 & 6 waived if:
  - ROE > 20%, OCF/NI > 1.0, business model = subscription/commission/high-turnover

## Data Sources
- Tencent qt.gtimg.cn: realtime PE/PB/ROE/dividend (current snapshot only)
- Annual reports (manual input OR auto-fetch via web search) — full 10Y history

This is a SCAN strategy that produces:
  - Signal direction = 'LONG' or 'SHORT' based on quality (no trading direction)
  - Score = 0-100 quality score
  - metadata = per-rule pass/fail status
"""
from strategy_base import Strategy, Signal, BacktestResult
from typing import List, Dict
import subprocess


class QualityScreenStrategy(Strategy):
    name = "quality-screen"
    market = "HK"  # primarily HK, but works for any market with fundamentals
    data_source = "tencent"

    def default_params(self) -> dict:
        return {
            'roe_threshold': 8.0,           # % 10Y avg
            'fcf_5y_min': 0,                # any negative fails
            'interest_coverage_min': 2.0,   # EBIT/interest
            'gross_margin_min': 15.0,       # %
            'ocf_to_ni_min': 0.7,           # 5Y avg ratio
            'net_margin_min': 5.0,          # %
            'dilution_5y_max': 20.0,        # % share increase
            'roe_exemption_gm': 30.0,       # gross margin for ROE exemption
            'low_margin_exemption_gm': 30.0,
        }

    def scan(self, tickers: List[str], date=None) -> List[Signal]:
        import sys
        signals = []
        for ticker in tickers:
            try:
                sig = self._scan_ticker(ticker)
                if sig:
                    signals.append(sig)
            except Exception as e:
                print(f"[framework] {self.name}: {ticker} scan failed: {e}",
                      file=sys.stderr)
        return signals

    def _scan_ticker(self, ticker: str) -> Signal:
        """
        Quality screen for one ticker.

        NOTE: Most quality metrics require 10Y annual report data.
        Tencent realtime API only provides CURRENT PE/PB/ROE snapshot.
        Full 10Y history requires fetching annual reports.

        For now, we use Tencent realtime fundamentals as a proxy:
        - Current PE-TTM (proxy for valuation)
        - Current PB
        - Current dividend yield
        - Current ROE (Tencent: implied ROE = dividend_yield / payout_ratio, or
          use PB/PB-implied approach)

        Full annual-report integration is a TODO — see quality_screen_full()
        in quality_screen_data.py for the production version.
        """
        from datasources.tencent_qt import fetch_realtime

        quotes = fetch_realtime([ticker])
        if ticker not in quotes:
            return None

        q = quotes[ticker]
        p = self.default_params()

        # Tencent realtime fields (best-effort mapping, partial coverage):
        # - PE-TTM (field 57)
        # - PB (field 59)
        # - Dividend yield (field 50)
        # - Market cap (field 44)
        # - 52W high/low (fields 48/49)
        # Note: ROE, gross/net margin, FCF, share dilution NOT in realtime feed.

        # Mark this as a PARTIAL screen — only 3 of 7 metrics available
        metadata = {
            'screen_type': 'partial_realtime',
            'available_metrics': ['PE-TTM', 'PB', 'dividend_yield'],
            'unavailable_metrics': ['10Y ROE', '5Y FCF', 'interest_coverage',
                                     'gross_margin', 'OCF/NI', 'net_margin',
                                     '5Y share dilution'],
            'data_source_note': 'For full 7-rule screen, integrate annual reports',
        }

        # Simple pass: PE-TTM < 30 AND PB < 5 AND dividend_yield > 1%
        # These are partial proxies for valuation discipline
        pe = q.get('pe_ttm', 0)
        pb = q.get('pb', 0)
        div_yield = q.get('dividend_yield', 0)

        rules = {}
        score = 50  # base

        # PE check — reasonable valuation
        if pe and pe > 0:
            if pe < 30:
                rules['PE-TTM'] = '✅ pass'
                score += 15
            elif pe < 50:
                rules['PE-TTM'] = '⚠️ borderline'
            else:
                rules['PE-TTM'] = '❌ fail (>50)'
                score -= 10
        else:
            rules['PE-TTM'] = '⚪ N/A'

        # PB check — not bubble valuation
        if pb and pb > 0:
            if pb < 3:
                rules['PB'] = '✅ pass (<3)'
                score += 15
            elif pb < 8:
                rules['PB'] = '⚠️ borderline (3-8)'
            else:
                rules['PB'] = '❌ fail (>8)'
                score -= 10
        else:
            rules['PB'] = '⚪ N/A'

        # Dividend — some shareholder return
        if div_yield and div_yield > 0:
            if div_yield > 2:
                rules['Dividend'] = '✅ pass (>2%)'
                score += 20
            elif div_yield > 1:
                rules['Dividend'] = '⚠️ borderline (1-2%)'
                score += 5
            else:
                rules['Dividend'] = '⚪ low (<1%)'
        else:
            rules['Dividend'] = '⚪ no dividend'

        # Cap score
        score = max(0, min(100, score))

        direction = 'LONG' if score >= 50 else 'SHORT'

        # Use price as placeholder TP/SL (filter strategy, not trading)
        price = q.get('price', 0)
        return Signal(
            ticker=ticker,
            name=q.get('name', ticker),
            direction=direction,
            entry_price=price,
            entry_time=str(q.get('timestamp', '')),
            tp_price=round(price * 1.05, 3),  # placeholder
            sl_price=round(price * 0.95, 3),  # placeholder
            atr=0,
            score=score,
            strategy=self.name,
            market=self.market,
            metadata={
                **metadata,
                'rules': rules,
                'pe_ttm': pe,
                'pb': pb,
                'dividend_yield': div_yield,
            },
        )

    def backtest(self, tickers: List[str], start_date: str, end_date: str,
                 params=None) -> List[BacktestResult]:
        """
        Backtest requires annual report history — TODO.
        For now, returns empty.
        """
        return []
