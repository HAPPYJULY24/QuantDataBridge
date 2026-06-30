"""
Portfolio Risk Manager - Multi-Asset Portfolio Risk Control

Phase 5E: Infrastructure preparation for Portfolio Management feature.
This is a STUB implementation to establish the foundation for future portfolio backtesting.
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import pandas as pd
import numpy as np


@dataclass
class PortfolioPosition:
    """
    Represents a position within a portfolio.
    
    Attributes:
        symbol: Asset symbol
        asset_type: Type of asset (futures, stock, etc.)
        quantity: Number of contracts/shares (positive = long, negative = short)
        avg_price: Average entry price
        current_price: Current market price
        unrealized_pnl: Mark-to-market PnL
        margin_used: Margin requirement for this position
    """
    symbol: str
    asset_type: str
    quantity: float
    avg_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    margin_used: float = 0.0
    
    def update_price(self, new_price: float, multiplier: float = 1.0) -> None:
        """
        Update current price and recalculate unrealized PnL.
        
        Args:
            new_price: New market price
            multiplier: Contract multiplier (for futures)
        """
        self.current_price = new_price
        price_diff = (new_price - self.avg_price) * np.sign(self.quantity)
        self.unrealized_pnl = price_diff * abs(self.quantity) * multiplier


class PortfolioRiskManager:
    """
    Portfolio-level risk management for multi-asset strategies.
    
    This is a STUB implementation. Future enhancements will include:
    - Correlation-based position sizing
    - Portfolio-level stop loss
    - Asset allocation constraints
    - Sector exposure limits
    - VaR (Value at Risk) calculations
    """
    
    def __init__(
        self,
        max_portfolio_risk: float = 0.02,
        max_correlation_weight: float = 0.7,
        max_sector_concentration: float = 0.4
    ):
        """
        Initialize portfolio risk manager.
        
        Args:
            max_portfolio_risk: Maximum portfolio risk as fraction of NAV (default 2%)
            max_correlation_weight: Maximum weight adjustment for correlated assets
            max_sector_concentration: Maximum exposure to single sector (default 40%)
        """
        self.max_portfolio_risk = max_portfolio_risk
        self.max_correlation_weight = max_correlation_weight
        self.max_sector_concentration = max_sector_concentration
        
        # Portfolio state
        self.positions: Dict[str, PortfolioPosition] = {}
        self.nav: float = 0.0  # Net Asset Value
        self.cash: float = 0.0
        
    def calculate_portfolio_risk(self) -> float:
        """
        Calculate total portfolio risk.
        
        Returns:
             Portfolio risk as fraction of NAV (Margin Utilization)
        """
        if self.nav <= 0:
            return 0.0
        
        total_margin = sum(pos.margin_used for pos in self.positions.values())
        return total_margin / self.nav
    
    def check_position_limit(
        self, 
        symbol: str, 
        proposed_quantity: float,
        correlation_matrix: Optional[pd.DataFrame] = None
    ) -> Tuple[bool, str]:
        """
        Check if proposed position is within portfolio risk limits.
        
        Args:
            symbol: Asset symbol
            proposed_quantity: Proposed position size
            correlation_matrix: Optional correlation matrix for diversification checks
        
        Returns:
            (is_allowed, reason)
        """
        # STUB: Basic check only
        # Future: Add correlation-based limits
        
        current_risk = self.calculate_portfolio_risk()
        if current_risk > self.max_portfolio_risk:
            return False, f"Portfolio risk {current_risk:.2%} exceeds limit {self.max_portfolio_risk:.2%}"
        
        return True, "OK"
    
    def update_position(
        self, 
        symbol: str, 
        asset_type: str,
        quantity: float, 
        price: float,
        multiplier: float = 1.0
    ) -> None:
        """
        Update or create a position in the portfolio with scale-in, scale-out,
        reversal, and full-close accounting.
        
        Args:
            symbol: Asset symbol
            asset_type: Asset type
            quantity: Position size (positive = long, negative = short, 0 = flat)
            price: Execution price
            multiplier: Contract multiplier
        """
        # Resolve initial margin from asset config
        try:
            from src.core.models.asset import get_asset_config
            asset_cfg = get_asset_config(symbol)
            initial_margin = asset_cfg.initial_margin
        except Exception:
            initial_margin = 5000.0  # Safe fallback

        if symbol not in self.positions:
            if quantity != 0:
                self.positions[symbol] = PortfolioPosition(
                    symbol=symbol,
                    asset_type=asset_type,
                    quantity=quantity,
                    avg_price=price,
                    current_price=price,
                    margin_used=abs(quantity) * initial_margin
                )
        else:
            pos = self.positions[symbol]
            if quantity == 0:
                self.positions.pop(symbol)
                return
                
            # A. Reversal scenario: direction of position changes
            if np.sign(quantity) != np.sign(pos.quantity):
                pos.avg_price = price
                pos.asset_type = asset_type
            
            # B. Scale-in scenario: same direction, size increases in absolute terms
            elif abs(quantity) > abs(pos.quantity):
                added_lots = abs(quantity - pos.quantity)
                old_total_cost = pos.avg_price * abs(pos.quantity)
                new_incremental_cost = price * added_lots
                pos.avg_price = (old_total_cost + new_incremental_cost) / abs(quantity)
                
            # C. Scale-out scenario: same direction, size decreases in absolute terms
            # Average entry price remains unchanged.
            
            # Update quantity, margin_used and recalculate PnL at the new price
            pos.quantity = quantity
            pos.margin_used = abs(quantity) * initial_margin
            pos.update_price(price, multiplier)
    
    def get_portfolio_summary(self) -> Dict:
        """
        Get portfolio summary statistics.
        
        Returns:
            Dictionary with portfolio metrics
        """
        total_positions = len(self.positions)
        total_unrealized_pnl = sum(pos.unrealized_pnl for pos in self.positions.values())
        total_margin = sum(pos.margin_used for pos in self.positions.values())
        
        return {
            "Total Positions": total_positions,
            "NAV": self.nav,
            "Cash": self.cash,
            "Total Unrealized PnL": total_unrealized_pnl,
            "Total Margin Used": total_margin,
            "Portfolio Risk": self.calculate_portfolio_risk(),
            "Margin Utilization": total_margin / self.nav if self.nav > 0 else 0.0
        }
    
    def reset(self) -> None:
        """Reset portfolio to initial state."""
        self.positions.clear()
        self.nav = 0.0
        self.cash = 0.0
