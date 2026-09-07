"""
Tencent qt.gtimg.cn data source — free real-time + historical for HK and US stocks.
HK format: 5-digit code like '00700' → 'hk00700' (zero-padded to 6)
US format: AAPL → 'usAAPL'

Uses curl via subprocess (Python urllib blocked in sandbox).
"""
import subprocess
import json
import pandas as pd
import numpy as np
import os


def _curl(url, encoding='utf-8', timeout=15):
    """Run curl via subprocess, return decoded text."""
    try:
        result = subprocess.run(
            ['curl', '-s', '--max-time', str(timeout), url],
            capture_output=True, timeout=timeout + 5
        )
        if result.returncode != 0:
            return ''
        try:
            return result.stdout.decode(encoding, errors='replace')
        except LookupError:
            return result.stdout.decode('utf-8', errors='replace')
    except Exception:
        return ''


def fetch_daily(tickers, days=320):
    """
    Fetch daily OHLCV for HK and US tickers via Tencent (web.ifzq.gtimg.cn).

    Parameters
    ----------
    tickers : list of str
        HK: 5-digit code '00700' (auto-padded to 6)
        US: 'AAPL' etc
    days : int
        Number of trading days (default 320)

    Returns
    -------
    dict mapping original ticker -> DataFrame with columns:
        date, open, close, high, low, volume
    """
    results = {}
    for t in tickers:
        clean = t.strip().lower()
        if clean.startswith('hk'):
            prefix, code = 'hk', clean[2:]
        elif clean.startswith('us'):
            prefix, code = 'us', clean[2:]
        elif clean.isdigit():
            prefix, code = 'hk', clean  # already 5-digit, don't repad
        else:
            prefix, code = 'us', clean

        url = (
            f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            f"?_var=kline_dayhfq&param={prefix}{code},day,,,{days},qfq"
        )
        raw = _curl(url, encoding='utf-8')
        if not raw:
            continue
        try:
            # Tencent returns `kline_dayhfq={...}` with assignment
            if '=' in raw and not raw.lstrip().startswith('{'):
                raw = raw.split('=', 1)[1]
            data = json.loads(raw)
        except Exception:
            continue

        key = f"{prefix}{code}"
        if key not in data.get('data', {}):
            continue

        # Tencent returns 'day' key (not 'qfqday' when qfq param is set)
        rows = (data['data'][key].get('qfqday') or
                data['data'][key].get('day') or
                data['data'][key].get('data'))
        if not rows:
            continue

        # Filter out metadata rows (last entry is often a dict)
        clean_rows = []
        for r in rows:
            if isinstance(r, list) and len(r) >= 6:
                clean_rows.append(r[:6])
        if not clean_rows:
            continue

        df = pd.DataFrame(clean_rows, columns=['date', 'open', 'close', 'high', 'low', 'volume'])
        df = df.astype({'open': float, 'close': float,
                        'high': float, 'low': float, 'volume': float})
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        results[t] = df

    return results


def fetch_realtime(tickers):
    """
    Fetch real-time quotes via Tencent (qt.gtimg.cn).

    Parameters
    ----------
    tickers : list of str
        HK: 5-digit code '00700' (already padded by Futu convention)
            or 6-digit '000700' (auto-detected)
        US: 'AAPL' etc

    Returns
    -------
    dict mapping ORIGINAL ticker -> dict:
        price, open, high, low, volume, prev_close, change_pct, change
    """
    parts = []
    padded_map = {}
    for t in tickers:
        clean = t.strip()
        if clean.lower().startswith('hk') or clean.lower().startswith('us'):
            parts.append(clean.lower())
        elif clean.isdigit():
            # HK codes are already 5-6 digits. Tencent expects 'hk' + code as-is
            # (e.g. hk00700 works, NOT hk000700)
            parts.append(f'hk{clean}')
            padded_map[f'hk{clean}'] = clean
        else:
            parts.append(f'us{clean.lower()}')

    q = ','.join(parts)
    url = f"https://qt.gtimg.cn/q={q}"
    raw = _curl(url, encoding='gbk')

    results = {}
    for line in raw.strip().split('\n'):
        if not line or 'pv_none_match' in line:
            continue
        # Format: v_hk00700="100~腾讯控股~00700~438.800~..."
        if '=' in line:
            line = line.split('=', 1)[1]
        line = line.strip().strip(';').strip('"')
        p = line.split('~')
        if len(p) < 45:
            continue

        raw_ticker = p[2].strip().strip('"') if len(p) > 2 else ''
        # Map back to original
        if raw_ticker in padded_map:
            ticker = padded_map[raw_ticker]
        elif raw_ticker.startswith('hk'):
            ticker = raw_ticker[2:]  # keep as-is (already 5-digit)
        elif raw_ticker.startswith('us'):
            ticker = raw_ticker[2:].upper()
        else:
            ticker = raw_ticker

        try:
            results[ticker] = {
                'name': p[1].strip(),  # stock name (e.g. 腾讯控股)
                'price': float(p[3]),
                'prev_close': float(p[4]),
                'open': float(p[5]),
                'volume': float(p[6]) if p[6] else 0,
                'high': float(p[33]),
                'low': float(p[34]),
                'change': float(p[31]),
                'change_pct': float(p[32]),
                # Fundamentals (Tencent qt.gtimg.cn fields, reverse-engineered):
                'turnover': float(p[37]) if len(p) > 37 and p[37] else 0,    # 成交额
                'pe_ttm': float(p[57]) if len(p) > 57 and p[57] else 0,        # PE-TTM
                'pb': float(p[59]) if len(p) > 59 and p[59] else 0,            # PB
                'dividend_yield': float(p[50]) if len(p) > 50 and p[50] else 0,  # 股息率 %
                'market_cap': float(p[44]) if len(p) > 44 and p[44] else 0,    # 总市值(亿)
                'high_52w': float(p[48]) if len(p) > 48 and p[48] else 0,       # 52周高
                'low_52w': float(p[49]) if len(p) > 49 and p[49] else 0,        # 52周低
            }
        except (ValueError, IndexError):
            continue

    return results


def lookup_names(tickers):
    """Return {ticker: name} from realtime quote."""
    quotes = fetch_realtime(tickers)
    return {t: q.get('name', t) for t, q in quotes.items()}


def fetch_intraday(ticker, interval='5m', count=320):
    """
    Fetch intraday bars via Tencent min K-line endpoint.
    interval: '1m', '5m', '15m', '30m', '60m'
    """
    clean = ticker.strip().lower()
    if clean.startswith('hk'):
        prefix, code = 'hk', clean[2:]
    elif clean.startswith('us'):
        prefix, code = 'us', clean[2:]
    elif clean.isdigit():
        prefix, code = 'hk', clean  # already 5-digit, don't repad
    else:
        prefix, code = 'us', clean

    url = (
        f"https://web.ifzq.gtimg.cn/appstock/app/kline/mchart"
        f"?_var=kline_{interval}&param={prefix}{code},{interval},,,{count}"
    )
    raw = _curl(url)
    if not raw:
        return pd.DataFrame()

    try:
        if '=' in raw and not raw.lstrip().startswith('{'):
            raw = raw.split('=', 1)[1]
        data = json.loads(raw)
    except Exception:
        return pd.DataFrame()

    # mchart returns min chart with single 'data' field, no time marker
    # Try different keys
    for d_key in ['data', 'mchart']:
        if d_key not in data:
            continue
        key = f"{prefix}{code}"
        if key in data[d_key]:
            bars = data[d_key][key].get(interval) or data[d_key][key].get('data')
            if bars:
                # bars: [time, open, close, high, low, volume, ...]
                clean_rows = [b[:6] for b in bars if isinstance(b, list) and len(b) >= 6]
                if clean_rows:
                    df = pd.DataFrame(clean_rows,
                                       columns=['datetime', 'open', 'close', 'high', 'low', 'volume'])
                    df = df.astype({'open': float, 'close': float,
                                    'high': float, 'low': float, 'volume': float})
                    return df

    return pd.DataFrame()
