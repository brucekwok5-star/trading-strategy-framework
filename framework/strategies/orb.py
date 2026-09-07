"""
Opening Range Breakout (ORB) Strategy.

Logic:
  1. Define N-minute opening range (default: 30 min)
  2. LONG: price breaks above range_high + breakout_pct
  3. SHORT: price breaks below range_low - breakout_pct
  4. TP: entry ± ATR × atr_multiplier
  5. SL: entry ∓ ATR × sl_multiplier
"""
import sys
from strategy_base import Strategy, Signal, BacktestResult
import yfinance as yf
import pandas as pd
from typing import List


class ORBStrategy(Strategy):
    name = "orb"
    market = "US"
    data_source = "yfinance"

    def default_params(self) -> dict:
        return {
            'orb_minutes': 30,      # opening range window in minutes
            'breakout_pct': 0.0,    # additional % beyond range for confirmation
            'atr_multiplier': 2.0,  # TP = entry ± ATR × this
            'sl_multiplier': 1.0,   # SL = entry ∓ ATR × this
            'atr_period': 14,
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
        p = self.default_params()

        # Fetch 5-min bars for today
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

        if isinstance(df_5m.columns, pd.MultiIndex):
            df_5m.columns = df_5m.columns.get_level_values(0)
        if isinstance(df_d.columns, pd.MultiIndex):
            df_d.columns = df_d.columns.get_level_values(0)

        # ATR
        atr = float(df_d['Close'].diff().abs().rolling(p['atr_period']).mean().iloc[-1])
        if atr == 0:
            return None

        # Build N-min opening range from first N minutes of today
        first_n = df_5m.iloc[:p['orb_minutes'] // 5]  # 5-min bars
        if len(first_n) < 2:
            return None

        orb_high = first_n['High'].max()
        orb_low = first_n['Low'].min()
        orb_range = orb_high - orb_low

        # Get latest price
        latest = df_5m.iloc[-1]
        latest_close = latest['Close']
        latest_time = latest.name

        # Check breakout
        breakout_long  = latest_close > orb_high * (1 + p['breakout_pct'])
        breakout_short = latest_close < orb_low  * (1 - p['breakout_pct'])

        if not (breakout_long or breakout_short):
            return None

        if breakout_long:
            direction = 'LONG'
            entry = orb_high * (1 + p['breakout_pct'])
            tp = entry + p['atr_multiplier'] * atr
            sl = entry - p['sl_multiplier'] * atr
        else:
            direction = 'SHORT'
            entry = orb_low * (1 - p['breakout_pct'])
            tp = entry - p['atr_multiplier'] * atr
            sl = entry + p['sl_multiplier'] * atr

        # Score based on how far beyond range
        if direction == 'LONG':
            score = min(100, ((latest_close - orb_high) / orb_high) * 500)
        else:
            score = min(100, ((orb_low - latest_close) / orb_low) * 500)

        return Signal(
            ticker=ticker,
            name=ticker,
            direction=direction,
            entry_price=round(entry, 2),
            entry_time=str(latest_time),
            tp_price=round(tp, 2),
            sl_price=round(sl, 2),
            atr=round(atr, 4),
            score=round(score, 1),
            strategy=self.name,
            market=self.market,
            metadata={'orb_high': orb_high, 'orb_low': orb_low},
        )

    def backtest(self, tickers: List[str], start_date: str, end_date: str,
                 params=None) -> List[BacktestResult]:
        """
        Backtest ORB strategy.

        For each day, simulate:
        - Use first 30 min range (proxy: day high/low first 30% range as approximation)
        - Breakout: next bar > range_high → LONG, < range_low → SHORT
        - TP/SL based on ATR × multipliers
        """
        import yfinance as yf
        merged = {**self.default_params(), **(params or {})}
        results = []

        for ticker in tickers:
            try:
                df = yf.download(
                    ticker, start=start_date, end=end_date,
                    interval='1d', auto_adjust=True, progress=False
                )
                if df.empty or len(df) < 30:
                    continue
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

                atr_period = merged['atr_period']
                atr_series = df['Close'].diff().abs().rolling(atr_period).mean()

                for i in range(atr_period + 1, len(df) - 1):
                    row = df.iloc[i]
                    next_row = df.iloc[i + 1]
                    atr = atr_series.iloc[i]
                    if pd.isna(atr) or atr == 0:
                        continue

                    # Approximate ORB from daily: use first 30% of day range as "ORB"
                    # Real implementation needs intraday 5-min data
                    day_range = row['High'] - row['Low']
                    if day_range == 0:
                        continue
                    orb_high = row['Open'] + day_range * 0.15
                    orb_low = row['Open'] - day_range * 0.15

                    # Did next day break out?
                    next_open = float(next_row['Open'])
                    if next_open > orb_high * (1 + merged['breakout_pct']):
                        direction = 'LONG'
                        entry_px = orb_high * (1 + merged['breakout_pct'])
                        tp_px = entry_px + merged['atr_multiplier'] * atr
                        sl_px = entry_px - merged['sl_multiplier'] * atr
                    elif next_open < orb_low * (1 - merged['breakout_pct']):
                        direction = 'SHORT'
                        entry_px = orb_low * (1 - merged['breakout_pct'])
                        tp_px = entry_px - merged['atr_multiplier'] * atr
                        sl_px = entry_px + merged['sl_multiplier'] * atr
                    else:
                        continue  # no breakout

                    # Exit next day close
                    exit_px = float(next_row['Close'])
                    if direction == 'LONG':
                        # Check if SL hit intraday
                        if float(next_row['Low']) <= sl_px:
                            exit_px = sl_px
                        elif float(next_row['High']) >= tp_px:
                            exit_px = tp_px
                        pnl_pct = (exit_px - entry_px) / entry_px * 100
                    else:
                        if float(next_row['High']) >= sl_px:
                            exit_px = sl_px
                        elif float(next_row['Low']) <= tp_px:
                            exit_px = tp_px
                        pnl_pct = (entry_px - exit_px) / entry_px * 100

                    results.append(BacktestResult(
                        ticker=ticker,
                        entry_time=str(row.name),
                        exit_time=str(next_row.name),
                        direction=direction,
                        entry_price=round(entry_px, 4),
                        exit_price=round(exit_px, 4),
                        pnl_pct=round(pnl_pct, 4),
                        win=pnl_pct > 0,
                        params=merged,
                    ))
            except Exception as e:
                print(f"[framework] {self.name}: {ticker} backtest failed: {e}",
                      file=sys.stderr)
        return results
