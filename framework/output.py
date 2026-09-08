"""
Discord / Telegram output for [framework] signals.
Webhook URLs MUST come from environment variables to keep secrets out of git.
"""
import os
import subprocess
import json
from datetime import datetime

DISCORD_WEBHOOK = os.environ.get(
    'DISCORD_WEBHOOK_URL',
    ''  # blank by default — must be set via env var or .env file
)


def signal_table(signals) -> str:
    """Format signals as a markdown table."""
    header = (
        "| Ticker | Name | Score | Dir | Entry | TP | SL |\n"
        "|--------|------|------:|-----|------:|----:|----:|"
    )
    rows = []
    for s in signals:
        emoji = "🟢" if s.direction == "LONG" else "🔴"
        rows.append(
            f"| {emoji} {s.ticker} | {s.name} | {s.score} | "
            f"{s.direction} | {s.entry_price} | {s.tp_price} | {s.sl_price} |"
        )
    return header + "\n" + "\n".join(rows)


def post_discord(title: str, content: str):
    """Post to Discord webhook with [framework] tag.

    Requires DISCORD_WEBHOOK_URL environment variable. If unset, prints a
    warning so silent failures don't hide Discord delivery issues.
    """
    webhook = DISCORD_WEBHOOK or os.environ.get('DISCORD_WEBHOOK_URL', '')
    if not webhook:
        print(f"[framework] ⚠️  DISCORD_WEBHOOK_URL not set — Discord post skipped")
        print(f"         Set env var: export DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...")
        return False

    payload = {
        "content": f"[framework] **{title}** {datetime.now().strftime('%H:%M')}",
        "embeds": [{
            "description": content,
            "color": 0x00ff00 if "LONG" in content else 0xff0000,
        }]
    }
    try:
        result = subprocess.run(
            ["curl", "-s", "-w", "\n%{http_code}",
             "-X", "POST", webhook,
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload)],
            capture_output=True, text=True, timeout=15
        )
        # Split body from HTTP code; accept 2xx as success
        parts = result.stdout.rsplit('\n', 1)
        body = parts[0] if len(parts) > 1 else ''
        http_code = parts[1] if len(parts) > 1 else '0'
        try:
            code = int(http_code.strip())
        except ValueError:
            code = 0
        if 200 <= code < 300:
            return True
        else:
            print(f"[framework] ⚠️  Discord post failed: HTTP {code} — {body[:200]}")
            return False
    except Exception as e:
        print(f"[framework] ⚠️  Discord post exception: {e}")
        return False


def daily_report(signals_by_strategy: dict) -> str:
    """
    Compile full framework report from signals_by_strategy dict.
    Each value: {'signals': [Signal], 'review': str, 'stats': dict,
                 optional 'tv_table', 'social'}
    """
    lines = [
        f"## [framework] Trading Signals — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    ]
    for name, data in signals_by_strategy.items():
        s = data['stats']
        pf = s.get('profit_factor', s.get('pf', 0))
        lines.append(
            f"### {name}  "
            f"({s['trades']} trades, WR {s['win_rate']}%, PF {pf})"
        )
        lines.append(signal_table(data['signals']))

        if data.get('tv_table'):
            lines.append("\n**📈 TradingView Charts:**")
            lines.append(data['tv_table'])

        if data.get('social'):
            lines.append("\n**💬 Social Sentiment (Futu + Xueqiu):**")
            lines.append(data['social'].get('summary', ''))

        if data.get('review'):
            lines.append(f"```\n{data['review']}\n```\n")

    report = "\n".join(lines)
    post_discord("Daily Signal Report", report)
    return report


def post_telegram(text: str):
    """Post to Telegram via bot. Requires TELEGRAM_BOT_TOKEN env var."""
    import os
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        return
    subprocess.run(
        ["curl", "-s", "-X", "POST",
         f"https://api.telegram.org/bot{token}/sendMessage",
         "-d", f"chat_id={chat_id}&text=[framework] {text}&parse_mode=Markdown"],
        check=False
    )
