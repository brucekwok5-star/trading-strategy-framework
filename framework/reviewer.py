"""
AI Reviewer Agent — spawns separate hermes agent (MiniMax M3.0) to review signals.
Checks: data correctness, criteria met, TP/SL plausible, best 3 long+short.
"""
import subprocess
import json

REVIEW_PROMPT = """You are a quantitative trading reviewer. Tag all output with [framework].

## Strategy: {strategy}
## Market: {market} | Data Source: {data_source}

## Signals to review
```json
{signals_json}
```

## Review Tasks
1. **Data correctness**: price within 10% of reasonable market price? volume > 0? timestamp in valid trading hours?
2. **Criteria met**: ALL filter conditions from the strategy spec are satisfied?
3. **TP/SL plausible**: TP and SL distances within ±3x ATR? Entry price reasonable?
4. **Best 3 LONG** and **Best 3 SHORT**: rank by score descending. Must pass ALL criteria.
5. **Concerns**: flag any suspicious signal (penny-stock vol artifact, data glitch, gap risk, etc.).

Respond EXACTLY in this format:
[framework]
### Data Check
PASS/FAIL per signal — short reason if FAIL

### Criteria Check
PASS/FAIL per signal — which criterion failed if any

### TP/SL Analysis
PLAUSIBLE / SUSPICIOUS per signal — why if suspicious

### Best 3 LONG
1. TICKER — score — one-line reason
2. TICKER — score — one-line reason
3. TICKER — score — one-line reason

### Best 3 SHORT
1. TICKER — score — one-line reason
2. TICKER — score — one-line reason
3. TICKER — score — one-line reason

### Concerns
- TICKER: reason
"""


def review_signals(signals, strategy_name, market, data_source) -> str:
    """
    Spawn a MiniMax M3.0 hermes agent to review signals.
    Returns the review text.
    """
    signals_json = json.dumps([
        {
            'ticker': s.ticker,
            'direction': s.direction,
            'entry_price': s.entry_price,
            'tp_price': s.tp_price,
            'sl_price': s.sl_price,
            'score': s.score,
            'atr': s.atr,
        }
        for s in signals
    ], indent=2)

    prompt = REVIEW_PROMPT.format(
        strategy=strategy_name,
        market=market,
        data_source=data_source,
        signals_json=signals_json,
    )

    # Write prompt to a temp file to avoid shell quoting issues
    import tempfile
    prompt_file = tempfile.NamedTemporaryFile(
        mode='w', suffix='.txt', delete=False, encoding='utf-8'
    )
    prompt_file.write(prompt)
    prompt_file.close()

    # Use bash to feed prompt via stdin or use file expansion
    try:
        result = subprocess.run(
            ['bash', '-c',
             f'cat {prompt_file.name} | hermes chat -q "$(cat {prompt_file.name})" '
             f'-m minimax --provider minimax-cn'],
            capture_output=True, text=True, timeout=120
        )
        output = result.stdout or result.stderr
    except subprocess.TimeoutExpired:
        output = '(review timed out after 120s)'
    finally:
        import os
        try:
            os.unlink(prompt_file.name)
        except Exception:
            pass
    return output


def review_and_rank_all(STRATEGIES_DICT) -> dict:
    """
    Scan every strategy → review → aggregate best LONGs + SHORTs across all.
    Returns dict: {strategy_name: {'signals', 'review', 'stats'}}
    """
    from signal_db import strategy_stats

    all_results = {}
    for name, strat in STRATEGIES_DICT.items():
        # Run scan (empty ticker list = use default pool)
        signals = strat.scan([])
        # Review
        review = review_signals(signals, name, strat.market, strat.data_source)
        # Stats from TinyDB
        stats = strategy_stats(name)
        all_results[name] = {
            'signals': signals,
            'review': review,
            'stats': stats,
        }
    return all_results
