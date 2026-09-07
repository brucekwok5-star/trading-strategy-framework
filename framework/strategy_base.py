"""
Base interface for all trading strategies.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict
import pandas as pd


@dataclass
class Signal:
    ticker: str
    name: str
    direction: str      # 'LONG' or 'SHORT'
    entry_price: float
    entry_time: str    # ISO timestamp
    tp_price: float
    sl_price: float
    atr: float
    score: float        # 0–100
    strategy: str       # e.g. 'dtat-scalper'
    market: str         # 'HK' or 'US'
    metadata: Dict = field(default_factory=dict)


@dataclass
class BacktestResult:
    ticker: str
    entry_time: str
    exit_time: str
    direction: str
    entry_price: float
    exit_price: float
    pnl_pct: float
    win: bool
    params: Dict


class Strategy(ABC):
    """Abstract base class for all trading strategies."""

    name: str = "BaseStrategy"
    market: str = "HK"          # 'HK' or 'US'
    data_source: str = "yfinance"  # 'futu' | 'tencent' | 'yfinance'

    def default_params(self) -> Dict:
        return {}

    @abstractmethod
    def scan(self, tickers: List[str], date: str = None) -> List[Signal]:
        """Run scan and return list of signals."""
        pass

    @abstractmethod
    def backtest(self, tickers: List[str], start_date: str, end_date: str,
                 params: Dict = None) -> List[BacktestResult]:
        """Run backtest with given params."""
        pass

    def param_sweep(self, tickers, start_date, end_date, param_grid: Dict) -> pd.DataFrame:
        """
        Run backtest over all combinations of param_grid.
        Returns DataFrame ranked by win_rate DESC, profit_factor DESC.
        """
        import itertools
        keys = list(param_grid.keys())
        values = list(param_grid.values())
        combos = list(itertools.product(*values))
        results = []

        for combo in combos:
            params = dict(zip(keys, combo))
            runs = self.backtest(tickers, start_date, end_date, params)
            wins = [r for r in runs if r.win]
            total = len(runs)
            if total == 0:
                continue
            wr = len(wins) / total * 100
            avg_win = sum(r.pnl_pct for r in wins) / len(wins) if wins else 0
            losses = [r for r in runs if not r.win]
            avg_loss = abs(sum(r.pnl_pct for r in losses) / len(losses)) if losses else 0
            pf = abs(avg_win / avg_loss) if avg_loss else float('inf')
            results.append({
                'params': params,
                'trades': total,
                'win_rate': wr,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'profit_factor': pf,
            })

        df = pd.DataFrame(results)
        return df.sort_values(['win_rate', 'profit_factor'], ascending=[False, False])
