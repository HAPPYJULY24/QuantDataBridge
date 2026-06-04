"""
BacktestEngine Facade
Maintains backward compatibility with existing code while dispatching to new modules.
"""

import pandas as pd
from typing import Dict, Optional
from src.core.engines.bt_vectorized import VectorizedBacktest
from src.core.engines.bt_event_driven import EventDrivenBacktest
from .signal_generator import SignalFactory


class BacktestEngine:
    """
    Facade for backtesting engine.
    
    Dispatches to either VectorizedBacktest or EventDrivenBacktest based on configuration.
    Maintains backward compatibility with existing run_backtest() signature.
    """
    
    def __init__(self, signal_emitter=None):
        """
        Initialize backtest engine facade.
        
        Args:
            signal_emitter: Optional PyQt6 signal emitter for UI updates (for event-driven mode)
        """
        self.vectorized = VectorizedBacktest()
        self.event_driven = EventDrivenBacktest(signal_emitter=signal_emitter)
        self.signal_emitter = signal_emitter
    
    def run_standard_backtest(self, df: pd.DataFrame, multiplier: float, commission: float, slippage: float,
                     initial_capital: float, upper_bound: float, lower_bound: float,
                     initial_margin: float, maintenance_margin_rate: float = 0.8,
                     allow_lunch: bool = True, allow_overnight: bool = True,
                     execution_mode: str = 'Close', sl_pct: float = 0.0,
                     risk_params: Optional[dict] = None, asset_symbol: str = "ASSET") -> Dict:
        """
        Execute high-fidelity standard backtest.
        Strictly bounded to EventDrivenBacktest engine to guarantee detailed audit_log.
        
        Args:
            df: DataFrame with OHLCV and factor columns
            multiplier: Contract multiplier
            commission: Commission per lot
            slippage: Slippage in ticks
            initial_capital: Starting capital
            upper_bound: Upper threshold for long signals
            lower_bound: Lower threshold for short signals
            initial_margin: Initial margin per lot
            maintenance_margin_rate: Margin call threshold
            allow_lunch: Allow positions during lunch
            allow_overnight: Allow overnight positions
            execution_mode: 'Close' or 'Next Open'
            sl_pct: Stop loss percentage
            risk_params: Risk parameters dictionary
            asset_symbol: Asset symbol
        
        Returns:
            Dictionary with metrics, equity_curve, signals, audit_log, trades
        """
        from logic.risk_manager import RiskManager
        
        if risk_params is None:
            risk_params = {}
        
        # Inject sl_pct into risk_params if provided
        if sl_pct > 0:
            risk_params['sl_pct'] = sl_pct
            
        # 1. Pipeline: Generate Signals
        strategy = risk_params.get('strategy', 'Mean Reversion')
        generator = SignalFactory.create(strategy)
        df['signal'] = generator.generate(
            df, 
            upper_bound=upper_bound, 
            lower_bound=lower_bound,
            signal_logic_code=risk_params.get('signal_logic_code')
        )
        
        # 2. Execution Engine
        return self.event_driven.run(
            df=df,
            asset_symbol=asset_symbol,
            RiskManagerClass=RiskManager,
            multiplier=multiplier,
            commission=commission,
            slippage=slippage,
            initial_capital=initial_capital,
            initial_margin=initial_margin,
            maintenance_margin_rate=maintenance_margin_rate,
            allow_lunch=allow_lunch,
            allow_overnight=allow_overnight,
            execution_mode=execution_mode,
            risk_params=risk_params
        )
    
    def audit_lookahead(self, df: pd.DataFrame, params: dict) -> Dict:
        """
        Audit for lookahead bias by shifting factor by 1 bar and comparing PnL.
        If profit collapses when shifted, signal is likely using future data.
        
        Args:
            df: DataFrame with OHLCV and factor
            params: Dictionary of backtest parameters
            
        Returns:
            Dict with warning, base_profit, audit_profit, diff_pct
        """
        # 1. Base Run (Original)
        # Using vectorized backtest here to keep audit fast, as it runs multiple times.
        def _quick_run(data: pd.DataFrame):
            # Pipeline preprocessing
            strategy = params.get('strategy', 'Mean Reversion')
            generator = SignalFactory.create(strategy)
            
            # The signal must be generated FRESH over the given 'data'
            data['signal'] = generator.generate(
                data, 
                upper_bound=params.get('upper_bound', 0.5), 
                lower_bound=params.get('lower_bound', -0.5),
                signal_logic_code=params.get('signal_logic_code')
            )
            
            return self.vectorized.run(
                df=data,
                multiplier=params.get('multiplier', 25.0),
                commission=params.get('commission', 15.0),
                slippage=params.get('slippage', 1.0),
                initial_capital=params.get('initial_capital', 100000.0),
                initial_margin=params.get('initial_margin', 5000.0),
                maintenance_margin_rate=params.get('maintenance_margin_rate', 0.8),
                allow_lunch=params.get('allow_lunch', True),
                allow_overnight=params.get('allow_overnight', True),
                execution_mode=params.get('execution_mode', 'Close'),
                risk_target=params.get('risk_target', 0.0),
                sl_pct=params.get('sl_pct', 0.0),
                max_lots=params.get('max_lots', 20),
                pressure_test=True,  # Audit uses vectorized as a fast sub-routine
                use_adx_filter=params.get('use_adx_filter', False)
            )
            
        base_res = _quick_run(df.copy())
        base_profit = base_res['metrics']['Total Net Profit']
        
        # 2. Audited Run (Shift Factor +1)
        # Shift factor means signal t+1 is now based on factor t
        df_audit = df.copy()
        df_audit['factor'] = df_audit['factor'].shift(1)
        
        audit_res = _quick_run(df_audit)
        audit_profit = audit_res['metrics']['Total Net Profit']
        
        # 3. Compare Results
        diff_pct = 0.0
        if abs(base_profit) > 1.0: # Ignore noise/zero profit cases
            diff_pct = (base_profit - audit_profit) / abs(base_profit)
        
        # Set warning if profit drops by more than 50%
        warning = (diff_pct > 0.5) and (base_profit > 100) # Only warn for profitable cases
        
        return {
            'warning': warning,
            'base_profit': base_profit,
            'audit_profit': audit_profit,
            'diff_pct': diff_pct
        }

    def run_pressure_test(self, df: pd.DataFrame, params: dict) -> list:
        """
        Slippage Sensitivity Test (Pressure Test).
        Uses VectorizedBacktest engine. Returns aggregated metrics without detailed logs.
        
        Args:
            df: OHLCV DataFrame
            params: Base parameters
            
        Returns:
            List of result dictionaries for each slippage level
        """
        sensitivity_results = []
        slippage_levels = [0, 1, 2, 3, 5, 8] # Slippage in ticks
        
        strategy = params.get('strategy', 'Mean Reversion')
        generator = SignalFactory.create(strategy)
        # Generate signal column ONCE for all slippage runs since signals don't change by slippage
        df['signal'] = generator.generate(
            df, 
            upper_bound=params.get('upper_bound', 0.5), 
            lower_bound=params.get('lower_bound', -0.5),
            signal_logic_code=params.get('signal_logic_code')
        )
        
        for s in slippage_levels:
            res = self.vectorized.run(
                df=df,
                multiplier=params.get('multiplier', 25.0),
                commission=params.get('commission', 15.0),
                slippage=float(s),
                initial_capital=params.get('initial_capital', 100000.0),
                initial_margin=params.get('initial_margin', 5000.0),
                maintenance_margin_rate=params.get('maintenance_margin_rate', 0.8),
                allow_lunch=params.get('allow_lunch', True),
                allow_overnight=params.get('allow_overnight', True),
                execution_mode=params.get('execution_mode', 'Close'),
                risk_target=params.get('risk_target', 0.0),
                sl_pct=params.get('sl_pct', 0.0),
                max_lots=params.get('max_lots', 20),
                pressure_test=True,  # Hard-bound: only vectorized engine for pressure tests
                use_adx_filter=params.get('use_adx_filter', False)
            )
            metrics = res['metrics']
            
            sensitivity_results.append({
                'Slippage': s,
                'Net Profit': metrics.get('Total Net Profit', 0.0),
                'MDD (%)': metrics.get('Max Drawdown %', 0.0),
                'Calmar': metrics.get('Calmar Ratio', 0.0),
                'Trades': metrics.get('Total Trades', 0)
            })
            
        return sensitivity_results

    def generate_trade_log(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Extract trade-by-trade log from vectorized results.
        
        Args:
            df: DataFrame returned by vectorized.run (equity_curve)
            
        Returns:
            DataFrame containing trade log
        """
        if 'pos' not in df.columns or df.empty:
            return pd.DataFrame()
        
        # Identify trade IDs if not already there
        if 'trade_id' not in df.columns:
            df['trade_id'] = (df['pos'] != df['pos'].shift(1).fillna(0)).cumsum()
        
        # Filter for rows where we have a position
        active_df = df[df['pos'] != 0].copy()
        if active_df.empty:
            return pd.DataFrame()
            
        trades = []
        for tid, group in active_df.groupby('trade_id'):
            entry_row = group.iloc[0]
            exit_row = group.iloc[-1]
            
            # Net PnL is the sum of net_pnl for all bars in the trade
            # Note: This works because each bar's net_pnl is the pnl from previous bar to current
            net_pnl = group['net_pnl'].sum()
            
            trades.append({
                'entry_time': group.index[0],
                'exit_time': group.index[-1],
                'direction': 'Long' if entry_row['pos'] > 0 else 'Short',
                'lots': abs(entry_row['pos']),
                'entry_price': entry_row['exec_price'] if 'exec_price' in entry_row else entry_row['close'],
                'exit_price': exit_row['exec_price'] if 'exec_price' in exit_row else exit_row['close'],
                'net_pnl': net_pnl,
                'exit_reason': exit_row.get('exit_type', 'Signal')
            })
            
        return pd.DataFrame(trades)
    
    # Helper methods (delegated for backward compatibility)
    def filter_trading_hours(self, df: pd.DataFrame, allow_lunch: bool = False, allow_overnight: bool = False) -> pd.DataFrame:
        """Delegate to vectorized backtest."""
        return self.vectorized._filter_trading_hours(df, allow_lunch, allow_overnight)
    
    def calculate_atr(self, df: pd.DataFrame, window: int = 14) -> pd.Series:
        """Delegate to vectorized backtest."""
        return self.vectorized._calculate_atr(df, window)
    
    def calculate_adx(self, df: pd.DataFrame, window: int = 14) -> pd.Series:
        """Delegate to vectorized backtest."""
        return self.vectorized._calculate_adx(df, window)
