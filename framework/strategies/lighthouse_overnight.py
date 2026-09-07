"""
灯塔 Lighthouse Overnight Strategy (HK + US via Tencent qt.gtimg.cn).

Logic:
  - Entry: buy at last 30-min close of the day
  - Hold: overnight
  - Exit:  +2.5% → half / +4% → full / -2% → hard stop / 09:45 time stop / gap-down >2%

Filters:
  - Day gain vs yesterday daily close >= gain_threshold
  - Volume surge >= vol_ratio_min
  - Close > MA20

HK market via Tencent API (yfinance often returns empty for HK).
"""
from strategy_base import Strategy, Signal, BacktestResult
import pandas as pd
import numpy as np
from typing import List


class LighthouseOvernightStrategy(Strategy):
    name = "lighthouse-overnight"
    market = "HK"
    data_source = "tencent"  # use Tencent for HK (yfinance unreliable)

    def default_params(self) -> dict:
        return {
            'gain_threshold': 3.0,   # % gain in last hour to qualify
            'vol_ratio_min': 1.5,   # volume surge minimum
            'ma_period': 20,
            'tp1_pct': 3.0,         # partial exit %  ← was 2.5
            'tp2_pct': 5.0,         # full exit %    ← was 4.0
            'sl_pct': 2.0,          # hard stop %
            'time_exit': '09:45',
        }

    def scan(self, tickers: List[str], date=None) -> List[Signal]:
        signals = []
        for ticker in tickers:
            try:
                sig = self._scan_ticker(ticker)
                if sig:
                    signals.append(sig)
            except Exception:
                continue
        return signals

    def _scan_ticker(self, ticker: str):
        from datasources.tencent_qt import fetch_daily, fetch_intraday

        p = self.default_params()

        # Fetch daily bars (Tencent)
        daily_map = fetch_daily([ticker], days=max(60, p['ma_period'] + 5))
        if ticker not in daily_map or len(daily_map[ticker]) < p['ma_period'] + 2:
            return None
        df_d = daily_map[ticker]
        # Normalize columns to Title case
        df_d.columns = [c.capitalize() if c.lower() in ['open','high','low','close','volume'] else c for c in df_d.columns]

        # Yesterday's close
        yest_close = float(df_d['Close'].iloc[-2])
        today_close = float(df_d['Close'].iloc[-1])
        day_gain = (today_close - yest_close) / yest_close * 100

        # MA20
        ma20 = float(df_d['Close'].rolling(p['ma_period']).mean().iloc[-1])
        if today_close <= ma20:
            return None

        # Gain filter
        if day_gain < p['gain_threshold']:
            return None

        # Vol ratio: today's vol vs avg(last 5d) vol
        vol_today = float(df_d['Volume'].iloc[-1])
        vol_avg5 = float(df_d['Volume'].iloc[-6:-1].mean())
        vol_ratio = vol_today / vol_avg5 if vol_avg5 > 0 else 0

        if vol_ratio < p['vol_ratio_min']:
            return None

        # ATR(14)
        atr = float(df_d['Close'].diff().abs().rolling(14).mean().iloc[-1])
        if atr == 0:
            return None

        # Entry = today's close (we'd enter at tomorrow's open in backtest)
        entry_price = today_close
        tp1 = entry_price * (1 + p['tp1_pct'] / 100)
        tp2 = entry_price * (1 + p['tp2_pct'] / 100)
        sl = entry_price * (1 - p['sl_pct'] / 100)

        # Get ticker name
        name = self._get_name(ticker)

        score = min(100, day_gain * 5 + vol_ratio * 15)

        return Signal(
            ticker=ticker,
            name=name,
            direction='LONG',
            entry_price=round(entry_price, 3),
            entry_time=str(df_d.index[-1]),
            tp_price=round(tp1, 3),
            sl_price=round(sl, 3),
            atr=round(atr, 4),
            score=round(score, 1),
            strategy=self.name,
            market=self.market,
            metadata={
                'day_gain': round(day_gain, 2),
                'vol_ratio': round(vol_ratio, 2),
                'ma20': round(ma20, 3),
                'tp2': round(tp2, 3),
            },
        )

    def _get_name(self, ticker: str) -> str:
        """Get ticker name from realtime quote."""
        try:
            from datasources.tencent_qt import lookup_names
            names = lookup_names([ticker])
            return names.get(ticker, ticker)
        except Exception:
            return ticker

    def backtest(self, tickers: List[str], start_date: str, end_date: str,
                 params=None) -> List[BacktestResult]:
        # Not implemented yet — placeholder
        return []
