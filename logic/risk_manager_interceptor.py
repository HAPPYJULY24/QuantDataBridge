"""
Risk Manager - Interceptor Pattern
Upgraded from Puppet Mode to active order validation.
"""

import logging
import numba
from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional
import pandas as pd
import numpy as np
import json

@dataclass
class RiskConfig:
    """Immutable Risk Constraints derived strictly from Strategy DNA."""
    initial_capital: float
    initial_margin: float
    risk_target_pct: float
    max_position_size: int
    multiplier: float
    adx_filter_enabled: bool
    adx_threshold: float = 20.0  # Optional fallback if needed by legacy
    leverage_limit: float = 10.0  # Hard leverage limit
    sl_pct: float = 0.0  # Fixed stop-loss percentage

    @staticmethod
    def from_dna(json_path: str) -> "RiskConfig":
        """Loads and parses the strategy_dna.json file into a RiskConfig."""
        with open(json_path, 'r', encoding='utf-8') as f:
            dna = json.load(f)
            
        if "backtest_profile" in dna and "settings" in dna["backtest_profile"]:
            settings = dna.get("backtest_profile", {}).get("settings", {}) or {}
            return RiskConfig(
                initial_capital=float(settings.get("initial_capital", 100000.0)),
                initial_margin=float(settings.get("initial_margin", 5000.0)),
                risk_target_pct=float(settings.get("risk_target", 1.0)),
                max_position_size=int(settings.get("max_lots", 20)),
                multiplier=float(settings.get("multiplier", 25.0)),
                adx_filter_enabled=bool(settings.get("use_adx_filter", False)),
                leverage_limit=float(settings.get("leverage_limit", 10.0)),
                sl_pct=float(settings.get("sl_pct", 0.0))
            )
            
        return RiskConfig(
            initial_capital=float(dna["environment"].get("initial_capital", 100000.0)),
            initial_margin=float(dna["backtest_risk_settings"].get("initial_margin", 5000.0)),
            risk_target_pct=float(dna["backtest_risk_settings"].get("risk_target_pct", 1.0)),
            max_position_size=int(dna["backtest_risk_settings"]["max_position_size"]),
            multiplier=float(dna["friction_costs"]["multiplier"]),
            adx_filter_enabled=bool(dna["execution_constraints"]["adx_filter_enabled"]),
            leverage_limit=float(dna["backtest_risk_settings"].get("leverage_limit", 10.0)),
            sl_pct=float(dna["backtest_risk_settings"].get("stop_loss_value", 0.0))
        )

# Import Phase 1 models
import sys
from pathlib import Path
project_root = Path(__file__).parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.core.models.asset import get_asset_config
from src.core.models.order import OrderRequest, OrderResponse

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)


@numba.njit(cache=True)
def numba_pre_trade_risk_check(
    volume: int,
    price: float,
    direction: int,
    multiplier: float,
    current_pos: int,
    used_margin: float,
    free_margin: float,
    initial_margin_per_lot: float,
    leverage_limit: float,
    account_equity: float
) -> int:
    """
    Numba-compiled high-performance Pre-Trade wind-control safety kernel.
    Execution time: < 100ns. Completely bypasses Python dynamic allocations.
    Returns: approved volume. 0 means rejected.
    """
    if account_equity <= 0.0:
        return 0
        
    order_sign = 1 if direction == 1 else -1
    
    # 1. Margin Affordability Sizing/Clamping
    if current_pos == 0 or (current_pos > 0 and order_sign > 0) or (current_pos < 0 and order_sign < 0):
        # Opening or scaling-in
        required_margin = volume * initial_margin_per_lot
        if required_margin > free_margin:
            if initial_margin_per_lot > 0.0:
                affordable_new = int(free_margin // initial_margin_per_lot)
                volume = max(0, affordable_new)
            else:
                volume = 0
    else:
        # Reversal or Scale-out
        abs_pos = abs(current_pos)
        if abs_pos >= volume:
            # Pure close: always allowed
            return volume
        else:
            # Reversal
            excess_volume = volume - abs_pos
            required_margin = excess_volume * initial_margin_per_lot
            freed_margin = abs_pos * initial_margin_per_lot
            effective_free = free_margin + freed_margin
            if required_margin > effective_free:
                if initial_margin_per_lot > 0.0:
                    affordable_excess = int(effective_free // initial_margin_per_lot)
                    volume = abs_pos + max(0, affordable_excess)
                else:
                    volume = abs_pos
                    
    if volume <= 0:
        return 0
        
    # 2. Hard Leverage Limit Verification
    projected_pos = current_pos + (volume * order_sign)
    if abs(projected_pos) > abs(current_pos):
        notional_exposure = abs(projected_pos) * price * multiplier
        projected_leverage = notional_exposure / account_equity
        
        if projected_leverage > leverage_limit:
            denominator = price * multiplier
            if denominator > 0.0:
                max_pos = int((leverage_limit * account_equity) // denominator)
                allowed_additional = max(0, max_pos - abs(current_pos))
                if current_pos * order_sign < 0:
                    volume = abs(current_pos) + allowed_additional
                else:
                    volume = allowed_additional
            else:
                volume = 0
                
    return volume


@dataclass
class Account_State:
    """Account state tracking."""
    balance: float
    equity: float
    used_margin: float = 0.0
    current_pos: int = 0  # +ve for Long, -ve for Short
    max_drawdown: float = 0.0
    is_liquidated: bool = False
    liquidation_reason: str = ""
    
    @property
    def maintenance_margin(self) -> float:
        """Dynamic maintenance margin baseline (80% of used initial margin)"""
        return self.used_margin * 0.8
    
    @property
    def free_margin(self) -> float:
        return self.equity - self.used_margin
    
    @property
    def margin_level(self) -> float:
        maint = self.maintenance_margin
        if maint == 0:
            return float('inf')
        return self.equity / maint


class RiskManager:
    """
    Risk Manager - Interceptor Pattern.
    
    Validates all order requests through 3-layer pipeline:
    1. Regime Check (ADX filtering)
    2. Position Sizing (ATR-based with margin check)
    3. Margin Sufficiency (using AssetConfig)
    """
    
    def __init__(self, config: RiskConfig):
        """
        Initialize RiskManager.
        100% DNA-driven initialization. No loose kwargs.
        """
        self.config = config
        
        # Initialize Sovereign State Ledger
        self.state = Account_State(
            balance=config.initial_capital, 
            equity=config.initial_capital
        )
        
        # Fallback alias for older references expecting self.params
        self.params = {
            'use_adx': config.adx_filter_enabled,
            'adx_threshold': config.adx_threshold,
            'margin_call_level': 1.1,
            'buffer_ratio': 0.9,
            'margin_per_lot': config.initial_margin,
            'risk_per_trade': config.risk_target_pct / 100.0
        }
        self.multiplier = config.multiplier
        self.initial_capital = config.initial_capital
        
        # Drawdown monitoring baseline
        self._high_water_mark = config.initial_capital
        self._daily_baseline_equity = config.initial_capital
        self._last_bar_equity = config.initial_capital
        self._current_day = None
        
        # Audit Log
        self.audit_log = []
        
    def update_dynamic_margin(self, symbol: str, new_initial_margin: float):
        """Dynamic margin adjustment interface to allow manual/exchange override on the fly."""
        logger.info(f"🔄 [DYNAMIC_MARGIN] Updating initial margin for {symbol}: {self.config.initial_margin} -> {new_initial_margin}")
        self.config.initial_margin = new_initial_margin
        self.params['margin_per_lot'] = new_initial_margin
    
    # ============================================================================
    # BACKWARD COMPATIBILITY (Puppet Mode Methods)
    # ============================================================================
    
    def sync_account_state(self, balance: float, equity: float, current_pos: int, used_margin: float, current_date=None):
        """
        Puppet Mode: Passive State Sync (BACKWARD COMPATIBLE).
        Accept state from BacktestEngine.
        """
        # If already liquidated, do not overwrite the state or check further to preserve original liquidation reason
        if self.state.is_liquidated:
            return

        self.state.balance = balance
        self.state.equity = equity
        self.state.current_pos = current_pos
        self.state.used_margin = used_margin
        
        # 1. Daily baseline tracking with Gap Risk Protection
        if current_date is not None:
            # Check if current_date is a datetime-like object or has a date method
            if hasattr(current_date, 'date'):
                bar_day = current_date.date()
            elif isinstance(current_date, str) and len(current_date) >= 10:
                bar_day = current_date[:10]
            else:
                # If it's an integer or other non-date type, do not perform daily reset
                bar_day = None

            if bar_day is not None and self._current_day != bar_day:
                # Today's baseline is yesterday's final closing equity to capture Overnight Gap risk
                self._daily_baseline_equity = getattr(self, '_last_bar_equity', equity)
                self._current_day = bar_day
                
        # Cache current Bar equity for the next day's reset
        self._last_bar_equity = equity
            
        # 2. Update High-Water Mark
        if equity > self._high_water_mark:
            self._high_water_mark = equity
            
        # 3. Compute drawdown metrics
        peak_drawdown = (self._high_water_mark - equity) / self._high_water_mark if self._high_water_mark > 0 else 0.0
        daily_drawdown = (self._daily_baseline_equity - equity) / self._daily_baseline_equity if self._daily_baseline_equity > 0 else 0.0
        
        # 4. Check for liquidations (Drawdown & Margin Call)
        if peak_drawdown > 0.35:
            self.state.is_liquidated = True
            self.state.liquidation_reason = f"Peak Drawdown Breach: {peak_drawdown:.2%} > 35%"
            return
            
        if daily_drawdown > 0.20:
            self.state.is_liquidated = True
            self.state.liquidation_reason = f"Daily Drawdown Breach: {daily_drawdown:.2%} > 20%"
            return
            
        # 5. Margin Call Liquidation check (using Maintenance Margin)
        if self.state.margin_level < 1.0:
            self.state.is_liquidated = True
            self.state.liquidation_reason = (
                f"Margin Call Liquidation: Equity ({self.state.equity:.2f}) "
                f"fell below Maintenance Margin ({self.state.maintenance_margin:.2f})"
            )
    
    def check_regime(self, row: pd.Series, signal: int) -> int:
        """
        BACKWARD COMPATIBLE: Legacy regime check.
        For use in old code that doesn't use OrderRequest.
        """
        if not self.params['use_adx']:
            return signal
        
        if signal == 0:
            return 0
        
        if 'ADX' not in row:
            return signal
        
        if row['ADX'] < self.params['adx_threshold']:
            self.audit_log.append({
                'Date': row.get('Date') if isinstance(row, dict) else row.name,
                'Type': 'Regime_Audit',
                'Action': 'Blocked',
                'Details': f"ADX {row['ADX']:.2f} < {self.params['adx_threshold']}"
            })
            return 0
        
        return signal
    
    def calculate_lots(self, atr: float, entry_price: float = 0.0, stop_loss_dist: float = 0.0) -> int:
        """
        BACKWARD COMPATIBLE: Legacy position sizing with math alignment.
        For use in old code that doesn't use OrderRequest.
        """
        if atr is None or pd.isna(atr) or atr <= 0:
            return 0
        
        sizing_equity = min(self.initial_capital, self.state.equity)
        risk_amount = sizing_equity * self.params['risk_per_trade']
        
        # Pyramid risk distance priority
        if stop_loss_dist > 0.0:
            risk_distance = stop_loss_dist
        elif self.config.sl_pct > 0.0 and entry_price > 0.0:
            risk_distance = entry_price * (self.config.sl_pct / 100.0)
        else:
            risk_distance = atr * 2.0
            
        volatility_value = risk_distance * self.multiplier
        
        if volatility_value == 0:
            return 1  # Minimum defensive lots
        
        target_lots = int(risk_amount / volatility_value)
        
        # Margin check
        if self.params['margin_per_lot'] > 0:
            max_allowed_lots = int((self.state.free_margin * self.params['buffer_ratio']) / 
                                  self.params['margin_per_lot'])
        else:
            max_allowed_lots = 999
        
        final_lots = min(target_lots, max_allowed_lots, self.config.max_position_size)
        final_lots = max(1, final_lots)  # Minimum 1 lot if sized
        
        if final_lots < target_lots:
            self.audit_log.append({
                'Type': 'Position_Sizing',
                'Action': 'Reduced',
                'Details': f"Target {target_lots} -> {final_lots} (Safety Cap/Margin)"
            })
        
        return final_lots
    
    def check_intra_bar(
        self, 
        row: pd.Series, 
        entry_price: float, 
        sl_price: float, 
        tp_price: Optional[float] = None
    ) -> Tuple[bool, str, float]:
        """BACKWARD COMPATIBLE: Intra-bar stop loss monitor."""
        current_pos = self.state.current_pos
        
        if current_pos == 0:
            return False, "", 0.0
        
        open_p = row['open']
        high_p = row['high']
        low_p = row['low']
        
        # Margin level warning
        margin_level = self.state.margin_level
        if margin_level < self.params['margin_call_level']:
            logger.critical(f"\033[91mCRITICAL ALERT: Low Margin Level {margin_level:.2f}!\033[0m")
        
        # LONG positions
        if current_pos > 0:
            if open_p < sl_price:
                return True, "Gap_SL", open_p
            if low_p < sl_price:
                return True, "Intra_SL", sl_price
            if tp_price and high_p > tp_price:
                return True, "Intra_TP", tp_price
        
        # SHORT positions
        elif current_pos < 0:
            if open_p > sl_price:
                return True, "Gap_SL", open_p
            if high_p > sl_price:
                return True, "Intra_SL", sl_price
            if tp_price and low_p < tp_price:
                return True, "Intra_TP", tp_price
        
        return False, "", 0.0
    
    # ============================================================================
    # NEW INTERCEPTOR PATTERN METHODS
    # ============================================================================
    
    def validate_order(self, order: OrderRequest) -> OrderResponse:
        """
        4-Layer Order Validation Pipeline (INTERCEPTOR PATTERN).
        
        Pipeline:
        1. Layer 1: check_regime_layer (ADX filtering)
        2. Layer 2: calculate_risk_pos_layer (ATR/sl_pct-aligned sizing)
        3. Layer 3: check_margin_layer (Margin sufficiency with smart truncation)
        4. Layer 4: check_leverage_layer (Hard leverage limit verification)
        
        Args:
            order: OrderRequest object
        
        Returns:
            OrderResponse (approved/rejected with reason)
        """
        # Wind-control Interceptor Check: Reject all new entries if liquidated, but allow exit orders
        if getattr(self.state, 'is_liquidated', False):
            if not getattr(order, 'is_exit', False):
                reason = getattr(self.state, 'liquidation_reason', "Account Liquidated")
                response = OrderResponse.reject(reason=f"Rejected: {reason}. Opening forbidden.")
                self._log_rejection(order, response)
                return response
            
        # --- CRITICAL FIX: Direct Bypass Pipeline for Exit/Close Orders ---
        if getattr(order, 'is_exit', False):
            order_sign = 1 if order.direction_str == 'LONG' else -1
            # Ensure exit orders ONLY reduce existing positions. Never allow net new reverse positioning.
            current_pos = self.state.current_pos
            if current_pos == 0:
                return OrderResponse.reject(reason="Exit order rejected: No active position to close.")
            if np.sign(current_pos) == np.sign(order_sign):
                return OrderResponse.reject(reason="Exit order rejected: Direction increases risk exposure.")
            
            # Clamp the exit volume to maximum of current active lots to prevent reversal opening
            allowed_exit_volume = min(order.volume, abs(current_pos))
            new_pos = current_pos + (allowed_exit_volume * order_sign)
            self.state.current_pos = new_pos
            self.state.used_margin = abs(new_pos) * self.config.initial_margin
            
            final_response = OrderResponse.approve(
                volume=allowed_exit_volume,
                reason=f"Exit Order: Executed safe close portion of {allowed_exit_volume} lots. Excess volume of {order.volume - allowed_exit_volume} discarded."
            )
            self._log_approval(order, final_response)
            return final_response
            
        # Layer 1: Regime Check
        regime_response = self._check_regime_layer(order)
        if not regime_response.approved:
            self._log_rejection(order, regime_response)
            return regime_response
            
        # Layer 2: Position Sizing
        sizing_response = self._calculate_risk_pos_layer(order)
        if not sizing_response.approved:
            self._log_rejection(order, sizing_response)
            return sizing_response
        approved_vol = sizing_response.adjusted_volume
        
        # Layer 3: Margin Check
        margin_response = self._check_margin_layer(order, approved_vol)
        if not margin_response.approved:
            self._log_rejection(order, margin_response)
            return margin_response
        approved_vol = margin_response.adjusted_volume
        
        # Layer 4: Leverage Check
        leverage_response = self._check_leverage_layer(order, approved_vol)
        if not leverage_response.approved:
            self._log_rejection(order, leverage_response)
            return leverage_response
        approved_vol = leverage_response.adjusted_volume
        
        # --- High-Speed JIT Verification Gate ---
        try:
            v_vol = int(approved_vol)
            v_price = float(order.price)
            v_dir = int(order.direction)
            v_mult = float(self.config.multiplier)
            v_curr_pos = int(self.state.current_pos)
            v_used_margin = float(self.state.used_margin)
            v_free_margin = float(self.state.free_margin)
            v_init_margin = float(self.config.initial_margin)
            v_lev_limit = float(self.config.leverage_limit)
            v_equity = float(self.state.equity)
        except (ValueError, TypeError) as casting_err:
            response = OrderResponse.reject(reason=f"Type Casting Failure for Numba Core: {casting_err}")
            self._log_rejection(order, response)
            return response
            
        jit_approved_vol = numba_pre_trade_risk_check(
            volume=v_vol,
            price=v_price,
            direction=v_dir,
            multiplier=v_mult,
            current_pos=v_curr_pos,
            used_margin=v_used_margin,
            free_margin=v_free_margin,
            initial_margin_per_lot=v_init_margin,
            leverage_limit=v_lev_limit,
            account_equity=v_equity
        )
        
        if jit_approved_vol < approved_vol:
            approved_vol = jit_approved_vol
            
        if approved_vol <= 0:
            response = OrderResponse.reject(
                reason="Rejected by Wind-Control JIT: Insufficient capital or leverage limit breached."
            )
            self._log_rejection(order, response)
            return response
            
        # Commit Net Margin Lock and synchronize
        order_sign = 1 if order.direction_str == 'LONG' else -1
        new_pos = self.state.current_pos + (approved_vol * order_sign)
        self.state.current_pos = new_pos
        self.state.used_margin = abs(new_pos) * self.config.initial_margin
        
        # Formulate the correct final OrderResponse
        if approved_vol == order.volume:
            final_response = OrderResponse.approve(
                volume=approved_vol,
                reason="Validated: All checks passed. Net Margin Locked via JIT."
            )
            self._log_approval(order, final_response)
            return final_response
        else:
            # Determine which layer or JIT caused the final truncation/adjustment
            if approved_vol == jit_approved_vol and jit_approved_vol < leverage_response.adjusted_volume:
                reason = "Adjusted by Wind-Control JIT: Reduced to fit affordable margin or leverage limits."
                details = {'jit_approved': jit_approved_vol}
            elif leverage_response.adjusted_volume < margin_response.adjusted_volume:
                reason = leverage_response.reason
                details = leverage_response.details
            elif margin_response.adjusted_volume < sizing_response.adjusted_volume:
                reason = margin_response.reason
                details = margin_response.details
            else:
                reason = sizing_response.reason
                details = sizing_response.details
                
            final_response = OrderResponse.adjust(
                original_volume=order.volume,
                adjusted_volume=approved_vol,
                reason=reason,
                details=details
            )
            self._log_adjustment(order, final_response)
            return final_response
    
    def _check_regime_layer(self, order: OrderRequest) -> OrderResponse:
        """Layer 1: ADX Regime Filter."""
        if not self.params['use_adx']:
            return OrderResponse.approve(order.volume, "Regime: ADX check disabled")
        
        # Check for NaN to prevent NaN-swallowing regime bypass
        if pd.isna(order.adx) or np.isnan(order.adx):
            return OrderResponse.reject(reason="Regime: ADX value is NaN. Blocked entry.")

        if order.adx < self.params['adx_threshold']:
            return OrderResponse.reject(
                reason=f"Regime: ADX too low ({order.adx:.2f} < {self.params['adx_threshold']})",
                details={'adx': order.adx, 'threshold': self.params['adx_threshold']}
            )
        
        return OrderResponse.approve(order.volume, f"Regime: ADX {order.adx:.2f} OK")
    
    def _calculate_risk_pos_layer(self, order: OrderRequest) -> OrderResponse:
        """Layer 2: Sovereign Sizing aligned mathematically with stop-loss specifications."""
        if order.atr is None or pd.isna(order.atr) or order.atr <= 0:
            return OrderResponse.reject(
                reason=f"Position Sizing: Invalid ATR ({order.atr})",
                details={'atr': order.atr}
            )
        
        # Calculate raw risk amount
        risk_per_trade = self.config.risk_target_pct / 100.0
        sizing_equity = min(self.config.initial_capital, self.state.equity)
        if sizing_equity <= 0:
            return OrderResponse.reject(reason="[BANKRUPTCY_BREACH] Position Sizing Blocked: Equity is non-positive or bankrupt.")
            
        risk_amount = sizing_equity * risk_per_trade
        
        # Risk distance hierarchy
        if self.config.sl_pct > 0.0 and order.price > 0.0:
            # Fixed percentage stop loss: align risk distance to sl_pct
            risk_distance = order.price * (self.config.sl_pct / 100.0)
        else:
            # Fallback to standard 2 * ATR
            risk_distance = order.atr * 2.0
            
        volatility_value = risk_distance * self.config.multiplier
        
        if volatility_value <= 0:
            return OrderResponse.reject(reason="Invalid volatility mapping")
            
        target_lots = int(risk_amount / volatility_value)
        
        # Apply DNA max bounds
        final_lots = min(max(target_lots, 1), self.config.max_position_size)
        
        # Ensure we don't exceed the requested volume either
        final_lots = min(final_lots, order.volume)
        if final_lots == 0:
            return OrderResponse.reject(reason="Position Sizing: Zero lots calculated")
            
        return OrderResponse.approve(final_lots, "Position Sizing OK")
    
    def _check_margin_layer(self, order: OrderRequest, approved_volume: int) -> OrderResponse:
        """Layer 3: Absolute Directional Margin Verification & Smart Truncation."""
        order_sign = 1 if order.direction_str == 'LONG' else -1
        curr_pos = self.state.current_pos
        
        # Check for NaN in equity or free margin to prevent NaN-swallowing order bypass
        if pd.isna(self.state.equity) or np.isnan(self.state.equity) or pd.isna(self.state.free_margin) or np.isnan(self.state.free_margin):
            return OrderResponse.reject(reason="[NaN_EXPOSURE_BREACH] Margin check rejected: Account equity or free margin is NaN.")

        # 1. Determine Closing vs New Exposure
        if curr_pos == 0 or (curr_pos > 0 and order_sign > 0) or (curr_pos < 0 and order_sign < 0):
            closing_lots = 0
            new_lots = approved_volume
        else:
            if abs(curr_pos) >= approved_volume:
                closing_lots = approved_volume
                new_lots = 0
            else:
                closing_lots = abs(curr_pos)
                new_lots = approved_volume - abs(curr_pos)
                
        # 2. Calculate Effective Margin
        freed_margin = closing_lots * self.config.initial_margin
        effective_free_margin = self.state.free_margin + freed_margin
        required_margin = new_lots * self.config.initial_margin
        
        # 3. Affordability Check
        if required_margin > effective_free_margin:
            # Smart Truncation
            if self.config.initial_margin > 0:
                safe_free_margin = max(0.0, effective_free_margin)
                affordable_new_lots = int(safe_free_margin // self.config.initial_margin)
            else:
                affordable_new_lots = new_lots
                
            affordable_total_lots = max(0, closing_lots + affordable_new_lots)
            
            if affordable_total_lots == 0:
                return OrderResponse.reject(
                    reason="[LEVERAGE_WARNING] Margin Call: Zero affordable lots",
                    details={'required_margin': required_margin, 'effective_free_margin': effective_free_margin}
                )
            else:
                return OrderResponse.adjust(
                    original_volume=approved_volume,
                    adjusted_volume=affordable_total_lots,
                    reason="[LEVERAGE_WARNING] Adjust: Margin Call Prevention - Reduced to affordable lots",
                    details={'required_margin': required_margin, 'effective_free_margin': effective_free_margin, 'affordable_new_lots': affordable_new_lots, 'closing_lots': closing_lots}
                )
                
        return OrderResponse.approve(
            approved_volume,
            f"Margin Verified (closing: {closing_lots}, new: {new_lots}, required: {required_margin:.2f})",
            details={'required_margin': required_margin, 'freed_margin': freed_margin, 'new_lots': new_lots}
        )

    def _check_leverage_layer(self, order: OrderRequest, approved_volume: int) -> OrderResponse:
        """Layer 4: Hard Leverage Limit Interception & Smart Truncation."""
        order_sign = 1 if order.direction_str == 'LONG' else -1
        curr_pos = self.state.current_pos
        
        # Calculate projected net position
        projected_pos = curr_pos + (approved_volume * order_sign)
        
        # If position size is decreasing or reversing to a smaller absolute size, approve immediately
        if abs(projected_pos) <= abs(curr_pos):
            return OrderResponse.approve(approved_volume, "Leverage: Position reduction approved")
            
        # --- CRITICAL FIX: Block new positions if account equity is bankrupt/negative ---
        if self.state.equity <= 0:
            return OrderResponse.reject(
                reason="[BANKRUPTCY_BREACH] Leverage check rejected: Account equity is non-positive or bankrupt."
            )
            
        # Calculate Real Notional Leverage: Notional Exposure / Equity
        # Notional Exposure = abs(Projected Pos) * Entry Price * Multiplier
        projected_notional_exposure = abs(projected_pos) * order.price * self.config.multiplier
        
        # Check for NaN in equity or notional exposure to prevent NaN-swallowing order bypass
        if pd.isna(self.state.equity) or np.isnan(self.state.equity) or pd.isna(projected_notional_exposure) or np.isnan(projected_notional_exposure):
            return OrderResponse.reject(
                reason="[NaN_EXPOSURE_BREACH] Leverage check rejected: Account equity or projected leverage is NaN."
            )

        projected_leverage = projected_notional_exposure / self.state.equity
        
        # Check for NaN in projected leverage
        if pd.isna(projected_leverage) or np.isnan(projected_leverage):
            return OrderResponse.reject(
                reason="[NaN_EXPOSURE_BREACH] Leverage check rejected: Projected leverage is NaN."
            )
        
        if projected_leverage > self.config.leverage_limit:
            # Smart Truncation to fit leverage limit using price and multiplier
            if order.price > 0 and self.config.multiplier > 0:
                max_allowed_pos = int((self.config.leverage_limit * self.state.equity) // (order.price * self.config.multiplier))
            else:
                max_allowed_pos = approved_volume
                
            # --- CRITICAL FIX: Handle Reversal properly under leverage checks ---
            is_reversal = (curr_pos > 0 and order_sign < 0) or (curr_pos < 0 and order_sign > 0)
            if is_reversal:
                # First abs(curr_pos) is just closing, then we can open up to max_allowed_pos
                allowed_additional = abs(curr_pos) + max_allowed_pos
            else:
                allowed_additional = max(0, max_allowed_pos - abs(curr_pos))
            
            if allowed_additional == 0:
                return OrderResponse.reject(
                    reason=f"Leverage Breach: Projected leverage {projected_leverage:.2f}x exceeds limit {self.config.leverage_limit:.2f}x (Zero additional volume allowed)"
                )
            elif allowed_additional < approved_volume:
                return OrderResponse.adjust(
                    original_volume=approved_volume,
                    adjusted_volume=allowed_additional,
                    reason=f"Leverage Breach Prevention: Truncated to fit {self.config.leverage_limit:.2f}x leverage limit"
                )
                
            return OrderResponse.reject(
                reason=f"Leverage Breach: Projected leverage {projected_leverage:.2f}x exceeds limit {self.config.leverage_limit:.2f}x"
            )
            
        return OrderResponse.approve(approved_volume, "Leverage Check Passed")
    
    def _log_rejection(self, order: OrderRequest, response: OrderResponse):
        """Log rejected order to audit trail."""
        self.audit_log.append({
            'Type': 'Order_Rejected',
            'Symbol': order.symbol,
            'Direction': order.direction_str,
            'Requested_Volume': order.volume,
            'Reason': response.reason,
            'Details': response.details
        })
        logger.warning(f"🚫 [ORDER REJECTED] {order.symbol} {order.direction_str} x{order.volume}: {response.reason}")
    
    def _log_adjustment(self, order: OrderRequest, response: OrderResponse):
        """Log adjusted order to audit trail."""
        self.audit_log.append({
            'Type': 'Order_Adjusted',
            'Symbol': order.symbol,
            'Direction': order.direction_str,
            'Requested_Volume': order.volume,
            'Approved_Volume': response.adjusted_volume,
            'Reason': response.reason,
            'Details': response.details
        })
        logger.info(f"⚠️ [ORDER ADJUSTED] {order.symbol} {order.direction_str}: {order.volume} -> {response.adjusted_volume}")
    
    def _log_approval(self, order: OrderRequest, response: OrderResponse):
        """Log approved order to audit trail."""
        self.audit_log.append({
            'Type': 'Order_Approved',
            'Symbol': order.symbol,
            'Direction': order.direction_str,
            'Volume': response.adjusted_volume,
            'Reason': response.reason
        })
        logger.info(f"✅ [ORDER APPROVED] {order.symbol} {order.direction_str} x{response.adjusted_volume}")
    
    def get_audit_dataframe(self) -> pd.DataFrame:
        """Get audit log as DataFrame."""
        return pd.DataFrame(self.audit_log)
