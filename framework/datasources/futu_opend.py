"""
Futu OpenD data source for HK stocks.
Start OpenD first: cd ~/.hermes/bin && ./FutuOpenD &
"""
import sys
import os

# Try to import futu API; if not installed, provide stubs
try:
    from futu import OpenQuoteContext
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False

FUTU_HOST = "127.0.0.1"
FUTU_PORT = 11111

KTYPE_MAP = {
    "1m": "K_1M",
    "5m": "K_5M",
    "15m": "K_15M",
    "30m": "K_30M",
    "1h": "K_1H",
    "1d": "K_Day",
}


def fetch(tickers, start_date=None, end_date=None, interval="1d"):
    """
    Fetch historical K-line data for HK tickers via Futu OpenD.

    Parameters
    ----------
    tickers : list of str
        Futu-style codes e.g. ['HK.00700', 'HK.09988']
    start_date, end_date : str
        YYYY-MM-DD
    interval : str
        '1m' | '5m' | '15m' | '30m' | '1h' | '1d'

    Returns
    -------
    dict mapping ticker -> DataFrame with columns:
        timestamp, open, high, low, close, volume
    """
    if not FUTU_AVAILABLE:
        raise ImportError("futu API not installed: pip install futu-api")

    results = {}
    ktype = KTYPE_MAP.get(interval, "K_Day")

    with OpenQuoteContext(FUTU_HOST, FUTU_PORT) as ctx:
        for ticker in tickers:
            ret, data = ctx.request_history_kline(
                code=ticker,
                start=start_date,
                end=end_date,
                ktype=ktype,
            )
            if ret == 0 and data is not None and not data.empty:
                # Normalize columns
                data = data.rename(columns={
                    'time_key': 'timestamp',
                    'open': 'open',
                    'high': 'high',
                    'low': 'low',
                    'close': 'close',
                    'volume': 'volume',
                })
                results[ticker] = data
    return results


def fetch_realtime(tickers):
    """Fetch real-time quotes for HK tickers via Futu OpenD."""
    if not FUTU_AVAILABLE:
        raise ImportError("futu API not installed")

    results = {}
    with OpenQuoteContext(FUTU_HOST, FUTU_PORT) as ctx:
        for ticker in tickers:
            ret, data = ctx.get_stock_quote([ticker])
            if ret == 0 and data is not None and not data.empty:
                results[ticker] = data
    return results


def convert_futu_code(ticker: str) -> str:
    """
    Convert various ticker formats to Futu HK code.
    '700' -> 'HK.00700'
    '00700' -> 'HK.00700'
    'AAPL' -> 'US.AAPL'
    """
    t = ticker.strip()
    if t.startswith('HK.') or t.startswith('US.'):
        return t
    if t.isdigit():
        if len(t) == 5:
            return f"HK.{t}"
        elif len(t) == 6:
            # 6-digit HK stock code (with market prefix)
            return f"HK.{t}"
    return t  # assume already Futu format
