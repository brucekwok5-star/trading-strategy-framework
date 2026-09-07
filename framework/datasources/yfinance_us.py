"""
yfinance data source for US stocks.
"""
import yfinance as yf
import pandas as pd


def fetch(tickers, start_date=None, end_date=None, interval="1d"):
    """
    Fetch US stock data via yfinance.

    Parameters
    ----------
    tickers : str or list of str
    start_date, end_date : str (YYYY-MM-DD) or None
    interval : str
        '1m'|'2m'|'5m'|'15m'|'30m'|'1h'|'2h'|'4h'|'1d'|'5d'|'1wk'|'1mo'|'3mo'

    Returns
    -------
    yfinance DataFrame or dict of DataFrames (for multiple tickers)
    """
    if isinstance(tickers, str):
        tickers = [tickers]
    data = yf.download(
        tickers,
        start=start_date,
        end=end_date,
        interval=interval,
        auto_adjust=True,
        progress=False,
        group_by='ticker' if len(tickers) > 1 else 'column',
    )
    return data


def fetch_single(ticker, start_date=None, end_date=None, interval="1d") -> pd.DataFrame:
    """Fetch a single ticker's data, returned as a clean DataFrame."""
    if isinstance(ticker, list):
        ticker = ticker[0]
    df = yf.download(
        ticker,
        start=start_date,
        end=end_date,
        interval=interval,
        auto_adjust=True,
        progress=False,
    )
    return df


def latest_price(tickers):
    """Return latest price dict for tickers."""
    if isinstance(tickers, str):
        tickers = [tickers]
    prices = {}
    for t in tickers:
        tk = yf.Ticker(t)
        info = tk.fast_info
        prices[t] = {
            'price': info.get('last_price') or info.get('market_price'),
            'prev_close': info.get('previous_close'),
            'open': info.get('open'),
            'volume': info.get('last_volume'),
        }
    return prices
