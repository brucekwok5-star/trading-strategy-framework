"""
Discord / Telegram output for [framework] signals.
"""
import subprocess
import json
from datetime import datetime

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1531888048797782026/..."


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
    """Post to Discord webhook with [framework] tag."""
    payload = {
        "content": f"[framework] **{title}** {datetime.now().strftime('%H:%M')}",
        "embeds": [{
            "description": content,
            "color": 0x00ff00 if "LONG" in content else 0xff0000,
        }]
    }
    subprocess.run(
        ["curl", "-s", "-X", "POST", DISCORD_WEBHOOK,
         "-H", "Content-Type: application/json",
         "-d", json.dumps(payload)],
        check=False
    )


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
