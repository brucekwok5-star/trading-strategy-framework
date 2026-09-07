"""
TradingView chart link builder + Chrome tab opener.

Wraps the tradingview-multi-ticker-tabs skill:
  - HK stocks: HKEX:XXXX (strip leading zeros)
  - US stocks: just the ticker (NASDAQ:AAPL, NYSE:TSLA)
  - Interval: 5=5m, 15=15m, 60=1h, D=daily
"""
import subprocess
import re
from typing import List


def to_tv_symbol(ticker: str) -> str:
    """
    Convert framework ticker to TradingView symbol.

    Examples:
      '00700' -> 'HKEX:700'
      '09988' -> 'HKEX:9988'
      'AAPL'  -> 'NASDAQ:AAPL' (heuristic — most US stocks are NASDAQ or NYSE)
      'BRK.B' -> 'NYSE:BRK.B'
    """
    t = ticker.strip()
    # Already formatted?
    if ':' in t:
        return t
    # HK: 5-digit zero-padded
    if t.isdigit():
        # TradingView drops leading zeros for HK
        return f"HKEX:{int(t)}"
    # US tickers — try common exchanges
    t_upper = t.upper()
    # .B class shares like BRK.B
    return t_upper  # default: TV will auto-detect exchange


def build_tv_links(tickers: List[str], interval: str = '5') -> str:
    """
    Build a markdown table of TradingView chart links.

    Parameters
    ----------
    tickers : list of str
        Mixed HK 5-digit or US tickers
    interval : str
        '5' = 5m, '15' = 15m, '60' = 1h, 'D' = daily

    Returns
    -------
    markdown table string
    """
    rows = ["| # | Stock | TradingView Link |",
            "|---|-------|------------------|"]
    for i, t in enumerate(tickers, 1):
        sym = to_tv_symbol(t)
        url = f"https://www.tradingview.com/chart/?symbol={sym}&interval={interval}"
        rows.append(f"| {i} | {t} | [TV {interval}m]({url}) |")
    return "\n".join(rows)


def open_chrome_tabs(tickers: List[str], interval: str = '5',
                     background: bool = False) -> int:
    """
    Open TradingView charts in Chrome tabs.

    Parameters
    ----------
    tickers : list of str
    interval : str
    background : bool
        If True, open all in background tabs (single new window, multiple tabs)
        If False, open each as new foreground window

    Returns
    -------
    number of tabs opened
    """
    urls = []
    for t in tickers:
        sym = to_tv_symbol(t)
        urls.append(f"https://www.tradingview.com/chart/?symbol={sym}&interval={interval}")

    if not urls:
        return 0

    # Use macOS 'open' command with multiple URLs (single window, multiple tabs)
    cmd = ['open', '-a', 'Google Chrome']
    if background:
        cmd.append('--background')
    cmd.extend(urls)

    try:
        subprocess.run(cmd, check=True, timeout=15)
        return len(urls)
    except subprocess.CalledProcessError:
        # Fallback: open one at a time
        opened = 0
        for url in urls:
            try:
                subprocess.run(['open', url], check=False, timeout=5)
                opened += 1
            except Exception:
                continue
        return opened
    except FileNotFoundError:
        # Chrome not available — print URLs as fallback
        print("[framework] Chrome not found — URLs:")
        for url in urls:
            print(f"  {url}")
        return 0


def build_and_open(tickers: List[str], interval: str = '5',
                   open_chrome: bool = True) -> str:
    """
    Convenience: build table + open Chrome tabs.
    Returns the markdown table.
    """
    table = build_tv_links(tickers, interval)
    if open_chrome:
        n = open_chrome_tabs(tickers, interval)
        print(f"\n[framework] Opened {n}/{len(tickers)} Chrome tabs")
    return table


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: chart_links.py TICKER1,TICKER2,... [interval]")
        sys.exit(1)
    tickers = sys.argv[1].split(',')
    interval = sys.argv[2] if len(sys.argv) > 2 else '5'
    table = build_and_open(tickers, interval)
    print(table)
