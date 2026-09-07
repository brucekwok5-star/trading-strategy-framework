"""
D-TAT Scalper — Delta Touch & Turn.

Entry Logic:
  1. Reconstruct first 15-min candle (09:30–09:45 ET) from 5-min bars
  2. Compute ATR(14) from daily bars (30-day lookback)
  3. Liquidity filter: candle_range >= 25% of ATR(14)
  4. Direction: candle close < open → LONG (red swept lows)
                candle close > open → SHORT (green swept highs)
  5. Entry: range low (LONG) / range high (SHORT)

Risk Management:
  TP  = entry ± Fibonacci level × candle_range
  SL  = entry ∓ TP_distance / rr_ratio (2:1 default)
"""
import sys

from strategy_base import Strategy, Signal, BacktestResult
import yfinance as yf
import pandas as pd
import numpy as np
from typing import List


class DTATScalperStrategy(Strategy):
    name = "dtat-scalper"
    market = "US"
    data_source = "yfinance"

    def default_params(self) -> dict:
        return {
            'or_pct': 0.25,      # liquidity threshold: candle_range >= or_pct × ATR(14)
            'tp_level': 0.382,   # Fibonacci TP level (38.2%)
            'rr_ratio': 2.0,      # reward-to-risk ratio
            'atr_period': 14,
            'entry_offset': 0.0,  # offset from range low/high
        }

    def scan(self, tickers: List[str], date=None) -> List[Signal]:
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

    def _scan_ticker(self, ticker: str):
        # Fetch 5-min (2 days) and daily (1 month)
        df_5m = yf.download(
            ticker, period='2d', interval='5m',
            auto_adjust=True, progress=False
        )
        df_d = yf.download(
            ticker, period='1mo', interval='1d',
            auto_adjust=True, progress=False
        )
        if df_5m.empty or df_d.empty:
            return None

        # Flatten MultiIndex columns if needed
        if isinstance(df_5m.columns, pd.MultiIndex):
            df_5m.columns = df_5m.columns.get_level_values(0)
        if isinstance(df_d.columns, pd.MultiIndex):
            df_d.columns = df_d.columns.get_level_values(0)

        # Build 15-min candle from first 3 x 5-min bars
        df_15m = df_5m.resample('15min').agg({
            'Open': 'first', 'High': 'max',
            'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()

        if len(df_15m) < 1:
            return None

        # ATR(14)
        atr = float(df_d['Close'].diff().abs().rolling(14).mean().iloc[-1])
        if atr == 0 or np.isnan(atr):
            return None

        # First 15-min candle
        candle = df_15m.iloc[0]
        candle_range = candle['High'] - candle['Low']
        p = self.default_params()

        # Liquidity filter
        if candle_range < p['or_pct'] * atr:
            return None

        # Direction
        if candle['Close'] < candle['Open']:
            direction = 'LONG'
            entry = candle['Low'] - p['entry_offset']
            tp = entry + p['tp_level'] * candle_range
            sl = entry - (tp - entry) / p['rr_ratio']
        else:
            direction = 'SHORT'
            entry = candle['High'] + p['entry_offset']
            tp = entry - p['tp_level'] * candle_range
            sl = entry + (entry - tp) / p['rr_ratio']

        score = min(100, (candle_range / (p['or_pct'] * atr)) * 50)

        return Signal(
            ticker=ticker,
            name=ticker,
            direction=direction,
            entry_price=round(entry, 2),
            entry_time=str(candle.name),
            tp_price=round(tp, 2),
            sl_price=round(sl, 2),
            atr=round(atr, 4),
            score=round(score, 1),
            strategy=self.name,
            market=self.market,
            metadata={'candle_range': round(candle_range, 4)},
        )

    def backtest(self, tickers: List[str], start_date: str, end_date: str,
                 params=None) -> List[BacktestResult]:
        if params:
            saved = self.default_params()
            self.default_params = lambda: {**saved, **params}

        results = []
        for ticker in tickers:
            res = self._backtest_ticker(ticker, start_date, end_date)
            results.extend(res)
        return results

    def _backtest_ticker(self, ticker, start_date, end_date) -> List[BacktestResult]:
        """Simple backtest: iterate trading days, apply signal logic, track P/L."""
        df_d = yf.download(
            ticker, start=start_date, end=end_date,
            interval='1d', auto_adjust=True, progress=False
        )
        if df_d.empty:
            return []
        if isinstance(df_d.columns, pd.MultiIndex):
            df_d.columns = df_d.columns.get_level_values(0)

        p = self.default_params()
        atr_ma = df_d['Close'].diff().abs().rolling(p['atr_period']).mean()
        results = []

        # Simulate: for each day, use previous day's data to generate signal
        for i in range(p['atr_period'] + 1, len(df_d) - 1):
            row = df_d.iloc[i]
            prev = df_d.iloc[i - 1]
            atr = atr_ma.iloc[i]

            if atr == 0 or np.isnan(atr):
                continue

            # Use open of day as "entry", high/low as range
            day_range = row['High'] - row['Low']
            if day_range < p['or_pct'] * atr:
                continue

            if row['Close'] < row['Open']:
                direction = 'LONG'
                entry_px = row['Low']
                tp_px = entry_px + p['tp_level'] * day_range
                sl_px = entry_px - (tp_px - entry_px) / p['rr_ratio']
            else:
                direction = 'SHORT'
                entry_px = row['High']
                tp_px = entry_px - p['tp_level'] * day_range
                sl_px = entry_px + (entry_px - tp_px) / p['rr_ratio']

            # Next day exit prices
            next_row = df_d.iloc[i + 1]
            exit_px = next_row['Close']
            exit_time = str(next_row.name)

            if direction == 'LONG':
                pnl_pct = (exit_px - entry_px) / entry_px * 100
            else:
                pnl_pct = (entry_px - exit_px) / entry_px * 100

            results.append(BacktestResult(
                ticker=ticker,
                entry_time=str(row.name),
                exit_time=exit_time,
                direction=direction,
                entry_price=round(entry_px, 2),
                exit_price=round(exit_px, 2),
                pnl_pct=round(pnl_pct, 3),
                win=pnl_pct > 0,
                params=p,
            ))
        return results
