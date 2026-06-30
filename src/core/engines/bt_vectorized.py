"""
Vectorized Backtest Module
Fast signal-based PnL calculation without RiskManager integration.
"""

import pandas as pd
import numpy as np
import logging
from typing import Dict, Optional


class VectorizedBacktest:
    """
    Vectorized backtesting engine for fast signal-based strategy evaluation.
    
    Uses numpy vectorization for maximum performance.
    No RiskManager integration - pure signal-driven execution.
    """
    
    def __init__(self):
        """Initialize vectorized backtest engine."""
        self.logger = logging.getLogger(__name__)
    
    def run(self, df: pd.DataFrame, multiplier: float, commission: float, slippage: float,
            initial_capital: float,
            initial_margin: float, maintenance_margin_rate: float = 0.8,
            allow_lunch: bool = True, allow_overnight: bool = True,
            execution_mode: str = 'Close', risk_target: float = 0.02, sl_pct: float = 0.0,
            max_lots: int = 20, pressure_test: bool = False, use_adx_filter: bool = False,
            custom_signals: Optional[pd.Series] = None) -> Dict:
        """
        Execute vectorized backtest.

        IMPORTANT: This engine is a pressure-test plugin.
        It returns only aggregate metrics (Net Profit, Drawdown, etc.).
        It does NOT produce trade-level data. Use EventDrivenBacktest for
        high-fidelity standard backtests.
        
        Args:
            df: DataFrame with 'close' and 'factor' columns
            multiplier: Contract multiplier (e.g., 25 for FCPO, 50 for FKLI)
            commission: Commission per lot
            slippage: Slippage in ticks
            initial_capital: Starting capital
            initial_margin: Initial margin per lot
            maintenance_margin_rate: Margin call threshold (default 0.8)
            allow_lunch: Allow positions during lunch hours
            allow_overnight: Allow overnight positions
            execution_mode: 'Close' or 'Next Open'
            risk_target: Risk percentage for position sizing (0 = fixed 1 lot)
            sl_pct: Stop loss percentage (0 = off)
            max_lots: Maximum lots per position
            pressure_test: Set to True when called from run_pressure_test dispatcher
            use_adx_filter: Set to True to enable ADX regime filtering
        
        Returns:
            Dictionary with aggregate metrics only: metrics, signals.
            Does NOT contain 'trades' or detailed equity_curve.
        """
        # Normalize execution mode
        if execution_mode and 'Next Open' in execution_mode:
            execution_mode = 'Next Open'
        else:
            execution_mode = 'Close'

        if not pressure_test:
            self.logger.warning(
                "[VECTORIZED] Called without pressure_test=True. "
                "This engine must only be used for slippage pressure scanning. "
                "Use EventDrivenBacktest for standard backtests."
            )
        
        # 1. Prepare Data
        df = self._prepare_dataframe(df)
        
        # Resolve tick_size from AssetConfig or fallback
        tick_size = 1.0
        if 'symbol' in df.columns:
            sym = str(df['symbol'].iloc[0]).upper()
            if "FKLI" in sym:
                tick_size = 0.5
            elif "FCPO" in sym:
                tick_size = 1.0
        else:
            if multiplier == 50.0:
                tick_size = 0.5
            elif multiplier == 25.0:
                tick_size = 1.0

        # 2. Calculate Risk Indicators
        if 'atr' not in df.columns:
            df['atr'] = self._calculate_atr(df)
        if 'adx' not in df.columns:
            df['adx'] = self._calculate_adx(df)
            
        # Prevent look-ahead bias: 
        # Shift ATR so that when evaluating conditions/stops during bar T, 
        # we only use volatility information known at the end of bar T-1.
        df['atr'] = df['atr'].shift(1).fillna(0)
        
        # 3. Generate Signals
        if custom_signals is not None:
            df['signal'] = custom_signals.fillna(0).astype(int)
        else:
            if 'signal' not in df.columns:
                df['signal'] = 0
            df['signal'] = df['signal'].fillna(0).astype(int)
            
            # Apply ADX Filter if enabled (Bug 5 - only blocks new entries and reversals)
            if use_adx_filter:
                prev_sig = df['signal'].shift(1).fillna(0).astype(int)
                is_new_entry = (df['signal'] != 0) & (df['signal'] != prev_sig)
                df['signal'] = np.where(is_new_entry & (df['adx'] < 20), 0, df['signal'])
            
            # 4. Apply Trading Hours Filter
            df = self._filter_trading_hours(df, allow_lunch, allow_overnight)
        
        # 5. Position Sizing
        df = self._calculate_position_size(df, risk_target, initial_capital, multiplier, max_lots)
        
        # 6. Execution & PnL Logic
        df = self._calculate_pnl(df, execution_mode, multiplier, sl_pct, commission, slippage, tick_size, allow_lunch, allow_overnight)
        
        # Calculate total trades before position truncation by liquidation
        entry_mask = (df['pos'] != 0) & (df['pos'] != df['pos'].shift(1).fillna(0))
        total_trades = int(entry_mask.sum())
        
        # 7. Equity Curve & Margin (internal only — not exposed in return dict)
        df = self._calculate_equity_and_margin(df, initial_capital, initial_margin, maintenance_margin_rate, tick_size, multiplier, slippage, execution_mode)
        
        # 8. Calculate aggregate metrics (NO trade-level data)
        metrics = self._calculate_metrics(df, initial_capital, total_trades=total_trades)
        
        # Return aggregate-only result dict — no 'trades', no 'equity_curve'
        return {
            "metrics": metrics,
            "signals": df['signal'],
        }
    
    def _prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Prepare and validate DataFrame."""
        # Handle column name variations
        if 'close' not in df.columns:
            for col in ['Close', 'CLOSE', 'price', 'Price', 'last', 'Last']:
                if col in df.columns:
                    df = df.rename(columns={col: 'close'})
                    break
        
        # Robust ADX/ATR detection (handle suffixes from AlphaEngine)
        if 'adx' not in df.columns:
            for col in df.columns:
                if str(col).lower().startswith('adx_'):
                    df['adx'] = df[col]
                    break
        
        if 'atr' not in df.columns:
            for col in df.columns:
                if str(col).lower().startswith('atr_'):
                    df['atr'] = df[col]
                    break

        if 'open' not in df.columns: df['open'] = df['close']
        if 'high' not in df.columns: df['high'] = df['close']
        if 'low' not in df.columns: df['low'] = df['close']
        if 'last' not in df.columns: df['last'] = df['close']
        
        if not {'close', 'factor'}.issubset(df.columns):
            raise ValueError(f"DataFrame must contain 'close' and 'factor' columns.\nFound: {list(df.columns)}")
        
        df = df.copy()
        if 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'])
            df = df.set_index('datetime')
        
        return df
    
    def _calculate_atr(self, df: pd.DataFrame, window: int = 14) -> pd.Series:
        """Calculate Average True Range (ATR)."""
        high = df['high']
        low = df['low']
        close = df['close']
        prev_close = close.shift(1)
        
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1/window, min_periods=window, adjust=False).mean()
        return atr.fillna(0)
    
    def _calculate_adx(self, df: pd.DataFrame, window: int = 14) -> pd.Series:
        """Calculate Average Directional Index (ADX)."""
        high = df['high']
        low = df['low']
        close = df['close']
        
        up_move = high.diff()
        down_move = low.diff().mul(-1)
        
        pos_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        neg_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        
        # Wilder's Smoothing for ADX components
        pos_dm = pd.Series(pos_dm, index=df.index).ewm(alpha=1/window, min_periods=window, adjust=False).mean()
        neg_dm = pd.Series(neg_dm, index=df.index).ewm(alpha=1/window, min_periods=window, adjust=False).mean()
        
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1/window, min_periods=window, adjust=False).mean()
        
        pos_di = 100 * (pos_dm / atr)
        neg_di = 100 * (neg_dm / atr)
        
        # Avoid division by zero
        denom = pos_di + neg_di
        denom = denom.replace(0, np.nan)
        
        dx = 100 * (pos_di - neg_di).abs() / denom
        adx = dx.ewm(alpha=1/window, min_periods=window, adjust=False).mean().fillna(0)
        return adx
    
    def _filter_trading_hours(self, df: pd.DataFrame, allow_lunch: bool, 
                              allow_overnight: bool) -> pd.DataFrame:
        """Filter trading hours to avoid gap risk."""
        if 'datetime' not in df.columns and not isinstance(df.index, pd.DatetimeIndex):
            return df
        
        df = df.copy()
        if 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', drop=False, inplace=True)
        
        times = df.index.time
        
        if not allow_lunch:
            lunch_start = pd.Timestamp("12:30").time()
            mask_lunch_exit = (times == lunch_start)
            if mask_lunch_exit.any():
                df.loc[mask_lunch_exit, 'signal'] = 0
        
        if not allow_overnight:
            market_close = pd.Timestamp("18:00").time()
            night_close = pd.Timestamp("23:30").time()
            
            mask_day_exit = (times == market_close)
            mask_night_exit = (times == night_close)
            
            if mask_day_exit.any():
                df.loc[mask_day_exit, 'signal'] = 0
            if mask_night_exit.any():
                df.loc[mask_night_exit, 'signal'] = 0
        
        return df
    
    def _calculate_position_size(self, df: pd.DataFrame, risk_target: float,
                                 initial_capital: float, multiplier: float,
                                 max_lots: int) -> pd.DataFrame:
        """Calculate position size based on risk target."""
        if risk_target > 0:
            # Volatility-based position sizing
            risk_amount = initial_capital * (risk_target / 100.0)
            contract_size = (df['atr'] * 2.0) * multiplier
            contract_size = contract_size.replace(0, np.inf)
            
            lots = risk_amount / contract_size
            lots = lots.fillna(0).astype(int)
            # Align with RiskManager: clamp to minimum of 1 lot if contract_size is valid and finite
            lots_clamped = np.where((contract_size > 0) & (contract_size < np.inf), np.maximum(lots, 1), lots)
            lots = pd.Series(lots_clamped, index=df.index).clip(upper=max_lots)
            
            df['pos_raw'] = df['signal'] * lots
        else:
            # Default 1 lot per signal
            df['pos_raw'] = df['signal']
        
        return df
    def _calculate_pnl(self, df: pd.DataFrame, execution_mode: str, multiplier: float,
                       sl_pct: float, commission: float, slippage: float, tick_size: float = 1.0,
                       allow_lunch: bool = True, allow_overnight: bool = True) -> pd.DataFrame:
        """Calculate PnL with optional stop loss and symmetrical price-embedded slippage."""
        # Identify force close bars (Bug 6)
        times = df.index.time
        force_close_mask = pd.Series(False, index=df.index)
        if not allow_lunch:
            lunch_start = pd.Timestamp("12:30").time()
            force_close_mask |= (times == lunch_start)
        if not allow_overnight:
            market_close = pd.Timestamp("18:00").time()
            night_close = pd.Timestamp("23:30").time()
            force_close_mask |= (times == market_close) | (times == night_close)
            
        # Position Shift Logic
        df['pos'] = df['pos_raw'].shift(1).fillna(0)
        # Prevent Next Open time drift: force position to 0 on T+1 if T was force closed
        prev_force_close = force_close_mask.shift(1).fillna(False)
        df['pos'] = np.where(prev_force_close, 0, df['pos'])

        df['exit_type'] = 'Signal'

        # 1. Get raw entry price
        if execution_mode == 'Next Open':
            raw_entry = df['open']
        else:
            raw_entry = df['close'].shift(1)
        
        # Symmetrical discretization on entry (Bug 3)
        # Buying price (Long Entry): Ceil((price + slippage) / tick_size) * tick_size
        # Selling price (Short Entry): Floor((price - slippage) / tick_size) * tick_size
        df['entry_price'] = np.where(
            df['pos'] > 0,
            np.ceil((raw_entry + slippage) / tick_size) * tick_size,
            np.where(
                df['pos'] < 0,
                np.floor((raw_entry - slippage) / tick_size) * tick_size,
                raw_entry
            )
        )
        
        # Identify first bar of trade to use entry price
        position_changed = df['pos'] != df['pos'].shift(1).fillna(0)
        first_bar_mask = (df['pos'] != 0) & position_changed
        
        # Group trade entry prices
        df['trade_id'] = (df['pos'] != df['pos'].shift(1).fillna(0)).cumsum()
        entry_prices = df.groupby('trade_id')['entry_price'].transform('first')
        df['entry_price'] = entry_prices
        
        if execution_mode == 'Next Open':
            standard_ref = df['open']
        else:
            standard_ref = df['close'].shift(1)
            
        df['ref_price'] = np.where(first_bar_mask, df['entry_price'], standard_ref)
        
        # 2. Get current price
        # Symmetrical exit price logic on force close bars in Next Open mode (Bug 6)
        if execution_mode == 'Next Open':
            current_price = np.where(force_close_mask, df['close'], df['open'].shift(-1))
            df['exec_price'] = df['open']
        else:
            current_price = df['close']
            df['exec_price'] = df['close']
            
        # 3. Identify exit bars (either trade ended, or position size/direction changed)
        pos_next = df['pos'].shift(-1).fillna(0)
        is_exit_bar = (df['pos'] != 0) & (pos_next != df['pos'])
        
        # Discretize exit price on exit bars (Bug 3)
        # Selling price (Long Exit): Floor((price - slippage) / tick_size) * tick_size
        # Buying price (Short Exit): Ceil((price + slippage) / tick_size) * tick_size
        exit_price_discretized = np.where(
            df['pos'] > 0,
            np.floor((current_price - slippage) / tick_size) * tick_size,
            np.where(
                df['pos'] < 0,
                np.ceil((current_price + slippage) / tick_size) * tick_size,
                current_price
            )
        )
        current_price_adjusted = np.where(is_exit_bar, exit_price_discretized, current_price)
        
        if sl_pct > 0:
            df = self._apply_stop_loss(df, sl_pct, multiplier, execution_mode, slippage, tick_size, force_close_mask, current_price_adjusted)
        else:
            # Basic PnL with symmetrical price-embedded slippage
            df['gross_pnl'] = (current_price_adjusted - df['ref_price']) * multiplier * df['pos']
        
        # Transaction Costs
        df['pos_change'] = df['pos'].diff().abs().fillna(0)
        cost_per_lot = commission
        df['cost'] = df['pos_change'] * cost_per_lot
        df['net_pnl'] = df['gross_pnl'] - df['cost']
        
        df['gross_pnl'] = df['gross_pnl'].fillna(0.0)
        df['net_pnl'] = df['net_pnl'].fillna(0.0)
        
        return df
    
    def _apply_stop_loss(self, df: pd.DataFrame, sl_pct: float, multiplier: float,
                          execution_mode: str, slippage: float = 0.0, tick_size: float = 1.0,
                          force_close_mask: Optional[pd.Series] = None,
                          current_price_adjusted: Optional[pd.Series] = None) -> pd.DataFrame:
        """Apply vectorized stop loss logic without look-ahead bias and with symmetrical gap exits."""
        # Always compute trade_id / entry_price / ref_price to ensure freshness (e.g. if DataFrame reused)
        df['trade_id'] = (df['pos'] != df['pos'].shift(1).fillna(0)).cumsum()
            
        if execution_mode == 'Next Open':
            raw_entry = df['open']
        else:
            raw_entry = df['close'].shift(1)
        
        df['entry_price'] = np.where(
            df['pos'] > 0,
            np.ceil((raw_entry + slippage) / tick_size) * tick_size,
            np.where(
                df['pos'] < 0,
                np.floor((raw_entry - slippage) / tick_size) * tick_size,
                raw_entry
            )
        )
        entry_prices = df.groupby('trade_id')['entry_price'].transform('first')
        df['entry_price'] = entry_prices
            
        position_changed = df['pos'] != df['pos'].shift(1).fillna(0)
        first_bar_mask = (df['pos'] != 0) & position_changed
        if execution_mode == 'Next Open':
            standard_ref = df['open']
        else:
            standard_ref = df['close'].shift(1)
        df['ref_price'] = np.where(first_bar_mask, df['entry_price'], standard_ref)

        if force_close_mask is None:
            force_close_mask = pd.Series(False, index=df.index)
            
        if current_price_adjusted is None:
            current_price = df['open'].shift(-1) if execution_mode == 'Next Open' else df['close']
            pos_next = df['pos'].shift(-1).fillna(0)
            is_exit_bar = (df['pos'] != 0) & (pos_next != df['pos'])
            exit_price_discretized = np.where(
                df['pos'] > 0,
                np.floor((current_price - slippage) / tick_size) * tick_size,
                np.where(
                    df['pos'] < 0,
                    np.ceil((current_price + slippage) / tick_size) * tick_size,
                    current_price
                )
            )
            current_price_adjusted = np.where(is_exit_bar, exit_price_discretized, current_price)

        # 1. Calculate SL prices
        df['sl_prices'] = np.where(df['pos'] > 0,
                                   df['entry_price'] * (1 - sl_pct/100.0),
                                   df['entry_price'] * (1 + sl_pct/100.0))
        
        # 2. Identify Signal Generation Bar (Signal Bar)
        # In Close mode, T is signal bar (pos[T]=0, pos[T+1]!=0)
        if execution_mode == 'Close':
            pos_raw = df['pos_raw'] if 'pos_raw' in df.columns else df['pos'].shift(-1).fillna(0)
            signal_bar_mask = (df['pos'] == 0) & (pos_raw.fillna(0) != 0)
        else:
            signal_bar_mask = pd.Series(False, index=df.index)
        
        # 3. Check for hits with look-ahead bias eliminated (Signal Bar is exempted, First Holding Bar is checked!)
        if execution_mode == 'Close':
            hit_long = (df['pos'] > 0) & (df['low'] < df['sl_prices']) & (~signal_bar_mask)
            hit_short = (df['pos'] < 0) & (df['high'] > df['sl_prices']) & (~signal_bar_mask)
        else:
            hit_long = (df['pos'] > 0) & (df['low'] < df['sl_prices'])
            hit_short = (df['pos'] < 0) & (df['high'] > df['sl_prices'])
            
        df['is_sl_triggered'] = hit_long | hit_short
        
        # 4. Cumulative hits per trade to stop out subsequent bars
        is_hit = df['is_sl_triggered']
        cum_hits = pd.Series(is_hit, index=df.index).groupby(df['trade_id']).cumsum()
        first_hit_mask = (cum_hits == 1) & (is_hit)
        post_hit_mask = (cum_hits > 0) & (~first_hit_mask)
        
        df['exit_type'] = 'Signal'
        df.loc[first_hit_mask, 'exit_type'] = 'Intra-bar SL'
        df.loc[post_hit_mask, 'exit_type'] = 'Post SL'
        
        # Apply stop-out to subsequent bars (position goes to 0)
        df.loc[post_hit_mask, 'pos'] = 0
        
        # 5. Symmetrical Discretization on stop exits (Bug 3)
        sl_exit_long = np.floor((df['sl_prices'] - slippage) / tick_size) * tick_size
        sl_exit_short = np.ceil((df['sl_prices'] + slippage) / tick_size) * tick_size
        
        # Long Exit Gap (Sell) floor discretization
        sl_gap_long_exit = np.floor((df['open'] - slippage) / tick_size) * tick_size
        # Short Exit Gap (Buy) ceil discretization
        sl_gap_short_exit = np.ceil((df['open'] + slippage) / tick_size) * tick_size
        
        sl_exit_prices = np.where(
            df['pos'] > 0,
            np.where(df['open'] < df['sl_prices'], sl_gap_long_exit, sl_exit_long),
            np.where(df['open'] > df['sl_prices'], sl_gap_short_exit, sl_exit_short)
        )
            
        # Calculate standard and stop PnL
        df['normal_pnl'] = (current_price_adjusted - df['ref_price']) * multiplier * df['pos']
        df['sl_pnl'] = (sl_exit_prices - df['ref_price']) * multiplier * df['pos']
        
        # Assemble final gross PnL
        df['gross_pnl'] = np.where(
            df['exit_type'] == 'Intra-bar SL',
            df['sl_pnl'],
            np.where(
                df['exit_type'] == 'Post SL',
                0.0,
                df['normal_pnl']
            )
        )
        
        return df
    
    def _calculate_equity_and_margin(self, df: pd.DataFrame, initial_capital: float,
                                     initial_margin: float, maintenance_margin_rate: float,
                                     tick_size: float = 1.0, multiplier: float = 25.0,
                                     slippage: float = 0.0, execution_mode: str = 'Close') -> pd.DataFrame:
        """Calculate equity curve and margin requirements with real-time liquidation truncation."""
        n = len(df)
        pos = df['pos'].values.copy()
        gross_pnl = df['gross_pnl'].values.copy()
        cost = df['cost'].values.copy()
        net_pnl = df['net_pnl'].values.copy()
        
        equity = np.zeros(n)
        used_margin = np.zeros(n)
        maint_level = np.zeros(n)
        is_liquidated = np.zeros(n, dtype=bool)
        
        # Extract cost_per_lot
        mask = df['pos_change'] > 0
        cost_per_lot = (df.loc[mask, 'cost'] / df.loc[mask, 'pos_change']).iloc[0] if mask.any() else 0.0
        
        current_equity = initial_capital
        liquidated = False
        
        for i in range(n):
            if liquidated:
                pos[i] = 0
                gross_pnl[i] = 0.0
                if i > 0 and pos[i-1] != 0:
                    pos_change = abs(pos[i] - pos[i-1])
                    cost[i] = pos_change * cost_per_lot
                else:
                    cost[i] = 0.0
                net_pnl[i] = gross_pnl[i] - cost[i]
                
            current_equity = initial_capital + net_pnl[:i+1].sum()
            equity[i] = current_equity
            
            # Check margin requirement
            used_margin[i] = abs(pos[i]) * initial_margin
            maint_level[i] = used_margin[i] * maintenance_margin_rate
            
            # Trigger liquidation if equity falls below maintenance margin baseline AND we hold a position
            if not liquidated and pos[i] != 0 and current_equity < maint_level[i]:
                liquidated = True
                is_liquidated[i] = True
                
                # Check if it was an open-gap breach
                if 'open' in df.columns and 'ref_price' in df.columns and 'close' in df.columns:
                    prev_net_pnl_sum = net_pnl[:i].sum() if i > 0 else 0.0
                    open_price = df['open'].iloc[i]
                    ref_price = df['ref_price'].iloc[i]
                    close_price = df['close'].iloc[i]
                    
                    floating_pnl_open = (open_price - ref_price) * multiplier * pos[i]
                    equity_at_open = initial_capital + prev_net_pnl_sum + floating_pnl_open
                    
                    # Symmetrical Open Gap Breach Check
                    high_water_mark = initial_capital + max(0.0, net_pnl[:i].sum()) if i > 0 else initial_capital
                    daily_baseline = initial_capital + net_pnl[:i].sum() if i > 0 else initial_capital
                    
                    peak_drawdown_open = (high_water_mark - equity_at_open) / high_water_mark if high_water_mark > 0 else 0.0
                    daily_drawdown_open = (daily_baseline - equity_at_open) / daily_baseline if daily_baseline > 0 else 0.0
                    
                    if (equity_at_open < maint_level[i]) or (peak_drawdown_open > 0.35) or (daily_drawdown_open > 0.20):
                        fill_price = open_price
                    else:
                        fill_price = close_price
                        
                    # Symmetrical tick size grid discretization for gap/intraday liquidation
                    if pos[i] > 0:  # Long: Floor
                        exit_price = np.floor((fill_price - slippage) / tick_size) * tick_size
                    else:  # Short: Ceil
                        exit_price = np.ceil((fill_price + slippage) / tick_size) * tick_size
                    
                    # Correctly record realized PnL on liquidation bar (NO wiping to zero!)
                    gross_pnl[i] = (exit_price - ref_price) * multiplier * pos[i]
                else:
                    # Graceful fallback: keep the gross_pnl[i] as is in the mock dataframe
                    pass
                
                # Truncate position immediately
                pos[i] = 0
                pos_change = abs(pos[i] - pos[i-1]) if i > 0 else 0.0
                cost[i] = pos_change * cost_per_lot
                net_pnl[i] = gross_pnl[i] - cost[i]
                
                # Re-calculate equity for this bar after truncation
                current_equity = initial_capital + net_pnl[:i+1].sum()
                equity[i] = current_equity
                used_margin[i] = 0.0
                maint_level[i] = 0.0
                
        df['pos'] = pos
        df['gross_pnl'] = gross_pnl
        df['cost'] = cost
        df['net_pnl'] = net_pnl
        df['equity'] = equity
        df['used_margin'] = used_margin
        df['maint_level'] = maint_level
        df['is_liquidated'] = is_liquidated
        
        # Update pos_change to match the truncated position
        df['pos_change'] = df['pos'].diff().abs().fillna(0)
        
        return df
    
    def _calculate_metrics(self, df: pd.DataFrame, initial_capital: float, total_trades: Optional[int] = None) -> Dict:
        """
        Calculate aggregate performance metrics for pressure tests.
        Returns only top-level summary metrics: Net Profit, Drawdown, Ratios, Trade Count.
        No trade-level data is exposed.
        """
        total_net_profit = df['net_pnl'].sum()
        final_equity = df['equity'].iloc[-1] if not df.empty else initial_capital
        if total_trades is None:
            entry_mask = (df['pos'] != 0) & (df['pos'] != df['pos'].shift(1).fillna(0))
            total_trades = int(entry_mask.sum())
        
        # Drawdown - directly on raw bar-by-bar df['equity'] (Bug 8)
        df['peak'] = df['equity'].cummax()
        df['drawdown'] = df['equity'] - df['peak']
        df['drawdown_pct'] = df['drawdown'] / df['peak']
        
        max_drawdown_rm = df['drawdown'].min()
        max_drawdown_pct = df['drawdown_pct'].min()
        
        # Sharpe Ratio (daily returns, annualized √252) (Bug 9)
        if isinstance(df.index, pd.DatetimeIndex) and len(df) > 2:
            daily_equity = df['equity'].resample('D').last().dropna()
            daily_ret = daily_equity.pct_change().dropna()
            mean_ret = daily_ret.mean()
            std_ret = daily_ret.std()
            sharpe = (mean_ret / std_ret) * np.sqrt(252) if std_ret > 0 else 0.0
        else:
            daily_ret = df['equity'].pct_change().dropna()
            mean_ret = daily_ret.mean()
            std_ret = daily_ret.std()
            sharpe = (mean_ret / std_ret) * np.sqrt(252) if std_ret > 0 else 0.0
        
        # Calmar Ratio
        days = (df.index[-1] - df.index[0]).days if len(df) > 1 else 1
        years = max(days / 365.25, 0.01)
        annual_return_pct = (final_equity / initial_capital) ** (1 / years) - 1 if final_equity > 0 else -1.0
        calmar = annual_return_pct / abs(max_drawdown_pct) if max_drawdown_pct != 0 else 0.0
        
        # Margin Status
        first_liquidation = df[df['is_liquidated']].first_valid_index()
        liquidation_msg = "Safe" if not first_liquidation else f"MARGIN CALL at {first_liquidation}!"
        
        if total_trades == 0:
            raise Exception("Total Trades recorded: 0. Check filters or signal logic.")
        
        return {
            "Total Net Profit": round(total_net_profit, 2),
            "Max Drawdown (RM)": round(abs(max_drawdown_rm), 2),
            "Max Drawdown %": round(abs(max_drawdown_pct) * 100, 2),
            "Sharpe Ratio": round(sharpe, 3),
            "Calmar Ratio": round(calmar, 3),
            "Total Trades": total_trades,
            "Margin Status": liquidation_msg,
        }


# Auto-register to engine registry on module load
try:
    from .engine_registry import EngineRegistry
    EngineRegistry.register('vectorized', VectorizedBacktest)
except ImportError:
    pass  # Registry not available yet
