"""
Social sentiment scanner — Futu Discussion Hunter + Xueqiu Browser Stock Scan.

Auto-starts required services:
  - Futu OpenD (CDP port 18800) via /Applications/Futu_OpenD.app
  - Chrome with --remote-debugging-port=9222

If services can't be started (no permission, port busy), falls back gracefully
with explicit instructions instead of silent skip.
"""
import subprocess
import json
import time
import os
import re
from pathlib import Path
from typing import List, Dict, Optional


FUTU_OPEN_D_APP = "/Applications/Futu_OpenD.app/Contents/MacOS/Futu_OpenD"
FUTU_CDP_PORT = 18800
CHROME_DEBUG_PORT = 9222
CHROME_APP = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


# ---------------------------------------------------------------------------
# Service management
# ---------------------------------------------------------------------------

def is_port_listening(port: int, host: str = '127.0.0.1') -> bool:
    """Check if a TCP port is listening."""
    try:
        r = subprocess.run(
            ['curl', '-s', '--max-time', '3', f'http://{host}:{port}/json'],
            capture_output=True, timeout=5
        )
        return r.returncode == 0 and bool(r.stdout)
    except Exception:
        return False


def start_futu_opend(timeout: int = 30) -> bool:
    """
    Start Futu OpenD if not running. Returns True when CDP port 18800 responds.

    NOTE: OpenD GUI pops up; user may need to log in (already logged in on Bruce's Mac).
    Also checks if Chrome on port 18803 (OpenClaw xueqiu session) is available
    as a fallback source for futu-style scraping via xueqiu community.
    """
    if is_port_listening(FUTU_CDP_PORT):
        return True

    # Check if OpenClaw xueqiu Chrome on 18803 is available (fallback)
    if is_port_listening(18803):
        print(f"[framework] Port 18800 (Futu CDP) not up, but 18803 (OpenClaw xq) is")
        print(f"[framework] Will use 18803 for scraping via xueqiu pages")
        return False  # return False so caller uses xueqiu path

    if not Path(FUTU_OPEN_D_APP).exists():
        print(f"[framework] Futu OpenD binary not found: {FUTU_OPEN_D_APP}")
        return False

    print(f"[framework] Starting Futu OpenD (CDP port {FUTU_CDP_PORT})...")
    try:
        # Launch OpenD in background — detached so it survives this script
        subprocess.Popen(
            [FUTU_OPEN_D_APP],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
    except Exception as e:
        print(f"[framework] Failed to start Futu OpenD: {e}")
        return False

    # Wait for CDP port to come up
    start = time.time()
    while time.time() - start < timeout:
        if is_port_listening(FUTU_CDP_PORT):
            print(f"[framework] Futu OpenD CDP ready ({time.time()-start:.1f}s)")
            return True
        time.sleep(2)

    print(f"[framework] Futu OpenD CDP did not respond within {timeout}s")
    print(f"  Hint: In Futu OpenD settings, enable 'Chrome DevTools Protocol' on port 18800")
    return False


def start_chrome_with_debug(timeout: int = 15) -> bool:
    """
    Launch Chrome with --remote-debugging-port + --remote-allow-origins=*
    if not already running with the correct flags.

    If a Chrome is already listening on the debug port but WITHOUT
    --remote-allow-origins (Chrome 111+ requirement), the caller will get 403
    errors when trying to use WebSocket — we surface that hint to the user.
    """
    if is_port_listening(CHROME_DEBUG_PORT):
        print(f"[framework] Chrome already listening on {CHROME_DEBUG_PORT}")
        print(f"[framework] (If WS gets 403, that Chrome needs --remote-allow-origins=*)")
        return True

    if not Path(CHROME_APP).exists():
        print(f"[framework] Chrome not found: {CHROME_APP}")
        return False

    debug_profile = Path.home() / ".chrome_debug_profile"
    debug_profile.mkdir(exist_ok=True)

    print(f"[framework] Starting Chrome with --remote-debugging-port={CHROME_DEBUG_PORT}...")
    try:
        subprocess.Popen(
            [CHROME_APP,
             f'--remote-debugging-port={CHROME_DEBUG_PORT}',
             '--remote-allow-origins=*',  # Required since Chrome 111+
             f'--user-data-dir={debug_profile}',
             '--no-first-run',
             '--no-default-browser-check',
             'about:blank'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
    except Exception as e:
        print(f"[framework] Failed to start Chrome: {e}")
        return False

    # Wait for debug port
    start = time.time()
    while time.time() - start < timeout:
        if is_port_listening(CHROME_DEBUG_PORT):
            print(f"[framework] Chrome debug port ready ({time.time()-start:.1f}s)")
            return True
        time.sleep(1)

    print(f"[framework] Chrome debug port did not respond within {timeout}s")
    return False


def cdp_pages(port: int) -> List[dict]:
    """List CDP pages on given port."""
    try:
        r = subprocess.run(
            ['curl', '-s', '--max-time', '5', f'http://127.0.0.1:{port}/json'],
            capture_output=True, text=True, timeout=10
        )
        return json.loads(r.stdout) if r.stdout else []
    except Exception:
        return []


def cdp_create_page(port: int, url: str = 'about:blank') -> Optional[str]:
    """Create a new CDP target. Returns page ws URL or None.

    Modern Chrome requires PUT /json/new?url=... (legacy /json/create is deprecated).
    """
    try:
        r = subprocess.run([
            'curl', '-s', '-X', 'PUT',
            f'http://127.0.0.1:{port}/json/new?{url}'
        ], capture_output=True, text=True, timeout=10)
        if r.stdout:
            try:
                # Response is a single target object: {"id":"...","url":"...","webSocketDebuggerUrl":"..."}
                d = json.loads(r.stdout)
                # Prefer webSocketDebuggerUrl directly
                ws = d.get('webSocketDebuggerUrl')
                if ws:
                    return ws
                tid = d.get('id')
                if tid:
                    return f"ws://127.0.0.1:{port}/devtools/page/{tid}"
            except json.JSONDecodeError:
                pass
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Direction detection (shared)
# ---------------------------------------------------------------------------

def _detect_direction(text: str) -> str:
    """Bull/bear detection — same as futu-discussion-hunter skill."""
    bull_kw = ["上涨", "大涨", "看好", "买入", "加仓", "做多", "反弹", "突破",
               "抄底", "持有", "满仓", "建仓", "会涨", "上行", "拉升", "牛",
               "增长", "增持", "上车", "布局", "低位", "升", "涨", "睇好",
               "目標", "目标价"]
    bear_kw = ["下跌", "大跌", "看跌", "做空", "止损", "割肉", "跌", "跌破",
               "弱势", "清仓", "减持", "不看好", "避开", "空仓", "崩", "不值",
               "还会跌", "减仓", "看空", "高估", "远离", "卖出", "止盈", "逃顶",
               "熊", "弱", "沽空", "唔好"]
    bull = sum(1 for w in bull_kw if w in text)
    bear = sum(1 for w in bear_kw if w in text)
    if bull > bear + 1:
        return "bullish"
    if bear > bull + 1:
        return "bearish"
    return "neutral"


# ---------------------------------------------------------------------------
# Futu scan (real implementation)
# ---------------------------------------------------------------------------

def scan_futu(tickers: List[str], max_posts_per_stock: int = 10) -> Dict[str, dict]:
    """
    Scrape Futu 牛牛圈 community for each ticker via CDP.

    Auto-starts Futu OpenD if needed.

    Parameters
    ----------
    tickers : list of str
        HK 5-digit codes like '00700', '09988'
    max_posts_per_stock : int

    Returns
    -------
    dict mapping ticker -> {
        'posts': [...],
        'bullish_count': int,
        'bearish_count': int,
        'top_users': [...],
        'sample_text': str,
    }
    """
    FALLBACK_RESULT = lambda: {
        'posts': [], 'bullish_count': 0, 'bearish_count': 0,
        'top_users': [], 'sample_text': '',
    }

    # Auto-start OpenD if needed
    if not start_futu_opend():
        print("[framework] Futu scan unavailable — OpenD not reachable")
        return {t: FALLBACK_RESULT() for t in tickers}

    # Find or create a CDP page
    pages = cdp_pages(FUTU_CDP_PORT)
    futu_pages = [p for p in pages if 'futunn.com' in p.get('url', '')]
    if futu_pages:
        ws_url = f"ws://127.0.0.1:{FUTU_CDP_PORT}/devtools/page/{futu_pages[0]['id']}"
    else:
        ws_url = cdp_create_page(FUTU_CDP_PORT, 'about:blank')
        if not ws_url:
            print("[framework] Failed to create CDP page")
            return {t: FALLBACK_RESULT() for t in tickers}

    # Find futu_hunt.js script
    hunt_script = None
    for path in [
        Path.home() / ".openclaw" / "workspace" / "futu_hunt.js",
        Path.home() / "workspace" / "futu_hunt.js",
        Path("/tmp/futu_hunt.js"),
    ]:
        if path.exists():
            hunt_script = str(path)
            break

    if not hunt_script:
        print("[framework] futu_hunt.js not found in ~/.openclaw/workspace/ or /tmp/")
        print("[framework] Hint: extract it from futu-discussion-hunter skill")
        return {t: FALLBACK_RESULT() for t in tickers}

    # Scrape each ticker
    results = {}
    for ticker in tickers:
        if not ticker.isdigit() or len(ticker) != 5:
            results[ticker] = FALLBACK_RESULT()
            continue

        url = f"https://www.futunn.com/hk/stock/{ticker}-HK/community"
        try:
            # Navigate
            nav = subprocess.run(
                ['node', hunt_script, ws_url, 'nav', url],
                capture_output=True, text=True, timeout=30
            )
            if nav.returncode != 0:
                results[ticker] = FALLBACK_RESULT()
                continue

            # Wait for SPA render
            time.sleep(5)

            # Extract posts
            ext = subprocess.run(
                ['node', hunt_script, ws_url, 'extract'],
                capture_output=True, text=True, timeout=60
            )
            if ext.returncode != 0 or not ext.stdout.strip():
                results[ticker] = FALLBACK_RESULT()
                continue

            try:
                posts = json.loads(ext.stdout.strip())[:max_posts_per_stock]
            except json.JSONDecodeError:
                results[ticker] = FALLBACK_RESULT()
                continue

            # Aggregate bull/bear counts
            bull, bear = 0, 0
            user_count = {}
            sample_text = ''
            for p in posts:
                text = p.get('text', '')
                if not text or len(text) < 10:
                    continue
                direction = _detect_direction(text)
                if direction == "bullish":
                    bull += 1
                elif direction == "bearish":
                    bear += 1
                for u in p.get('users', []):
                    name = u.get('name', '')
                    if name:
                        user_count[name] = user_count.get(name, 0) + 1
                if not sample_text:
                    sample_text = text[:120]

            top_users = sorted(user_count.items(),
                               key=lambda x: -x[1])[:5]

            results[ticker] = {
                'posts': posts,
                'bullish_count': bull,
                'bearish_count': bear,
                'top_users': top_users,
                'sample_text': sample_text,
            }

            # Rate limit
            time.sleep(3)

        except Exception as e:
            print(f"[framework] Futu {ticker} error: {e}")
            results[ticker] = FALLBACK_RESULT()

    return results


# ---------------------------------------------------------------------------
# Xueqiu scan (real implementation)
# ---------------------------------------------------------------------------

def _chrome_evaluate(ws_url: str, expression: str, timeout: int = 30) -> Optional[str]:
    """Run a JS expression in Chrome via CDP. Returns result.value or None."""
    hunt_script = None
    for path in [
        Path.home() / ".openclaw" / "workspace" / "cdp_eval.js",
        Path.home() / "workspace" / "cdp_eval.js",
        Path("/tmp/cdp_eval.js"),
    ]:
        if path.exists():
            hunt_script = str(path)
            break

    if not hunt_script:
        # Fallback: use python websockets client if available
        try:
            import websocket  # type: ignore
            return _chrome_evaluate_pyws(ws_url, expression, timeout)
        except ImportError:
            print("[framework] websocket-client not installed: pip install websocket-client")
            return None

    try:
        r = subprocess.run(
            ['node', hunt_script, ws_url, 'eval', expression],
            capture_output=True, text=True, timeout=timeout
        )
        if r.returncode == 0 and r.stdout:
            try:
                data = json.loads(r.stdout)
                return data.get('result', {}).get('value')
            except json.JSONDecodeError:
                return r.stdout.strip()
    except Exception:
        pass
    return None


def _chrome_evaluate_pyws(ws_url: str, expression: str, timeout: int = 30) -> Optional[str]:
    """Pure-Python CDP evaluation via websocket-client."""
    try:
        import websocket  # type: ignore
        ws = websocket.create_connection(ws_url, timeout=timeout)
        msg_id = 1
        ws.send(json.dumps({
            'id': msg_id,
            'method': 'Runtime.evaluate',
            'params': {'expression': expression, 'returnByValue': True,
                       'awaitPromise': True}
        }))
        ws.settimeout(timeout)
        while True:
            raw = ws.recv()
            data = json.loads(raw)
            if data.get('id') == msg_id:
                ws.close()
                return data.get('result', {}).get('result', {}).get('value')
    except Exception as e:
        print(f"[framework] Chrome eval failed: {e}")
        return None


def scan_xueqiu(tickers: List[str], max_posts_per_stock: int = 8) -> Dict[str, dict]:
    """
    Scrape Xueqiu discussion for each ticker.

    Auto-starts Chrome with --remote-debugging-port=9222 if needed.
    Navigates to xueqiu.com search box, types ticker, extracts articles.

    Returns
    -------
    dict mapping ticker -> {...}
    """
    FALLBACK_RESULT = lambda: {
        'posts': [], 'bullish_count': 0, 'bearish_count': 0, 'sample_text': '',
    }

    # Auto-start Chrome with debug port
    if not start_chrome_with_debug():
        print("[framework] Xueqiu scan unavailable — Chrome debug port not reachable")
        return {t: FALLBACK_RESULT() for t in tickers}

    # Find or create xueqiu page
    pages = cdp_pages(CHROME_DEBUG_PORT)
    xq_pages = [p for p in pages if 'xueqiu.com' in p.get('url', '')]

    if xq_pages:
        ws_url = f"ws://127.0.0.1:{CHROME_DEBUG_PORT}/devtools/page/{xq_pages[0]['id']}"
    else:
        # Create new page and navigate to xueqiu
        ws_url = cdp_create_page(CHROME_DEBUG_PORT, 'https://xueqiu.com')
        if not ws_url:
            print("[framework] Failed to create xueqiu CDP page")
            return {t: FALLBACK_RESULT() for t in tickers}
        # Wait for SPA to load
        time.sleep(6)

    # Verify login state by snapshotting current URL
    try:
        r = subprocess.run(
            ['curl', '-s', '--max-time', '5', f'http://127.0.0.1:{CHROME_DEBUG_PORT}/json'],
            capture_output=True, text=True, timeout=10
        )
        all_pages = json.loads(r.stdout) if r.stdout else []
        xq_page = next((p for p in all_pages if p.get('id') in ws_url), None)
        if xq_page and 'login' in xq_page.get('url', '').lower():
            print("[framework] ⚠️  Xueqiu logged out — user must scan QR to log in")
            print("[framework] Open Chrome (debug profile) → xueqiu.com → scan QR")
    except Exception:
        pass

    # JS extraction code from xueqiu-browser-stock-scan skill
    JS_EXTRACT = """(function(){
  var r=[];
  var a=document.querySelectorAll('article');
  for(var i=0;i<Math.min(8,a.length);i++){
    var t=a[i].innerText.substring(0,500).replace(/\\n+/g,' ').trim();
    var u=a[i].querySelectorAll('a[href*="/u/"]');
    var n=u.length>0?u[0].innerText:'unknown';
    r.push(n+'|||'+t);
  }
  return JSON.stringify(r);
})()"""

    results = {}
    for ticker in tickers:
        # Pad HK tickers to 5 digits
        if ticker.isdigit():
            xq_ticker = ticker.zfill(5)
        else:
            xq_ticker = ticker  # US: as-is

        try:
            # Step 1: click search box and type ticker
            # (Simplified — full skill uses browser_* tools with @refs)
            # Use Runtime.evaluate to set search box value
            type_js = f"""
            (function(){{
              var box = document.querySelector('input[type="search"], input.search-input, input[placeholder*="搜索"], input[placeholder*="股票"]');
              if (!box) return 'no_search_box';
              box.focus();
              box.value = '{xq_ticker}';
              box.dispatchEvent(new Event('input', {{bubbles:true}}));
              box.dispatchEvent(new KeyboardEvent('keydown', {{key:'Enter', code:'Enter', keyCode:13, bubbles:true}}));
              return 'typed';
            }})()
            """

            typed = _chrome_evaluate(ws_url, type_js)
            if typed != 'typed':
                results[ticker] = {
                    'posts': [], 'bullish_count': 0, 'bearish_count': 0,
                    'sample_text': f'(search box not found — log in to xueqiu)',
                    'note': 'logged_out_or_login_required',
                }
                continue

            # Wait for SPA to render search results
            time.sleep(5)

            # Extract posts
            raw = _chrome_evaluate(ws_url, JS_EXTRACT)
            if not raw:
                results[ticker] = FALLBACK_RESULT()
                continue

            try:
                raw_posts = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                results[ticker] = FALLBACK_RESULT()
                continue

            posts = []
            for entry in raw_posts[:max_posts_per_stock]:
                if '|||' in entry:
                    user, text = entry.split('|||', 1)
                else:
                    user, text = 'unknown', entry
                posts.append({'user': user.strip(), 'text': text.strip()})

            # Aggregate
            bull, bear = 0, 0
            sample_text = ''
            for p in posts:
                text = p.get('text', '')
                if not text:
                    continue
                direction = _detect_direction(text)
                if direction == 'bullish':
                    bull += 1
                elif direction == 'bearish':
                    bear += 1
                if not sample_text:
                    sample_text = text[:120]

            results[ticker] = {
                'posts': posts,
                'bullish_count': bull,
                'bearish_count': bear,
                'sample_text': sample_text,
                'note': '',
            }

            # Clear search box for next ticker
            time.sleep(4)

        except Exception as e:
            print(f"[framework] Xueqiu {ticker} error: {e}")
            results[ticker] = FALLBACK_RESULT()

    return results


# ---------------------------------------------------------------------------
# Unified wrapper
# ---------------------------------------------------------------------------

def scan_signal_stocks_social(tickers: List[str],
                               do_futu: bool = True,
                               do_xueqiu: bool = True) -> dict:
    """
    Run social sentiment scan on signal tickers via Futu + Xueqiu.
    Auto-starts required services.
    """
    hk_tickers = [t for t in tickers if t.isdigit()]
    print(f"[framework] Social scan: {len(tickers)} tickers "
          f"({len(hk_tickers)} HK applicable for Futu)")

    futu_data = scan_futu(hk_tickers) if do_futu else {}
    xueqiu_data = scan_xueqiu(tickers) if do_xueqiu else {}

    # Build summary markdown
    summary = _build_summary_table(tickers, futu_data, xueqiu_data)

    return {
        'tickers': tickers,
        'futu': futu_data,
        'xueqiu': xueqiu_data,
        'summary': summary,
    }


def _build_summary_table(tickers: List[str],
                          futu: Dict[str, dict],
                          xueqiu: Dict[str, dict]) -> str:
    """Build a markdown summary table."""
    rows = ["| Ticker | Futu Bull | Futu Bear | Futu Net | Xueqiu Bull | Xueqiu Bear | Xueqiu Net |",
            "|--------|----------:|----------:|:---------|------------:|------------:|:-----------|"]
    for t in tickers:
        f = futu.get(t, {})
        fb, fr = f.get('bullish_count', 0), f.get('bearish_count', 0)
        fn = '🟢' if fb > fr + 1 else ('🔴' if fr > fb + 1 else '⚪')

        x = xueqiu.get(t, {})
        xb, xr = x.get('bullish_count', 0), x.get('bearish_count', 0)
        xn = '🟢' if xb > xr + 1 else ('🔴' if xr > xb + 1 else '⚪')

        note = x.get('note', '')
        if note:
            xn = f"{xn}*"

        rows.append(f"| {t} | {fb} | {fr} | {fn} | {xb} | {xr} | {xn} |")

    footnote = ""
    if any(x.get('note') for x in xueqiu.values()):
        footnote = "\n*\\* Xueqiu needs login or returned empty results*"
    return "\n".join(rows) + footnote


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: social_scan.py TICKER1,TICKER2,...")
        sys.exit(1)
    tickers = sys.argv[1].split(',')
    result = scan_signal_stocks_social(tickers)
    print(result['summary'])
