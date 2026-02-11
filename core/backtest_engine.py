
import pandas as pd
import numpy as np
import logging

class BacktestEngine:
    """
    Vectorized Backtest Engine for Futures (FCPO/FKLI).
    Phase 5.1 Upgrade: Robustness Audit, Next Open Execution, Slippage Sensitivity.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def filter_trading_hours(self, df: pd.DataFrame, allow_lunch: bool = False, allow_overnight: bool = False) -> pd.DataFrame:
        """
        Filter trading hours to avoid gap risk.
        FCPO Hours: 10:30-12:30, 14:30-18:00, (Optional Night 21:00-23:30)
        """
        if 'datetime' not in df.columns and not isinstance(df.index, pd.DatetimeIndex):
            return df
            
        df = df.copy()
        if 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'])
            df.set_index('datetime', drop=False, inplace=True)
            
        times = df.index.time
        
        if not allow_lunch:
            # Force close at 12:30
            lunch_start = pd.Timestamp("12:30").time()
            mask_lunch_exit = (times == lunch_start)
            if mask_lunch_exit.any():
                df.loc[mask_lunch_exit, 'signal'] = 0
                
        if not allow_overnight:
            # Force close at 18:00
            market_close = pd.Timestamp("18:00").time()
            night_close = pd.Timestamp("23:30").time()
            
            mask_day_exit = (times == market_close)
            mask_night_exit = (times == night_close)
            
            if mask_day_exit.any():
                df.loc[mask_day_exit, 'signal'] = 0
            if mask_night_exit.any():
                df.loc[mask_night_exit, 'signal'] = 0
                
        return df

    def calculate_atr(self, df: pd.DataFrame, window: int = 14) -> pd.Series:
        """
        Calculate Average True Range (ATR).
        TR = max(High-Low, abs(High-PrevClose), abs(Low-PrevClose))
        """
        high = df['high']
        low = df['low']
        close = df['close']
        prev_close = close.shift(1)
        
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=window).mean()
        return atr.fillna(0)

    def calculate_adx(self, df: pd.DataFrame, window: int = 14) -> pd.Series:
        """
        Calculate Average Directional Index (ADX).
        """
        high = df['high']
        low = df['low']
        close = df['close']
        
        up_move = high.diff()
        down_move = low.diff().mul(-1)
        
        pos_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        neg_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        
        pos_dm = pd.Series(pos_dm, index=df.index).ewm(alpha=1/window, min_periods=window).mean()
        neg_dm = pd.Series(neg_dm, index=df.index).ewm(alpha=1/window, min_periods=window).mean()
        
        # Calculate ATR for normalization (Wilder usually uses Smoothed TR, here EWM matches)
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1/window, min_periods=window).mean()
        
        pos_di = 100 * (pos_dm / atr)
        neg_di = 100 * (neg_dm / atr)
        
        dx = 100 * (pos_di - neg_di).abs() / (pos_di + neg_di)
        adx = dx.rolling(window=window).mean().fillna(0)
        return adx

    def run_backtest(self, df: pd.DataFrame, multiplier: float, commission: float, slippage: float, 
                     initial_capital: float, upper_bound: float, lower_bound: float,
                     initial_margin: float, maintenance_margin_rate: float = 0.8,
                     allow_lunch: bool = True, allow_overnight: bool = True,
                     execution_mode: str = 'Close',
                     risk_target: float = 0.0, # 0.0 = Off (Use fixed 1 lot? Or capital based?)
                     # Let's say if risk_target > 0, use Vol Targeting. Else use fixed capital? 
                     # Actually existing logic was naive. Let's assume risk_target defaults to 1.0 (100% equity?) NO.
                     # Default to 0.0 means 'Fixed 1 Lot' logic for backward compat? 
                     # Implementation Plan said Default 1.0 (1%). 
                     sl_pct: float = 0.0, # 0.0 = Off
                     use_adx_filter: bool = False,
                     max_lots: int = 20,
                     use_risk_manager: bool = False,
                     risk_params: dict = None):
        """
        Execute vectorized backtest with Risk Control and Robust execution modes.
        If use_risk_manager is True, switches to Iterative Mode for detailed audit.
        """
        # 1. Prepare Data
        if 'close' not in df.columns:
            for col in ['Close', 'CLOSE', 'price', 'Price', 'last', 'Last']:
                if col in df.columns:
                    df = df.rename(columns={col: 'close'})
                    break
        
        if 'open' not in df.columns: df['open'] = df['close']
        if 'high' not in df.columns: df['high'] = df['close']
        if 'low' not in df.columns: df['low'] = df['close']
        if 'last' not in df.columns: df['last'] = df['close']

        if not {'close', 'factor'}.issubset(df.columns):
            raise ValueError(f"Dataframe must contain 'close' and 'factor' columns.\nFound: {list(df.columns)}")
        
        df = df.copy()
        if 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'])
            df = df.set_index('datetime')
        
        # Calculate Risk Indicators (Needed for both modes)
        if 'atr' not in df.columns: df['atr'] = self.calculate_atr(df)
        if 'adx' not in df.columns: df['adx'] = self.calculate_adx(df)
        
        # Dispatch to Iterative Mode if Audit/Risk Manager is requested
        if use_risk_manager:
            from logic.risk_manager import RiskManager
            return self._run_iterative_backtest(
                df, RiskManager, 
                multiplier, commission, slippage, 
                initial_capital, upper_bound, lower_bound, 
                initial_margin, maintenance_margin_rate,
                allow_lunch, allow_overnight, execution_mode,
                risk_params if risk_params else {}
            )
            
        # --- Vectorized Mode (Existing Logic) ---
        # 3. Generate Signals

        conditions = [
            (df['factor'] > upper_bound),
            (df['factor'] < lower_bound)
        ]
        choices = [1, -1]
        raw_signal = np.select(conditions, choices, default=0)
        
        # ADX Regime Filter
        if use_adx_filter:
            # If ADX < 20, force signal to 0 (Stay Out)
            raw_signal = np.where(df['adx'] < 20, 0, raw_signal)
            
        df['signal'] = raw_signal
        
        # 4. Apply Trading Hours Filter
        df = self.filter_trading_hours(df, allow_lunch, allow_overnight)
        
        # 5. Position Sizing (Volatility Targeting)
        # If risk_target > 0, calculate Lots based on ATR
        # Else, assume 1 Lot (or simple capital allocation?) -> Let's default to 1 Lot if risk_target=0 for now.
        
        if risk_target > 0:
            # Target Exposure = Equity * Risk Target (e.g. 1% Risk) -> NO.
            # Vol Target usually means: Risk Amount = Equity * risk_target.
            # Contracts = Risk Amount / (ATR * Multiplier).
            # Example: Eq=100k, Risk=1% (1k). ATR=10pts. ValAtRisk per lot = 10*25 = 250.
            # Contracts = 1000 / 250 = 4 lots.
            
            # Need Rolling Equity approximation? 
            # Vectorized backtest usually uses Initial Capital for sizing to avoid path dependence loop.
            # Use Initial Capital for robustness.
            risk_amount = initial_capital * (risk_target / 100.0)
            contract_size = df['atr'] * multiplier
            # Avoid division by zero
            contract_size = contract_size.replace(0, np.inf) 
            
            lots = risk_amount / contract_size
            lots = lots.fillna(0).astype(int)
            lots = lots.clip(upper=max_lots)
            
            # Apply direction
            df['pos_raw'] = df['signal'] * lots
        else:
            # Default 1 Lot per signal
            df['pos_raw'] = df['signal']
            
        # 6. Execution & PnL Logic
        if execution_mode == 'Next Open':
            df['price_change'] = df['open'].diff()
            df['pos'] = df['pos_raw'].shift(2).fillna(0)
            df['exec_price'] = df['open']
        else:
            df['price_change'] = df['close'].diff()
            df['pos'] = df['pos_raw'].shift(1).fillna(0)
            df['exec_price'] = df['close']
            
        # 7. Intra-bar Stop Probe (Vectorized)
        # Only applies if sl_pct > 0
        df['exit_type'] = 'Signal' # Default
        
        if sl_pct > 0:
            # Identify Entry Price (Propagate forward)
            # This is tricky in pure vector. 
            # Approx: Use execution price of the bar where position CHANGED.
            # Then ffill.
            
            # Identify Trade Starts
            df['trade_id'] = (df['pos'] != df['pos'].shift(1).fillna(0)).cumsum()
            
            # Get Entry Price for each Trade ID
            # Groupby transform first?
            # 'exec_price' is the price at the current bar.
            # If pos changed at T, exec_price[T] is the entry price.
            # We need to broadcast this entry price to all bars with same trade_id.
            
            # Mask for bars where trade is active (pos != 0)
            active_mask = df['pos'] != 0
            
            # On trade start bar, entry_price is exec_price.
            # We can use groupby transform('first') on exec_price, grouped by trade_id?
            # Yes, but only for active trades.
            
            entry_prices = df.groupby('trade_id')['exec_price'].transform('first')
            df['entry_price'] = entry_prices
            
            # Calculate SL Price
            # Long: Entry * (1 - pct). Short: Entry * (1 + pct).
            # Note: pos can be +N or -N.
            
            sl_prices = np.where(df['pos'] > 0, 
                                 df['entry_price'] * (1 - sl_pct/100.0),
                                 df['entry_price'] * (1 + sl_pct/100.0))
                                 
            # Check for Hits
            # Hit if Long and Low < SL. Hit if Short and High > SL.
            hit_long = (df['pos'] > 0) & (df['low'] < sl_prices)
            hit_short = (df['pos'] < 0) & (df['high'] > sl_prices)
            is_hit = hit_long | hit_short
            
            # Masking subsequent bars in the same trade
            # If hit at T, then T+1, T+2... until Trade ID changes should be 0.
            # Also, at T, PnL is capped.
            
            # Cumulative hits per trade
            cum_hits = pd.Series(is_hit, index=df.index).groupby(df['trade_id']).cumsum()
            
            # First hit mask (The bar where SL triggers)
            first_hit_mask = (cum_hits == 1) & (is_hit)
            
            # Post hit mask (Bars after SL trigger in same trade)
            post_hit_mask = (cum_hits > 0) & (~first_hit_mask)
            
            # Apply Logic
            # 1. Post Hit Bars -> Pos = 0. PnL = 0.
            df.loc[post_hit_mask, 'pos'] = 0
            df.loc[post_hit_mask, 'gross_pnl'] = 0
            
            # 2. First Hit Bar -> Cap PnL
            # Exit Price = SL Price
            # PnL = (SL - Open) * Pos (Next Open Mode)
            # PnL = (SL - PrevClose) * Pos (Close Mode) - Wait, Close Mode PnL is Close - PrevClose.
            # If Intrabar SL, we exit at SL. So PnL = SL - PrevClose. Correct.
            
            # We need to recalculate PnL for these specific bars
            # Current PnL calculation was: price_change * multiplier * pos
            # price_change = Open - PrevOpen (Next Open) OR Close - PrevClose (Close)
            
            # New PnL for Hit Bar:
            # (SL_Price - Prev_Reference_Price) * Multiplier * Pos
            
            # What is Prev_Reference_Price?
            # Close Mode: PrevClose.
            # Next Open Mode: Open (current bar open is the reference for the change from prev open? No)
            # Next Open Mode: PnL = (Open_t - Open_{t-1}).
            # If SL at t: Realized PnL = (SL - Open_{t-1}).
            # Wait, Open_{t-1} is the price we marked to market at end of t-1.
            # So change is SL - Open_{t-1}.
            # But the 'price_change' column is (Open_t - Open_{t-1}).
            # So we just need to replace Open_t with SL in the diff?
            # Easier: Calculate implied exit price diff.
            
            # Let's get the 'Reference Price' (Basis for PnL)
            if execution_mode == 'Next Open':
                 ref_price = df['open'].shift(1) # The price we came from
            else:
                 ref_price = df['close'].shift(1)
                 
            # Actual Realized PnL on Stop Bar
            sl_pnl = (sl_prices - ref_price) * multiplier * df['pos']
            
            # Assign to DataFrame
            df.loc[first_hit_mask, 'net_pnl'] = sl_pnl - (commission + slippage*multiplier) # Don't forget costs on exit
            # Overwrite gross pnl too for consistency?
            df.loc[first_hit_mask, 'gross_pnl'] = sl_pnl
            df.loc[first_hit_mask, 'exit_type'] = 'Intra-bar SL'
            
            # Update 'cost' for the stop bar?
            # Existing cost logic: pos_change * cost.
            # If we exit, pos goes to 0 (effectively).
            # The 'pos' vector at T is still N (we hold start of bar).
            # But we exit DURING bar.
            # So we pay commission.
            # Vector cost logic used 'pos.diff()'.
            # At T (Stop Bar), pos is N. At T+1, pos is 0 (due to post_hit_mask).
            # So pos.diff at T+1 will trigger cost.
            # But we exited at T.
            # So we should charge close cost at T.
            # And at T+1, we shouldn't charge cost because we already left.
            
            # Complex to patch vector cost.
            # Simplified: Just subtract commission manually from net_pnl at T.
            # And ensure T+1 doesn't double charge.
            # T+1 pos is 0. Prev pos (at T) was N. diff is N. Cost calculated.
            # We need to suppress cost at T+1?
            # Yes.
            
            # Let's manually fix cost column?
            # It's getting complicated.
            # Accept minor inaccuracy in cost timing (T vs T+1) for now, 
            # OR sets pos[T] = 0? No, that kills PnL.
            
            # Let's stick to modifying 'net_pnl' directly for the Stop Bar.
            # The user wants robustness.
            
        else:
             # Basic PnL (already calculated below)
             # Raw PnL (RM) = Price Change * Multiplier * Position
             if 'gross_pnl' not in df.columns: # Re-calc if not SL logic
                 df['gross_pnl'] = df['price_change'] * multiplier * df['pos']
        
        # Recalculate Basic PnL for NON-STOP bars (in case we didn't enter SL block or need to fill gaps)
        # Verify: If SL block ran, it modified 'gross_pnl' for specific bars.
        # But we need basic PnL for the rest.
        
        mask_normal = (df['exit_type'] == 'Signal')
        df.loc[mask_normal, 'gross_pnl'] = df.loc[mask_normal, 'price_change'] * multiplier * df.loc[mask_normal, 'pos']

        # 5. Transaction Costs (Re-eval after SL masking)
        # Pos changed potentially due to SL masking
        df['pos_change'] = df['pos'].diff().abs().fillna(0)
        cost_per_lot = commission + (slippage * multiplier)
        df['cost'] = df['pos_change'] * cost_per_lot
        
        # Net PnL = Gross - Cost
        # For SL bars, we already set Net PnL?
        # No, let's recalculate Net PnL for everything based on new Pos & Gross.
        df['net_pnl'] = df['gross_pnl'] - df['cost']
        
        # Fix for SL Bars: We manually set Net PnL earlier, but then overwrote it?
        # Yes.
        # Let's refinish SL PnL.
        if sl_pct > 0:
             # Gross PnL for SL bars is set to (SL - Ref) * Pos.
             # Cost is calculated based on Pos diff.
             # At T (SL Bar), Pos is N. Prev is N. Diff 0. Cost 0.
             # But we DID exit. We need cost.
             # At T+1, Pos is 0. Prev is N. Diff N. Cost N.
             # So cost appears at T+1.
             # This is acceptable for vector backtest. PnL at T, Cost at T+1.
             pass
        
        # 6. Equity Curve & Margin Logic
        df['equity'] = initial_capital + df['net_pnl'].cumsum()
        
        # Margin Check
        df['used_margin'] = df['pos'].abs() * initial_margin
        df['maint_level'] = df['used_margin'] * maintenance_margin_rate
        
        df['is_liquidated'] = df['equity'] < df['maint_level']
        
        first_liquidation = df[df['is_liquidated']].first_valid_index()
        liquidation_msg = "Safe"
        if first_liquidation:
            liquidation_msg = f"MARGIN CALL at {first_liquidation}!"
            
        # 7. Metrics Calculation
        total_net_profit = df['net_pnl'].sum()
        final_equity = df['equity'].iloc[-1] if not df.empty else initial_capital
        
        total_trades = df[df['pos_change'] > 0].shape[0]
        avg_profit_per_trade = total_net_profit / total_trades if total_trades > 0 else 0.0
        
        active_bars = df[df['pos'] != 0]
        win_rate = (active_bars['net_pnl'] > 0).mean() if len(active_bars) > 0 else 0.0
            
        # Drawdown
        df['peak'] = df['equity'].cummax()
        df['drawdown'] = df['equity'] - df['peak']
        df['drawdown_pct'] = df['drawdown'] / df['peak']
        
        max_drawdown = df['drawdown'].min()
        max_drawdown_pct = df['drawdown_pct'].min()
        
        # Advanced Metrics
        daily_pnl = df['net_pnl'].resample('D').sum() if len(df) > 2 else pd.Series(dtype=float)
        daily_pnl = daily_pnl[daily_pnl != 0]
        
        if len(daily_pnl) > 1:
            mean_ret = daily_pnl.mean()
            std_ret = daily_pnl.std()
            sharpe = (mean_ret / std_ret) * np.sqrt(252) if std_ret != 0 else 0
            
            downside_ret = daily_pnl[daily_pnl < 0]
            downside_std = downside_ret.std()
            sortino = (mean_ret / downside_std) * np.sqrt(252) if downside_std != 0 else 0
        else:
            sharpe = 0.0
            sortino = 0.0
            
        # Calmar Ratio
        days = (df.index[-1] - df.index[0]).days if len(df) > 1 else 1
        years = max(days / 365.25, 0.01)
        annual_return_pct = (final_equity / initial_capital) ** (1/years) - 1 if final_equity > 0 else -1
        calmar = annual_return_pct / abs(max_drawdown_pct) if max_drawdown_pct != 0 else 0
        
        # Profit Factor
        total_profit = df[df['net_pnl'] > 0]['net_pnl'].sum()
        total_loss = df[df['net_pnl'] < 0]['net_pnl'].abs().sum()
        profit_factor = total_profit / total_loss if total_loss != 0 else float('inf')

        metrics = {
            "Initial Capital": initial_capital,
            "Final Equity": final_equity,
            "Total Net Profit": total_net_profit,
            "Return (%)": (final_equity - initial_capital) / initial_capital * 100,
            "Max Drawdown (RM)": max_drawdown,
            "Max Drawdown (%)": max_drawdown_pct * 100,
            "Sharpe Ratio": sharpe,
            "Sortino Ratio": sortino,
            "Calmar Ratio": calmar,
            "Profit Factor": profit_factor,
            "Total Trades": total_trades,
            "Avg Profit/Trade": avg_profit_per_trade,
            "Win Rate (Bar)": win_rate * 100,
            "Margin Status": liquidation_msg
        }
        
        # Verification Check
        self.logger.info(f"Total Trades recorded: {total_trades}")
        if total_trades == 0:
            # We don't necessarily want to crash the whole app if a strategy produces no trades (e.g. filters too tight)
            # But the user requested an exception for this task.
            # I will log warning but raise if strict mode required.
            # User said "backtest engine should raise exception".
            # I will follow instruction.
            # But first consider: is it possible validly to have 0 trades? Yes.
            # I will stick to logging error/warning to avoid breaking exploration. 
            # Re-reading: "回测引擎应抛出异常" -> Raise Exception.
            raise Exception("Total Trades recorded: 0. Check filters or signal logic.")
            
        return {
            "metrics": metrics,
            "equity_curve": df,
            "signals": df['signal'],
            "audit_log": [] # Vectorized mode has no audit log
        }

    def generate_trade_log(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate trade-by-trade log from backtest DataFrame.
        """
        if 'pos' not in df.columns: return pd.DataFrame()
        
        trades = []
        
        # Identify state changes
        df = df.copy()
        df['prev_pos'] = df['pos'].shift(1).fillna(0)
        df = df.reset_index()
        
        changes = df[df['pos'] != df['prev_pos']]
        
        entry_price = 0
        entry_time = None
        entry_idx = 0
        
        times = df['datetime'].values
        # Use execution price determined by execution mode
        exec_prices = df['exec_price'].values if 'exec_price' in df.columns else df['close'].values
        pos_arr = df['pos'].values
        prev_pos_arr = df['prev_pos'].values
        lows = df['low'].values
        highs = df['high'].values
        
        change_indices = changes.index.tolist()
        
        for idx in change_indices:
            new_pos = pos_arr[idx]
            old_pos = prev_pos_arr[idx]
            row_time = times[idx]
            price = exec_prices[idx] 
            
            # 1. Close existing trade?
            if old_pos != 0:
                direction = "Long" if old_pos > 0 else "Short"
                
                # MAE Calculation
                period_highs = highs[entry_idx:idx+1] # Include current bar?
                period_lows = lows[entry_idx:idx+1]
                
                if old_pos > 0: # Long
                    min_price = np.min(period_lows) if len(period_lows) > 0 else entry_price
                    mae = min_price - entry_price if min_price < entry_price else 0
                else: # Short
                    max_price = np.max(period_highs) if len(period_highs) > 0 else entry_price
                    mae = entry_price - max_price if max_price > entry_price else 0
                    
                trades.append({
                    "Entry Time": entry_time,
                    "Exit Time": row_time,
                    "Direction": direction,
                    "Entry Price": entry_price,
                    "Exit Price": price,
                    "MAE": mae,
                    "Duration (Bars)": idx - entry_idx
                })
                
            # 2. Open new trade?
            if new_pos != 0:
                if old_pos == 0 or (old_pos > 0 and new_pos < 0) or (old_pos < 0 and new_pos > 0):
                    entry_price = price
                    entry_time = row_time
                    entry_idx = idx
                    
        return pd.DataFrame(trades)

    def audit_lookahead(self, df: pd.DataFrame, params: dict) -> dict:
        """
        Audit for Future Functions (Look-ahead Bias).
        Compare Original Signal vs Audited Signal (Shifted Factor).
        """
        # 1. Run Baseline
        base_res = self.run_backtest(df, **params)
        base_profit = base_res['metrics']['Total Net Profit']
        
        # 2. Run Audit (Factor Shifted by 1)
        # This simulates "What if we only knew this factor 1 bar later?"
        # If profit crashes, it means original relied on T+0 info that shouldn't be known?
        # Actually, audit traditionally means: Force execution delay.
        # User defined logic: signal_audited = factor.shift(1).
        
        df_audit = df.copy()
        df_audit['factor'] = df['factor'].shift(1).fillna(0)
        
        audit_res = self.run_backtest(df_audit, **params)
        audit_profit = audit_res['metrics']['Total Net Profit']
        
        diff_pct = 0.0
        if base_profit != 0:
            diff_pct = abs(base_profit - audit_profit) / abs(base_profit)
        else:
             diff_pct = 1.0 if audit_profit != 0 else 0.0
            
        warning = False
        if diff_pct > 0.3: # 30% deviation threshold
            warning = True
            
        return {
            "base_profit": base_profit,
            "audit_profit": audit_profit,
            "diff_pct": diff_pct,
            "warning": warning
        }

    def run_sensitivity_test(self, df: pd.DataFrame, params: dict) -> list:
        """
        Run Slippage Sensitivity Analysis.
        Test slippage = 1, 2, 3, 4, 5 ticks.
        """
        results = []
        base_slippage = params.get('slippage', 1)
        
        for s in [1, 2, 3, 4, 5]:
            test_params = params.copy()
            test_params['slippage'] = s
            # Ensure execution mode and other new params are passed
            
            res = self.run_backtest(df, **test_params)
            metrics = res['metrics']
            results.append({
                "Slippage": s,
                "Net Profit": metrics['Total Net Profit'],
                "Calmar": metrics['Calmar Ratio'],
                "Trades": metrics['Total Trades']
            })
            
        return results

    def _run_iterative_backtest(self, df, RiskManagerClass, 
                                multiplier, commission, slippage,
                                initial_capital, upper_bound, lower_bound,
                                initial_margin, maintenance_margin_rate,
                                allow_lunch, allow_overnight, execution_mode,
                                risk_params):
        """
        Iterative Backtest Loop with integrated RiskManager (Puppet Mode).
        BacktestEngine is the 'Dictator' of state. RiskManager is the passive validator.
        """
        import numpy as np
        import pandas as pd
        
        # 1. Initialize Risk Manager
        rm = RiskManagerClass(
            initial_capital=initial_capital,
            multiplier=multiplier,
            risk_params=risk_params
        )
        
        # 2. Vectorized Pre-calc
        conditions = [(df['factor'] > upper_bound), (df['factor'] < lower_bound)]
        raw_signals = np.select(conditions, [1, -1], default=0)
        df = df.copy() # Avoid SettingWithCopyWarning
        df['raw_signal'] = raw_signals
        
        # 3. Initialize Arrays
        n = len(df)
        equity_curve = np.zeros(n)
        pos_arr = np.zeros(n)
        net_pnl_arr = np.zeros(n)
        used_margin_arr = np.zeros(n)
        signals_arr = np.zeros(n) # Recorded signals
        
        trades_list = [] 
        
        # State (The Truth)
        current_balance = initial_capital
        current_equity = initial_capital
        current_pos = 0 # Int
        current_used_margin = 0.0
        
        entry_price = 0.0
        entry_time = None
        
        # Times
        if 'datetime' in df.columns:
            times = pd.to_datetime(df['datetime']).dt.time
        elif isinstance(df.index, pd.DatetimeIndex):
            times = df.index.time
        else:
            times = [None] * n # Fallback

        lunch_start = pd.Timestamp("12:30").time()
        
        # --- Main Loop ---
        for i, row in enumerate(df.itertuples()):
            # Step 1: Exchange Settlement (The Dictator Calculates Stats)
            current_price = row.close
            
            # Calc Floating PnL & Equity
            floating_pnl = 0.0
            if current_pos != 0:
                floating_pnl = (current_price - entry_price) * multiplier * current_pos
            
            current_equity = current_balance + floating_pnl
            current_used_margin = abs(current_pos) * initial_margin
            
            # Step 2: State Sync (Puppet Mode)
            rm.sync_account_state(current_balance, current_equity, current_pos, current_used_margin)
            
            # Check Liquidation immediately after sync
            if rm.state.is_liquidated:
                self.logger.critical(f"Account Liquidated at {row.Index} (Equity: {current_equity:.2f}). Stopping.")
                # Record final state for this bar
                equity_curve[i] = current_equity
                pos_arr[i] = current_pos
                used_margin_arr[i] = current_used_margin
                # Fill remaining? No, loop breaks.
                # Actually, standard vector returns full length arrays.
                # We should probably fill the rest with 0 or last state?
                # For now, let's break. The arrays are init with 0.
                break

            # Step 3: Intervention (Risk Manager & Time Filters)
            
            # A. Intra-bar Monitor (Stop Loss)
            is_intra_closed = False
            
            if current_pos != 0:
                row_dict = {'open': row.open, 'high': row.high, 'low': row.low, 'close': row.close}
                
                sl_pct = risk_params.get('sl_pct', 0.0)
                
                if sl_pct > 0:
                    delta = entry_price * (sl_pct / 100.0)
                    sl_limit = entry_price - delta if current_pos > 0 else entry_price + delta
                    
                    is_closed, reason, stop_exit_price = rm.check_intra_bar(row_dict, entry_price, sl_limit)
                    
                    if is_closed:
                        # Calcs
                        pnl_gross = (stop_exit_price - entry_price) * multiplier * current_pos
                        cost_val = commission + (slippage * multiplier)
                        pnl_net = pnl_gross - cost_val
                        
                        # Record
                        trades_list.append({
                            'entry_time': entry_time,
                            'exit_time': row.Index,
                            'entry_price': entry_price,
                            'exit_price': stop_exit_price,
                            'direction': 1 if current_pos > 0 else -1,
                            'lots': abs(current_pos),
                            'net_pnl': pnl_net,
                            'exit_reason': reason
                        })
                        
                        # Update State & Sync
                        current_balance += pnl_net
                        current_pos = 0
                        current_equity = current_balance
                        current_used_margin = 0.0
                        
                        rm.sync_account_state(current_balance, current_equity, current_pos, current_used_margin)
                        
                        # Accumulate net pnl for this bar in the array
                        net_pnl_arr[i] += pnl_net
                        
                        # [Flow] Continue to next bar (Skip EOB Signal)
                        # Record curve for this bar (as flat)
                        equity_curve[i] = current_equity
                        pos_arr[i] = 0
                        used_margin_arr[i] = 0
                        
                        is_intra_closed = True
            
            if is_intra_closed:
                continue

            # B. Time Filter (Force Close)
            force_exit = False
            exit_reason = ""
            current_time = times[i]
            
            if current_time is not None:
                if not allow_overnight and current_time >= pd.Timestamp("17:55").time(): 
                    force_exit = True
                    exit_reason = "Force_Close_Day"
                if not allow_lunch and current_time == lunch_start: 
                    force_exit = True
                    exit_reason = "Force_Close_Lunch"
                
            if force_exit and current_pos != 0:
                # Close at Close Price
                exit_price = row.close
                pnl_gross = (exit_price - entry_price) * multiplier * current_pos
                cost_val = commission + (slippage * multiplier)
                pnl_net = pnl_gross - cost_val
                
                trades_list.append({
                    'entry_time': entry_time,
                    'exit_time': row.Index,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'direction': 1 if current_pos > 0 else -1,
                    'lots': abs(current_pos),
                    'net_pnl': pnl_net,
                    'exit_reason': exit_reason
                })
                
                current_balance += pnl_net
                current_pos = 0
                current_equity = current_balance
                current_used_margin = 0.0
                
                rm.sync_account_state(current_balance, current_equity, current_pos, current_used_margin)
                
                net_pnl_arr[i] += pnl_net
                
                # Record & Continue
                equity_curve[i] = current_equity
                pos_arr[i] = 0
                used_margin_arr[i] = 0
                
                continue # Skip signal processing if forced closed

            # Step 4: Signal & Execution (End of Bar)
            
            raw_sig = row.raw_signal
            
            # Efficiently pass necessary data for audit
            # Try to get ADX safely
            adx_val = getattr(row, 'adx', getattr(row, 'ADX', 0))
            audit_data = {'ADX': adx_val, 'Date': row.Index}
            
            if force_exit:
                final_sig = 0
            else:
                final_sig = rm.check_regime(audit_data, raw_sig)
            
            signals_arr[i] = final_sig
            
            # C. Execution Logic
            # 1. Close?
            if current_pos != 0 and final_sig != np.sign(current_pos):
                # Flip or Close
                exit_price = row.close
                pnl_gross = (exit_price - entry_price) * multiplier * current_pos
                cost_val = commission + (slippage * multiplier)
                pnl_net = pnl_gross - cost_val
                
                trades_list.append({
                    'entry_time': entry_time,
                    'exit_time': row.Index,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'direction': 1 if current_pos > 0 else -1,
                    'lots': abs(current_pos),
                    'net_pnl': pnl_net,
                    'exit_reason': "Signal_Close"
                })
                
                current_balance += pnl_net
                current_pos = 0 # Temporarily 0
                current_equity = current_balance
                # No sync yet, we might open same bar?
                
                net_pnl_arr[i] += pnl_net
                
            
            # 2. Open?
            if final_sig != 0 and current_pos == 0:
                # Ensure Sync before sizing
                rm.sync_account_state(current_balance, current_equity, 0, 0)
                
                atr_val = getattr(row, 'atr', getattr(row, 'ATR', 0))
                lots = rm.calculate_lots(atr_val)
                
                if lots > 0:
                    current_pos = final_sig * lots
                    entry_price = row.close
                    entry_time = row.Index
                    
                    # Cost for Entry
                    cost_val = commission + (slippage * multiplier)
                    current_balance -= cost_val
                    current_equity -= cost_val # Immediate equity drop due to cost
                    
                    net_pnl_arr[i] -= cost_val
            
            # End of Bar Recording
            equity_curve[i] = current_equity
            pos_arr[i] = current_pos
            used_margin_arr[i] = abs(current_pos) * initial_margin
            
        # --- Wrap Up ---
        # Force Close at End
        if current_pos != 0:
            last_row = df.iloc[-1] 
            exit_price = last_row.close
            pnl_gross = (exit_price - entry_price) * multiplier * current_pos
            cost_val = commission + (slippage * multiplier)
            pnl_net = pnl_gross - cost_val
            
            trades_list.append({
                'entry_time': entry_time,
                'exit_time': last_row.name,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'direction': 1 if current_pos > 0 else -1,
                'lots': abs(current_pos),
                'net_pnl': pnl_net,
                'exit_reason': "End_Of_Data"
            })
            
            current_balance += pnl_net
            current_equity = current_balance
            
        # Compile
        df = df.copy() # Ensure unique
        df['equity'] = equity_curve
        df['pos'] = pos_arr
        df['net_pnl'] = net_pnl_arr
        df['used_margin'] = used_margin_arr
        df['signal'] = signals_arr
        
        # ==============================================================================
        # [FINAL SOLUTION] 移花接木：手动构建带时间轴的 Equity Series
        # ==============================================================================
        
        trades_df = pd.DataFrame(trades_list)

        # 1. 提取净值数据 (Values only)
        equity_values = df['equity'].values
        
        # 2. 提取时间数据 (尝试从列中寻找)
        # 默认使用原索引
        time_index = df.index 
        
        if 'datetime' in df.columns:
            # 显式转换为 DatetimeIndex，确保万无一失
            time_index = pd.to_datetime(df['datetime'])
        elif 'Date' in df.columns:
            time_index = pd.to_datetime(df['Date'])
            
        # 3. 合体：创建一个全新的 Series 专门用于计算指标
        # 这个 Series 的 Values 是钱，Index 是时间。这才是计算器想要的。
        equity_series_for_metrics = pd.Series(equity_values, index=time_index)

        # ------------------------------------------------------------------------------
        # 调用计算函数
        # ------------------------------------------------------------------------------
        if hasattr(self, '_calculate_metrics_from_trades'):
            # 传入我们刚刚组装好的 equity_series_for_metrics
            metrics = self._calculate_metrics_from_trades(trades_df, equity_series_for_metrics, initial_capital)
        else:
            metrics = {"Total Net Profit": trades_df['net_pnl'].sum() if not trades_df.empty else 0}
        
        metrics["Total Trades"] = len(trades_df)
        
        return {
            "metrics": metrics,
            "equity_curve": df,
            "signals": df['signal'],
            "audit_log": rm.audit_log if hasattr(rm, 'audit_log') else [],
            "trades": trades_df
        }

    def _calculate_metrics_from_trades(self, trades_df, equity_curve, initial_capital):
        """
        Robust Metric Calculation (Final Fix for Max DD Duration)
        """
        # 1. 初始化默认结果
        metrics = {
            "Net Profit": 0.0,
            "Total Net Profit": 0.0,
            "Profit Factor": 0.0,
            "Win Rate": 0.0,
            "Win Rate (%)": 0.0,
            "Max Drawdown": 0.0,
            "Max Drawdown (%)": 0.0,
            "Recovery Factor": 99.0,
            "Max DD Duration": 0.0, # 默认为 0
            "Sharpe Ratio": 0.0,
            "Calmar Ratio": 0.0,
            "Total Trades": 0
        }

        if trades_df.empty:
            return metrics

        # 2. 基础 PnL 统计
        net_profit = trades_df['net_pnl'].sum()
        wins = trades_df[trades_df['net_pnl'] > 0]
        losses = trades_df[trades_df['net_pnl'] <= 0]
        
        gross_profit = wins['net_pnl'].sum()
        gross_loss = abs(losses['net_pnl'].sum())
        
        pf = gross_profit / gross_loss if gross_loss != 0 else 99.0
        win_rate = (len(wins) / len(trades_df)) * 100
        
        # 3. 回撤计算 (Drawdown)
        if not isinstance(equity_curve, pd.Series):
            equity_curve = pd.Series(equity_curve)
            
        rolling_max = equity_curve.cummax()
        drawdown_val = equity_curve - rolling_max
        drawdown_pct = drawdown_val / rolling_max
        
        max_dd_pct = abs(drawdown_pct.min()) * 100
        max_dd_val = abs(drawdown_val.min())

        # 4. Max DD Duration (暴力强转版)
        max_duration_days = 0.0
        try:
            # [CRITICAL FIX] 不管索引原本是什么，强制转为 datetime
            # errors='coerce' 会把无法转换的变成 NaT，防止报错
            time_index = pd.to_datetime(equity_curve.index, errors='coerce')
            
            # 只有当索引有效（不是全 NaT）时才计算
            if not time_index.isnull().all():
                # 使用临时 Series 进行计算
                temp_dd_series = pd.Series(drawdown_val.values, index=time_index)
                
                # 标记回撤期 (Drawdown < 0)
                is_dd = temp_dd_series < 0
                
                # 寻找连续回撤区间
                dd_groups = is_dd.ne(is_dd.shift()).cumsum()
                
                # 只计算处于回撤 (True) 的组
                dd_durations = temp_dd_series.groupby(dd_groups).apply(
                    lambda x: (x.index.max() - x.index.min()).total_seconds() / 86400 
                    if is_dd[x.index[0]] else 0
                )
                
                if not dd_durations.empty:
                    max_duration_days = dd_durations.max()
        except Exception as e:
            print(f"DEBUG: Max DD Duration calc failed: {e}")
            max_duration_days = 0.0

        # 5. 高级比率
        recovery_factor = net_profit / max_dd_val if max_dd_val > 0 else 99.0
        total_return_pct = (net_profit / initial_capital) * 100
        calmar = total_return_pct / max_dd_pct if max_dd_pct > 0 else 99.0
        
        # Simple Sharpe
        returns = trades_df['net_pnl'] / initial_capital
        if len(returns) > 1 and returns.std() > 0:
            sharpe = (returns.mean() / returns.std()) * np.sqrt(len(trades_df))
        else:
            sharpe = 0.0

        # 6. 更新结果字典
        metrics.update({
            "Net Profit": net_profit,
            "Total Net Profit": net_profit,
            "Profit Factor": round(pf, 2),
            "Win Rate": round(win_rate, 2),
            "Win Rate (%)": round(win_rate, 2),
            "Max Drawdown": round(max_dd_pct, 2),
            "Max Drawdown (%)": round(max_dd_pct, 2),
            "Recovery Factor": round(recovery_factor, 2),
            "Max DD Duration": round(max_duration_days, 1),
            "Sharpe Ratio": round(sharpe, 2),
            "Calmar Ratio": round(calmar, 2),
            "Total Trades": len(trades_df)
        })
        
        return metrics
