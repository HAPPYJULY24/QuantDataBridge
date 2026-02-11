
import logging
from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional
import pandas as pd
import numpy as np

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

@dataclass
class Account_State:
    balance: float
    equity: float
    used_margin: float = 0.0
    current_pos: int = 0  # +ve for Long, -ve for Short
    max_drawdown: float = 0.0
    is_liquidated: bool = False
    
    @property
    def free_margin(self) -> float:
        return self.equity - self.used_margin
    
    @property
    def margin_level(self) -> float:
        if self.used_margin == 0:
            return float('inf')
        return self.equity / self.used_margin

class RiskManager:
    def __init__(
        self, 
        initial_capital: float = 100000.0, 
        multiplier: float = 25.0, 
        risk_params: Optional[Dict] = None
    ):
        """
        Initialize the RiskManager.
        
        Args:
            initial_capital (float): Starting capital.
            multiplier (float): Contract point value multiplier (e.g., 25 for FCPO).
            risk_params (dict): Dictionary containing risk parameters.
                - use_adx (bool): Enable ADX filter.
                - adx_threshold (float): Minimum ADX to allow trading.
                - risk_per_trade (float): Risk % per trade (e.g., 0.02 for 2%).
                - buffer_ratio (float): Buffer for margin check (default 0.9).
                - margin_per_lot (float): Margin required per lot.
        """
        self.initial_capital = initial_capital
        self.multiplier = multiplier
        
        # Default risk parameters
        self.params = {
            'use_adx': True,
            'adx_threshold': 20.0,
            'risk_per_trade': 0.02,
            'buffer_ratio': 0.9,
            'margin_per_lot': 5000.0, # Example default
            'margin_call_level': 1.1  # Alert level
        }
        
        if risk_params:
            self.params.update(risk_params)
            
        # Initialize state
        self.state = Account_State(balance=initial_capital, equity=initial_capital)
        
        # Audit Log
        self.audit_log = []
        
    def sync_account_state(self, balance: float, equity: float, current_pos: int, used_margin: float):
        """
        Puppet Mode: Passive State Sync.
        Strictly accept state from BacktestEngine (The Dictator).
        """
        self.state.balance = balance
        self.state.equity = equity
        self.state.current_pos = current_pos
        self.state.used_margin = used_margin
        
        # Real-time Liquidation Check
        if self.state.margin_level < 1.0:
            self.state.is_liquidated = True

    def check_regime(self, row: pd.Series, signal: int) -> int:
        """
        Layer 1: Regime Audit (Environmental Filter)
        If ADX < Threshold, force signal to 0.
        """
        if not self.params['use_adx']:
            return signal
            
        if signal == 0:
            return 0
            
        # Check if ADX exists in row
        if 'ADX' not in row:
            # logger.warning("ADX not found in data. Skipping Regime Audit.") # Too noisy
            return signal
            
        if row['ADX'] < self.params['adx_threshold']:
            self.audit_log.append({
                'Date': row.get('Date') if isinstance(row, dict) else row.name, # Handle dict or Series
                'Type': 'Regime_Audit',
                'Action': 'Blocked',
                'Details': f"ADX {row['ADX']:.2f} < {self.params['adx_threshold']}"
            })
            return 0
            
        return signal

    def calculate_lots(self, atr: float, stop_loss_dist: float = 0.0) -> int:
        """
        Layer 2: Position Sizing
        Target Lots = (Equity * Risk%) / (Risk_Distance * Multiplier)
        If stop_loss_dist is 0, use ATR-based estimation (e.g. 2 * ATR)
        
        Includes "One-vote veto" (Margin Check) with Buffer.
        """
        # [FIX 1] Hardened defense against NaN/Zero/Negative ATR
        if atr is None or pd.isna(atr) or atr <= 0:
            return 0 

        risk_per_trade = self.params['risk_per_trade']
        multiplier = self.multiplier
        equity = self.state.equity
        buffer_ratio = self.params['buffer_ratio']
        margin_per_lot = self.params['margin_per_lot']
        
        # [FIX 2] Anti-Compounding: Use min(initial, equity)
        sizing_equity = min(self.initial_capital, self.state.equity)
        
        risk_amount = sizing_equity * risk_per_trade
        volatility_value = atr * multiplier
        
        if volatility_value == 0:
            return 0
            
        target_lots = int(risk_amount / volatility_value)
        
        # 2. Free Margin Check with Buffer
        # buffer_ratio (e.g. 0.9) leaves 10% room
        if margin_per_lot > 0:
            max_allowed_lots = int((self.state.free_margin * buffer_ratio) / margin_per_lot)
        else:
            max_allowed_lots = 999
        
        # 3. Final Sizing
        final_lots = min(target_lots, max_allowed_lots)
        
        # [FIX 3] Hard Cap (Safety Lock)
        final_lots = min(final_lots, 20) 
        
        final_lots = max(0, final_lots) # Ensure non-negative
        
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
        """
        Layer 3: Intra-bar Monitor
        Simulate High/Low path.
        Conservative Order: 
        1. Check Open vs SL (Gap)
        2. Check Low vs SL (Long) / High vs SL (Short)
        3. Check High vs TP (Long) / Low vs TP (Short) -> (Not strictly required by task but good practice)
        
        Returns:
            (is_closed: bool, reason: str, exit_price: float)
        """
        current_pos = self.state.current_pos
        
        if current_pos == 0:
            return False, "", 0.0
            
        open_p = row['open']
        high_p = row['high']
        low_p = row['low']
        
        # Monitor Margin Level
        margin_level = self.state.margin_level
        if margin_level < self.params['margin_call_level']:
            logger.critical(f"\033[91mCRITICAL ALERT: Low Margin Level {margin_level:.2f}!\033[0m")

        # --- LONG POSITIONS ---
        if current_pos > 0:
            # 1. Gap Check
            if open_p < sl_price:
                return True, "Gap_SL", open_p
            
            # 2. Intra-bar Low Check (Conservative: Check SL First)
            if low_p < sl_price:
                return True, "Intra_SL", sl_price
                
            # 3. TP Check (Optional, assuming checking SL only for this task mainly, 
            # but usually we check TP after SL if SL not hit)
            if tp_price and high_p > tp_price:
                return True, "Intra_TP", tp_price

        # --- SHORT POSITIONS ---
        elif current_pos < 0:
            # 1. Gap Check
            if open_p > sl_price:
                return True, "Gap_SL", open_p
                
            # 2. Intra-bar High Check
            if high_p > sl_price:
                return True, "Intra_SL", sl_price
                
            # 3. TP Check
            if tp_price and low_p < tp_price:
                return True, "Intra_TP", tp_price
                
        return False, "", 0.0

    def get_audit_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(self.audit_log)
