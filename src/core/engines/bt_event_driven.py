"""
Event-Driven Backtest Module
Bar-by-bar execution loop with RiskManager integration and Position tracking.
"""

import pandas as pd
import numpy as np
import logging
import math
from typing import Dict, Optional, List
from datetime import datetime

# Import Phase 1 models
import sys
from pathlib import Path
project_root = Path(__file__).parents[3]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.core.models.trade import Position, TradeDirection
from src.core.models.order import OrderRequest, OrderResponse


class EventDrivenBacktest:
    """
    Event-driven backtesting engine with bar-by-bar execution loop.
    
    Features:
    - RiskManager integration for position sizing and risk checks
    - Position class for dynamic avg_price and margin tracking
    - PyQt6 signal_emitter support for UI updates
    - Trade-by-trade audit logging
    """
    
    def __init__(self, signal_emitter=None):
        """
        Initialize event-driven backtest engine.
        
        Args:
            signal_emitter: Optional PyQt6 signal emitter for UI updates.
                           Should have .log and .progress signals.
        """
        self.logger = logging.getLogger(__name__)
        self.signal_emitter = signal_emitter
    
    def _emit_log(self, message: str):
        """Emit log message to UI if signal_emitter available."""
        if self.signal_emitter and hasattr(self.signal_emitter, 'log'):
            self.signal_emitter.log.emit(message)
        self.logger.info(message)
    
    def _emit_progress(self, current: int, total: int):
        """Emit progress update to UI if signal_emitter available."""
        if self.signal_emitter and hasattr(self.signal_emitter, 'progress'):
            self.signal_emitter.progress.emit(current, total)
    
    def run(self, df: pd.DataFrame, asset_symbol: str, RiskManagerClass,
            multiplier: float, commission: float, slippage: float,
            initial_capital: float,
            initial_margin: float, maintenance_margin_rate: float = 0.8,
            allow_lunch: bool = True, allow_overnight: bool = True,
            execution_mode: str = 'Close', risk_params: dict = None) -> Dict:
        """
        Execute event-driven backtest with RiskManager integration.
        
        Args:
            df: DataFrame with OHLCV and factor columns
            asset_symbol: Asset symbol (e.g., 'FCPO', 'FKLI')
            RiskManagerClass: RiskManager class (not instance)
            multiplier: Contract multiplier from AssetConfig
            commission: Commission per lot
            slippage: Slippage in ticks
            initial_capital: Starting capital
            initial_margin: Initial margin per lot
            maintenance_margin_rate: Margin call threshold
            allow_lunch: Allow positions during lunch
            allow_overnight: Allow overnight positions
            execution_mode: 'Close' or 'Next Open'
            risk_params: Risk parameters for RiskManager
        
        Returns:
            Dictionary with metrics, equity_curve, signals, audit_log, trades
        """
        self._emit_log(f"[EVENT-DRIVEN] Starting backtest for {asset_symbol}")
        self._emit_log(f"[CONFIG] Multiplier={multiplier}, Margin={initial_margin}, Capital={initial_capital}")
        
        # 1. Initialize RiskManager
        if risk_params is None:
            risk_params = {}
            
        # Resolve tick_size from AssetConfig or fallback
        try:
            from src.core.models.asset import get_asset_config
            asset_cfg = get_asset_config(asset_symbol)
            tick_size = asset_cfg.tick_size
        except Exception:
            if "FKLI" in str(asset_symbol).upper():
                tick_size = 0.5
            elif "FCPO" in str(asset_symbol).upper():
                tick_size = 1.0
            else:
                tick_size = 1.0
        self._emit_log(f"[CONFIG] Resolved Tick Size = {tick_size}")
        
        rm = RiskManagerClass(
            initial_capital=initial_capital,
            multiplier=multiplier,
            risk_params=risk_params
        )
        
        self._emit_log(f"[RISK] RiskManager initialized with params: {risk_params}")
        
        # 2. Prepare DataFrame
        df = self._prepare_dataframe(df)
        
        # Calculate Risk Indicators if missing (required for RiskManager)
        if 'atr' not in df.columns:
            df['atr'] = self._calculate_atr(df)
        if 'adx' not in df.columns:
            df['adx'] = self._calculate_adx(df)
            
        # Prevent look-ahead bias: 
        # Shift ATR so that when checking stops or sizing during bar T, 
        # we only use volatility information known at the end of bar T-1.
        df['atr'] = df['atr'].shift(1).fillna(0)
        if 'adx' in df.columns:
            df['adx'] = df['adx'].shift(1).fillna(0)
            
        # Signal Processing: The `signal` column MUST exist prior to calling this engine.
        # Fallback to 0 if not natively available
        if 'signal' not in df.columns:
            df['signal'] = 0
        
        # 3. Initialize state arrays
        n = len(df)
        equity_curve = np.zeros(n)
        pos_arr = np.zeros(n)
        net_pnl_arr = np.zeros(n)
        used_margin_arr = np.zeros(n)
        signals_arr = np.zeros(n)
        
        trades_list: List[Dict] = []
        
        # 4. Initialize account state
        current_balance = initial_capital
        current_equity = initial_capital
        current_position: Optional[Position] = None
        
        # Pending state for T+1 execution
        # 0: None, 1: Long, -1: Short, 2: Close
        pending_action = 0 
        just_closed = False
        entered_this_bar_index = -1
        
        # 5. Extract time information
        times = self._extract_times(df)
        lunch_start = pd.Timestamp("12:30").time()
        
        # 6. Main event loop — 3-Phase State Machine
        self._emit_log(f"[LOOP] Starting {n} bars event loop with T+1 Execution...")
        
        for i, row in enumerate(df.itertuples()):
            # Progress update every 100 bars
            if i % 100 == 0:
                self._emit_progress(i, n)
            
            # ======================================================================
            # PHASE I: EXECUTE PENDING ORDERS (T+1 Execution at Current Bar OPEN)
            #
            # All orders generated by the signal detector in the PREVIOUS bar's
            # PHASE III are executed HERE at the current bar's open price.
            # This is the physical enforcement of the T+1 execution constraint.
            # No future data can leak into this phase.
            # ======================================================================
            
            # Step I-0: Atomic memory reset — prevent dirty-state ghost trades
            pnl_gross = 0.0
            pnl_net = 0.0
            cost_val = 0.0
            exit_price = None
            entry_price = None
            executed_this_bar = False
            
            # Step I-0.5: Open-to-Market (MtM) Sync to prevent stale risk metrics on Overnight Gaps
            if current_position is not None and current_position.lots > 0:
                floating_pnl_open = current_position.calculate_pnl(row.open)
                open_equity = current_balance + floating_pnl_open
                direction_sign = 1 if current_position.direction == TradeDirection.LONG else -1
                current_pos_signed = current_position.lots * direction_sign
                current_used_margin = current_position.margin_used
            else:
                open_equity = current_balance
                current_pos_signed = 0
                current_used_margin = 0.0
            
            if hasattr(rm, 'sync_account_state'):
                rm.sync_account_state(current_balance, open_equity, current_pos_signed, current_used_margin, current_date=row.Index)
                      # Step I-1: Execute the pending order at the OPEN of the current bar
            if pending_action != 0:
                if execution_mode == 'Close':
                    fill_price = df.iloc[i-1]['close'] if i > 0 else row.open
                else:
                    fill_price = row.open

                if pending_action == 2:  # Close command
                    if current_position is not None and current_position.lots > 0:
                        lots_closed = current_position.lots
                        dir_val = current_position.direction.value
                        direction_mult = 1 if dir_val == "LONG" or dir_val == 1 else -1
                        
                        # Apply exit slippage and discretization (Price-Embedded Slippage)
                        if direction_mult == 1:  # Closing LONG: Sell order (Floor)
                            exit_price = math.floor((fill_price - slippage) / tick_size) * tick_size
                        else:  # Closing SHORT: Buy order (Ceil)
                            exit_price = math.ceil((fill_price + slippage) / tick_size) * tick_size
                            
                        pnl_gross = (exit_price - current_position.avg_entry_price) * direction_mult * multiplier * lots_closed
                        exit_cost = commission * lots_closed
                        pnl_net = pnl_gross - 2 * commission * lots_closed
                        
                        # GUARD: trades_list.append is ONLY called inside pending_action block
                        trades_list.append({
                            'entry_time': current_position.entry_time,
                            'exit_time': row.Index,
                            'entry_price': current_position.avg_entry_price,
                            'exit_price': exit_price,
                            'direction': current_position.direction.value,
                            'lots': current_position.lots,
                            'net_pnl': pnl_net,
                            'exit_reason': "Signal_Close",
                            'requested_price': fill_price,
                            'commission_paid': 2 * commission * lots_closed,
                            'slippage_incurred': 2 * slippage * multiplier * lots_closed,
                            'margin_occupied': lots_closed * initial_margin
                        })
                        
                        current_balance += pnl_gross - exit_cost
                        net_pnl_arr[i] = pnl_net
                        current_position = None
                        
                        self._emit_log(f"🔄 [{row.Index}] PHASE I — T+1 Close at {exit_price:.2f} | Net PnL={pnl_net:.2f}")
                        executed_this_bar = True
                        just_closed = True
                        
                elif pending_action in [1, -1]:  # Entry command
                    if current_position is None or current_position.lots == 0:
                        atr_val = getattr(row, 'atr', getattr(row, 'ATR', 0))
                        adx_val = getattr(row, 'adx', getattr(row, 'ADX', 0))
                        
                        # Apply entry slippage and discretization (Price-Embedded Slippage)
                        if pending_action == 1:  # Buying: LONG entry (Ceil)
                            exec_price = math.ceil((fill_price + slippage) / tick_size) * tick_size
                        else:  # Selling: SHORT entry (Floor)
                            exec_price = math.floor((fill_price - slippage) / tick_size) * tick_size
                        
                        # Intent volume: pass caller's max_lots (or large sentinel) so the
                        # Interceptor's _check_sizing_layer can cap it to the correct value.
                        intent_volume = risk_params.get('max_lots', 999) if risk_params else 999
                        order_request = OrderRequest(
                            symbol=asset_symbol,
                            volume=intent_volume,
                            direction=pending_action,
                            order_type='MARKET',
                            price=exec_price,
                            timestamp=row.Index,
                            atr=atr_val,
                            adx=adx_val
                        )
                        
                        if hasattr(rm, 'validate_order'):
                            response: OrderResponse = rm.validate_order(order_request)
                            if response.approved:
                                lots = response.adjusted_volume
                                current_position = Position(
                                    symbol=asset_symbol,
                                    direction=TradeDirection.LONG if pending_action == 1 else TradeDirection.SHORT,
                                    lots=lots,
                                    avg_entry_price=exec_price,
                                    multiplier=multiplier,
                                    initial_margin_per_lot=initial_margin,
                                    entry_time=row.Index
                                )
                                entered_this_bar_index = i
                                self._emit_log(f"✅ [{row.Index}] PHASE I — T+1 Entry: {order_request.direction_str} x{lots} at {exec_price:.2f}")
                                executed_this_bar = True
                                
                                # Deduct entry friction (single-side cost - commission only)
                                entry_cost = commission * lots
                                current_balance -= entry_cost
                        else:
                            # Legacy fallback (no validate_order)
                            lots = rm.calculate_lots(atr_val)
                            if lots > 0:
                                current_position = Position(
                                    symbol=asset_symbol,
                                    direction=TradeDirection.LONG if pending_action == 1 else TradeDirection.SHORT,
                                    lots=lots,
                                    avg_entry_price=exec_price,
                                    multiplier=multiplier,
                                    initial_margin_per_lot=initial_margin,
                                    entry_time=row.Index
                                )
                                entered_this_bar_index = i
                                self._emit_log(f"✅ [{row.Index}] PHASE I — T+1 Entry (Legacy): {pending_action} x{lots} at {exec_price:.2f}")
                                executed_this_bar = True
                                
                                # Deduct entry friction (single-side cost - commission only)
                                entry_cost = commission * lots
                                current_balance -= entry_cost
                
                # Step I-2: Destroy the pending order object — it is now consumed
                pending_action = 0
            
            # Cooldown: single-bar re-entry lock
            # just_closed stays True only if we closed this very bar (via T+1)
            if not executed_this_bar:
                just_closed = False
            
            # ======================================================================
            # PHASE II: INTRA-BAR MONITORING & RISK INTERVENTIONS
            #
            # Steps II-1 → II-3 use only information that was known at bar OPEN
            # (for stop levels) and intra-bar OHLC (for stop-hit detection).
            # No future close-price data is used to decide an exit here.
            # ======================================================================
            
            # Step II-1: Mark-to-Market at current bar's CLOSE (floating PnL only)
            current_price = row.close
            floating_pnl = 0.0
            if current_position is not None and current_position.lots > 0:
                floating_pnl = current_position.calculate_pnl(current_price)
            
            current_equity = current_balance + floating_pnl
            current_used_margin = current_position.margin_used if current_position else 0.0
            
            # Step II-2: Sync RiskManager with current account snapshot
            if current_position and current_position.lots > 0:
                direction_sign = 1 if current_position.direction == TradeDirection.LONG else -1
                current_pos_signed = current_position.lots * direction_sign
            else:
                current_pos_signed = 0
            rm.sync_account_state(current_balance, current_equity, current_pos_signed, current_used_margin, current_date=row.Index)
            
            # --- [CRITICAL VULNERABILITY FIX]: MARGIN CALL ENFORCEMENT ---
            if getattr(rm.state, 'is_liquidated', False) and current_position is not None and current_position.lots > 0:
                lots_closed = current_position.lots
                dir_val = current_position.direction.value
                direction_mult = 1 if dir_val == "LONG" or dir_val == 1 else -1
                
                # Check if it was liquidated by the Open price (Overnight Gap) or during the bar
                floating_pnl_open = current_position.calculate_pnl(row.open)
                open_equity = current_balance + floating_pnl_open
                maint_margin_limit = current_position.margin_used * maintenance_margin_rate
                
                # Symmetrical Open Gap Breach Check
                peak_drawdown_open = (getattr(rm, '_high_water_mark', open_equity) - open_equity) / getattr(rm, '_high_water_mark', 1.0) if getattr(rm, '_high_water_mark', 0) > 0 else 0.0
                daily_drawdown_open = (getattr(rm, '_daily_baseline_equity', open_equity) - open_equity) / getattr(rm, '_daily_baseline_equity', 1.0) if getattr(rm, '_daily_baseline_equity', 0) > 0 else 0.0
                
                if (open_equity < maint_margin_limit) or (peak_drawdown_open > 0.35) or (daily_drawdown_open > 0.20):
                    fill_price = row.open
                    exit_reason = "Margin_Call_Gap_Open"
                else:
                    fill_price = row.close
                    exit_reason = "Margin_Call_Intraday"
                
                # Symmetrical Discretization on Margin Call Exit
                if direction_mult == 1:  # Selling: Floor
                    exit_price = math.floor((fill_price - slippage) / tick_size) * tick_size
                else:  # Buying: Ceil
                    exit_price = math.ceil((fill_price + slippage) / tick_size) * tick_size
                    
                pnl_gross = (exit_price - current_position.avg_entry_price) * direction_mult * multiplier * lots_closed
                exit_cost = commission * lots_closed
                pnl_net = pnl_gross - 2 * commission * lots_closed
                
                trades_list.append({
                    'entry_time': current_position.entry_time,
                    'exit_time': row.Index,
                    'entry_price': current_position.avg_entry_price,
                    'exit_price': exit_price,
                    'direction': current_position.direction.value,
                    'lots': current_position.lots,
                    'net_pnl': pnl_net,
                    'exit_reason': exit_reason,
                    'requested_price': fill_price,
                    'commission_paid': 2 * commission * lots_closed,
                    'slippage_incurred': 2 * slippage * multiplier * lots_closed,
                    'margin_occupied': lots_closed * initial_margin
                })
                
                current_balance += pnl_gross - exit_cost
                current_position = None
                just_closed = True
                
                self._emit_log(f"🚨 [{row.Index}] PHASE II — MARGIN CALL LIQUIDATION at {exit_price:.2f} | Net PnL={pnl_net:.2f}")
                
                # Record state and skip to next bar
                equity_curve[i] = current_balance
                pos_arr[i] = 0
                used_margin_arr[i] = 0
                net_pnl_arr[i] = pnl_net
                continue
            
            # Step II-3: Risk Interventions — intra-bar stop loss / take profit check
            is_intra_closed = False
            
            if current_position is not None and current_position.lots > 0:
                sl_pct = risk_params.get('sl_pct', 0.0)
                tp_pct = risk_params.get('tp_pct', 0.0)
                if sl_pct > 0 or tp_pct > 0:
                    row_dict = {'open': row.open, 'high': row.high, 'low': row.low, 'close': row.close}
                    is_long = (current_position.direction == TradeDirection.LONG)
                    
                    # SL price calculation
                    sl_limit = None
                    if sl_pct > 0:
                        sl_delta = current_position.avg_entry_price * (sl_pct / 100.0)
                        sl_limit = (current_position.avg_entry_price - sl_delta if is_long
                                    else current_position.avg_entry_price + sl_delta)
                    
                    # TP price calculation
                    tp_limit = None
                    if tp_pct > 0:
                        tp_delta = current_position.avg_entry_price * (tp_pct / 100.0)
                        tp_limit = (current_position.avg_entry_price + tp_delta if is_long
                                    else current_position.avg_entry_price - tp_delta)
                    
                    # Call intra-bar monitor with available SL/TP
                    if sl_limit is not None:
                        is_closed, reason, stop_exit_price = rm.check_intra_bar(
                            row_dict, current_position.avg_entry_price,
                            sl_limit, tp_price=tp_limit)
                    else:
                        # TP-only mode: use sentinel SL that cannot trigger
                        sentinel_sl = 0.0 if is_long else float('inf')
                        is_closed, reason, stop_exit_price = rm.check_intra_bar(
                            row_dict, current_position.avg_entry_price,
                            sentinel_sl, tp_price=tp_limit)
                    
                    if is_closed:
                        lots_closed = current_position.lots
                        dir_val = current_position.direction.value
                        direction_mult = 1 if dir_val == "LONG" or dir_val == 1 else -1
                        
                        actual_exit_slippage = 0.0 if "TP" in str(reason) else slippage
                        
                        if direction_mult == 1:  # Selling: Floor
                            exit_price = math.floor((stop_exit_price - actual_exit_slippage) / tick_size) * tick_size
                        else:  # Buying: Ceil
                            exit_price = math.ceil((stop_exit_price + actual_exit_slippage) / tick_size) * tick_size
                            
                        pnl_gross = (exit_price - current_position.avg_entry_price) * direction_mult * multiplier * lots_closed
                        exit_cost = commission * lots_closed
                        pnl_net = pnl_gross - 2 * commission * lots_closed
                        
                        # GUARD: append strictly inside this risk-intervention block
                        trades_list.append({
                            'entry_time': current_position.entry_time,
                            'exit_time': row.Index,
                            'entry_price': current_position.avg_entry_price,
                            'exit_price': exit_price,
                            'direction': current_position.direction.value,
                            'lots': current_position.lots,
                            'net_pnl': pnl_net,
                            'exit_reason': reason,
                            'requested_price': stop_exit_price,
                            'commission_paid': 2 * commission * lots_closed,
                            'slippage_incurred': 2 * actual_exit_slippage * multiplier * lots_closed,
                            'margin_occupied': lots_closed * initial_margin
                        })
                        
                        current_balance += pnl_gross - exit_cost
                        current_position = None
                        just_closed = True
                        is_intra_closed = True
                        self._emit_log(f"⚠️ [{row.Index}] PHASE II — {reason} at {exit_price:.2f} | Net PnL={pnl_net:.2f}")
 
            if is_intra_closed:
                # Record state and skip to next bar — signal detection is skipped
                equity_curve[i] = current_balance
                pos_arr[i] = 0
                used_margin_arr[i] = 0
                net_pnl_arr[i] = pnl_net
                continue
            
            # Step II-4: Time-based forced exit (EOD / Lunch)
            force_exit_reason = ""
            current_time = times[i]
            
            # Dynamically determine if this is the last bar of the day
            is_last_bar_of_day = (i == n - 1) or (df.index[i].date() != df.index[i+1].date())
            
            if current_time is not None:
                if not allow_overnight and is_last_bar_of_day:
                    force_exit_reason = "Force_Close_Day"
                if not allow_lunch and current_time == lunch_start:
                    force_exit_reason = "Force_Close_Lunch"
            
            if force_exit_reason and current_position is not None and current_position.lots > 0:
                fill_price = row.close
                lots_closed = current_position.lots
                dir_val = current_position.direction.value
                direction_mult = 1 if dir_val == "LONG" or dir_val == 1 else -1
                
                # Apply exit slippage and discretization
                if direction_mult == 1:  # Selling: Floor
                    exit_price = math.floor((fill_price - slippage) / tick_size) * tick_size
                else:  # Buying: Ceil
                    exit_price = math.ceil((fill_price + slippage) / tick_size) * tick_size
                    
                pnl_gross = (exit_price - current_position.avg_entry_price) * direction_mult * multiplier * lots_closed
                exit_cost = commission * lots_closed
                pnl_net = pnl_gross - 2 * commission * lots_closed
                
                trades_list.append({
                    'entry_time': current_position.entry_time,
                    'exit_time': row.Index,
                    'entry_price': current_position.avg_entry_price,
                    'exit_price': exit_price,
                    'direction': current_position.direction.value,
                    'lots': current_position.lots,
                    'net_pnl': pnl_net,
                    'exit_reason': force_exit_reason,
                    'requested_price': fill_price,
                    'commission_paid': 2 * commission * lots_closed,
                    'slippage_incurred': 2 * slippage * multiplier * lots_closed,
                    'margin_occupied': lots_closed * initial_margin
                })
                
                current_balance += pnl_gross - exit_cost
                current_position = None
                just_closed = True
                
                equity_curve[i] = current_balance
                pos_arr[i] = 0
                used_margin_arr[i] = 0
                net_pnl_arr[i] = pnl_net
                continue
            
            # ======================================================================
            # PHASE III: SIGNAL DETECTION AT BAR T (Reads factor at T's CLOSE)
            #
            # This phase reads bar T's factor and close price ONLY.
            # Any signal generated here becomes a pending_order that CANNOT execute
            # in this iteration — it must wait for the next bar's PHASE I.
            # This is the physical enforcement of the look-ahead-free guarantee.
            # ======================================================================
            
            # Step III-1: Read signal data from current bar T
            raw_sig = getattr(row, 'signal', 0)
            factor_val = getattr(row, 'factor', 0.0)
            adx_val = getattr(row, 'adx', getattr(row, 'ADX', 0))
            audit_data = {'ADX': adx_val, 'Date': row.Index}
            
            # Step III-2: Validate signal through RiskManager regime filter
            valid_entry_sig = rm.check_regime(audit_data, raw_sig)
            
            # Step III-3: Generate pending order (PROHIBITED from executing this iteration)
            if current_position is None or current_position.lots == 0:
                # State: FLAT — look for entry signals
                if not just_closed:  # Single-bar re-entry lock: prevents whiplash
                    if raw_sig == 1 and valid_entry_sig == 1:
                        pending_action = 1
                        self._emit_log(f"💡 [{row.Index}] PHASE III — Signal=1 → LONG queued for T+1")
                    elif raw_sig == -1 and valid_entry_sig == -1:
                        pending_action = -1
                        self._emit_log(f"💡 [{row.Index}] PHASE III — Signal=-1 → SHORT queued for T+1")
            else:
                # State: IN POSITION — look for exit signals
                if i > entered_this_bar_index:
                    if current_position.direction == TradeDirection.LONG:
                        if raw_sig == 0 or raw_sig == -1:
                            pending_action = 2
                            self._emit_log(f"💡 [{row.Index}] PHASE III — Signal={raw_sig} → CLOSE LONG queued for T+1")
                    elif current_position.direction == TradeDirection.SHORT:
                        if raw_sig == 0 or raw_sig == 1:
                            pending_action = 2
                            self._emit_log(f"💡 [{row.Index}] PHASE III — Signal={raw_sig} → CLOSE SHORT queued for T+1")
            
            # Step III-4: Commit bar state to output arrays
            signals_arr[i] = pending_action if pending_action in [1, -1] else 0
            
            # Flush Zombie Orders
            if not allow_overnight and i < n - 1 and df.index[i].date() != df.index[i+1].date():
                if pending_action != 0:
                    self._emit_log(f"🧹 [{row.Index}] PHASE III — EOD Zombie Order Flushed (allow_overnight=False)")
                    pending_action = 0
            
            equity_curve[i] = current_equity
            pos_arr[i] = current_position.lots if current_position else 0
            used_margin_arr[i] = current_position.margin_used if current_position else 0.0
            # net_pnl_arr[i] remains 0.0 for bars with no realized PnL (holding bars)
        
        # Final progress update
        self._emit_progress(n, n)
        
        # === END-OF-DATA: Force close any remaining open position ===
        if current_position is not None and current_position.lots > 0:
            last_row = df.iloc[-1]
            fill_price = last_row['close']
            lots_closed = current_position.lots
            dir_val = current_position.direction.value
            direction_mult = 1 if dir_val == "LONG" or dir_val == 1 else -1
            
            # Apply exit slippage and discretization
            if direction_mult == 1:  # Selling: Floor
                exit_price = math.floor((fill_price - slippage) / tick_size) * tick_size
            else:  # Buying: Ceil
                exit_price = math.ceil((fill_price + slippage) / tick_size) * tick_size
                
            pnl_gross = (exit_price - current_position.avg_entry_price) * direction_mult * multiplier * lots_closed
            exit_cost = commission * lots_closed
            pnl_net = pnl_gross - 2 * commission * lots_closed
            
            trades_list.append({
                'entry_time': current_position.entry_time,
                'exit_time': last_row.name,
                'entry_price': current_position.avg_entry_price,
                'exit_price': exit_price,
                'direction': current_position.direction.value,
                'lots': current_position.lots,
                'net_pnl': pnl_net,
                'exit_reason': "End_Of_Data",
                'requested_price': fill_price,
                'commission_paid': 2 * commission * lots_closed,
                'slippage_incurred': 2 * slippage * multiplier * lots_closed,
                'margin_occupied': lots_closed * initial_margin
            })
            
            current_balance += pnl_gross - exit_cost
            current_equity = current_balance
            net_pnl_arr[-1] = pnl_net
        
        # === STEP 7: Compile results ===
        df = df.copy()
        df['equity'] = equity_curve
        df['pos'] = pos_arr
        df['net_pnl'] = net_pnl_arr
        df['used_margin'] = used_margin_arr
        df['signal'] = signals_arr
        
        # Calculate drawdown for UI charts
        df['peak'] = df['equity'].cummax()
        df['drawdown'] = df['equity'] - df['peak']
        df['drawdown_pct'] = df['drawdown'] / df['peak']
        
        trades_df = pd.DataFrame(trades_list)
        
        self._emit_log(f"[COMPLETE] Total trades: {len(trades_df)}, Final equity: {current_equity:.2f}")
        
        # === STEP 8: Calculate metrics ===
        equity_series = self._create_equity_series(df)
        metrics = self._calculate_metrics_from_trades(trades_df, equity_series, initial_capital)
        metrics["Total Trades"] = len(trades_df)
        metrics["Initial Capital"] = initial_capital
        
        return {
            "metrics": metrics,
            "equity_curve": df,
            "signals": df['signal'],
            "audit_log": rm.audit_log if hasattr(rm, 'audit_log') else [],
            "trades": trades_df
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
        
        if not {'close', 'factor'}.issubset(df.columns):
            raise ValueError(f"DataFrame must contain 'close' and 'factor' columns.")
        
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

    def _extract_times(self, df: pd.DataFrame):
        """Extract time information from DataFrame."""
        if 'datetime' in df.columns:
            return pd.to_datetime(df['datetime']).dt.time
        elif isinstance(df.index, pd.DatetimeIndex):
            return df.index.time
        else:
            return [None] * len(df)
    
    def _create_equity_series(self, df: pd.DataFrame) -> pd.Series:
        """Create equity Series with proper time index."""
        equity_values = df['equity'].values
        time_index = df.index
        
        if 'datetime' in df.columns:
            time_index = pd.to_datetime(df['datetime'])
        elif 'Date' in df.columns:
            time_index = pd.to_datetime(df['Date'])
        
        return pd.Series(equity_values, index=time_index)
    
    def _calculate_metrics_from_trades(self, trades_df: pd.DataFrame, 
                                       equity_curve: pd.Series, 
                                       initial_capital: float) -> Dict:
        """
        Calculate performance metrics using institutional-grade Mark-to-Market (MtM).
        
        - Sharpe:  Daily equity returns, annualized √252
        - MDD:     Equity curve high-water mark (captures intra-trade floating losses)
        - Calmar:  CAGR / MDD(MtM)
        - Trade-level metrics (Win Rate, PF) remain trade-based.
        """
        metrics = {
            "Net Profit": 0.0,
            "Total Net Profit": 0.0,
            "Profit Factor": 0.0,
            "Win Rate": 0.0,
            "Win Rate (%)": 0.0,
            "Max Drawdown": 0.0,
            "Max Drawdown (%)": 0.0,
            "Recovery Factor": 99.0,
            "Max DD Duration": 0.0,
            "Sharpe Ratio": 0.0,
            "Calmar Ratio": 0.0,
            "Total Trades": 0
        }
        
        if trades_df.empty:
            return metrics
        
        # ================================================================
        # SECTION A: Trade-Level Metrics (Win Rate, Profit Factor, Net PnL)
        # ================================================================
        trades_list = trades_df.to_dict('records')
        
        winning_trades = [t for t in trades_list if t.get('net_pnl', 0) > 0]
        losing_trades = [t for t in trades_list if t.get('net_pnl', 0) <= 0]
        
        win_rate = (len(winning_trades) / len(trades_list)) * 100 if len(trades_list) > 0 else 0.0
        
        gross_profit = sum(t['net_pnl'] for t in winning_trades)
        gross_loss = abs(sum(t['net_pnl'] for t in losing_trades))
        
        pf = gross_profit / gross_loss if gross_loss != 0 else 99.0
        net_profit = sum(t['net_pnl'] for t in trades_list)
        
        # ================================================================
        # SECTION B: Mark-to-Market Metrics (Sharpe, MDD, Calmar)
        #            Based on bar-level equity curve with floating PnL
        # ================================================================
        
        # --- B1: Build daily equity series from bar-level data ---
        eq = equity_curve.copy()
        # Safe fill: only replace leading zeros (bars before first trade) with initial_capital.
        # NEVER replace mid-series zeros — they represent real account blowup.
        if (eq == 0).any():
            first_nonzero_idx = eq.ne(0).idxmax()
            eq.loc[:first_nonzero_idx] = eq.loc[:first_nonzero_idx].replace(0, initial_capital)
        
        # Resample to daily (last value of each trading day)
        if isinstance(eq.index, pd.DatetimeIndex):
            daily_equity = eq.resample('D').last().dropna()
        else:
            daily_equity = eq  # fallback: use as-is
        
        # --- B2: Max Drawdown (MtM) from equity curve high-water mark ---
        peak = daily_equity.cummax()
        drawdown = daily_equity - peak
        drawdown_pct = drawdown / peak
        
        max_dd_pct = abs(drawdown_pct.min()) * 100 if len(drawdown_pct) > 0 else 0.0
        max_dd_val = abs(drawdown.min()) if len(drawdown) > 0 else 0.0
        
        # MDD Duration (days): longest streak below high-water mark
        is_in_dd = drawdown < 0
        dd_groups = (~is_in_dd).cumsum()
        if is_in_dd.any():
            dd_durations = is_in_dd.groupby(dd_groups).sum()
            max_dd_duration = float(dd_durations.max())
        else:
            max_dd_duration = 0.0
        
        # --- B3: Sharpe Ratio (daily returns, annualized √252) ---
        if len(daily_equity) > 1:
            daily_returns = daily_equity.pct_change().dropna()
            if len(daily_returns) > 1 and daily_returns.std() > 0:
                sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
            else:
                sharpe = 0.0
        else:
            sharpe = 0.0
        
        # --- B4: Calmar Ratio (CAGR / MDD_MtM) ---
        final_equity = float(daily_equity.iloc[-1]) if len(daily_equity) > 0 else initial_capital
        
        if isinstance(daily_equity.index, pd.DatetimeIndex) and len(daily_equity) > 1:
            total_days = (daily_equity.index[-1] - daily_equity.index[0]).days
        else:
            total_days = 0
        
        if total_days > 0 and initial_capital > 0 and final_equity > 0:
            cagr = (final_equity / initial_capital) ** (365.25 / total_days) - 1
        else:
            cagr = (final_equity / initial_capital) - 1 if initial_capital > 0 else 0.0
        
        cagr_pct = cagr * 100
        calmar = cagr_pct / max_dd_pct if max_dd_pct > 0 else 99.0
        
        # --- B5: Recovery Factor (net profit / max drawdown value) ---
        recovery_factor = net_profit / max_dd_val if max_dd_val > 0 else 99.0
        
        # ================================================================
        # SECTION C: Assemble final metrics dict
        # ================================================================
        metrics.update({
            "Net Profit": net_profit,
            "Total Net Profit": net_profit,
            "Profit Factor": round(pf, 2),
            "Win Rate": round(win_rate, 2),
            "Win Rate (%)": round(win_rate, 2),
            "Max Drawdown": round(max_dd_pct, 2),
            "Max Drawdown (%)": round(max_dd_pct, 2),
            "Recovery Factor": round(recovery_factor, 2),
            "Max DD Duration": round(max_dd_duration, 1),
            "Sharpe Ratio": round(sharpe, 2),
            "Calmar Ratio": round(calmar, 2),
            "Total Trades": len(trades_df)
        })
        
        return metrics
