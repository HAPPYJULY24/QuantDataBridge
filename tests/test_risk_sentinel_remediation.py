import pytest
import pandas as pd
import numpy as np
import math
from logic.risk_manager_interceptor import RiskManager as Interceptor, RiskConfig, numba_pre_trade_risk_check
from src.core.models.order import OrderRequest, OrderResponse
from src.core.engines.bt_event_driven import EventDrivenBacktest
from src.core.engines.bt_vectorized import VectorizedBacktest


def test_numba_primitive_casting_and_execution():
    """
    Test that casting native primitives avoids Type Inference Conflicts
    and correctly verifies orders through numba_pre_trade_risk_check.
    """
    # 1. Standard parameters
    volume = np.int64(5)       # Simulating NumPy int64 wrapper
    price = np.float32(100.5)  # Simulating NumPy float32 wrapper
    direction = 1              # LONG
    multiplier = 25.0
    current_pos = 0
    used_margin = 0.0
    free_margin = 100000.0
    initial_margin_per_lot = 5000.0
    leverage_limit = 10.0
    account_equity = 100000.0

    # Explicit primitive casting (like in risk_manager_interceptor.py)
    v_vol = int(volume)
    v_price = float(price)
    v_dir = int(direction)
    v_mult = float(multiplier)
    v_curr_pos = int(current_pos)
    v_used_margin = float(used_margin)
    v_free_margin = float(free_margin)
    v_init_margin = float(initial_margin_per_lot)
    v_lev_limit = float(leverage_limit)
    v_equity = float(account_equity)

    # Calling JIT compiler function
    approved_vol = numba_pre_trade_risk_check(
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

    assert approved_vol == 5, f"Expected 5 lots approved, got {approved_vol}"


def test_numba_deadlock_bypass_exit_orders():
    """
    Test the v2.9.5 Sovereign Close-Out Escape Wrapper.
    Even under bankruptcy/negative equity, exit orders must bypass JIT restrictions and be approved.
    """
    cfg = RiskConfig(
        initial_capital=100000.0,
        initial_margin=5000.0,
        risk_target_pct=1.0,
        max_position_size=20,
        multiplier=25.0,
        adx_filter_enabled=False,
        leverage_limit=10.0
    )
    rm = Interceptor(cfg)

    # Force negative bankrupt equity & active position (10 lots Long)
    rm.state.equity = -15000.0
    rm.state.current_pos = 10
    rm.state.used_margin = 50000.0

    # 1. Try to open a NEW LONG position (Should be rejected due to negative equity)
    open_order = OrderRequest(
        symbol="FCPO",
        volume=5,
        direction=1, # LONG entry
        order_type="MARKET",
        price=4000.0,
        timestamp=pd.Timestamp("2026-05-28"),
        atr=20.0,
        adx=25.0
    )
    open_order.is_exit = False
    
    open_response = rm.validate_order(open_order)
    assert not open_response.approved, "Opening order under negative equity must be rejected"

    # 2. Issue emergency Exit Sell order (Should bypass Numba deadlock and be approved)
    exit_order = OrderRequest(
        symbol="FCPO",
        volume=10,
        direction=-1, # SHORT exit
        order_type="MARKET",
        price=3980.0,
        timestamp=pd.Timestamp("2026-05-28"),
        atr=20.0,
        adx=25.0
    )
    exit_order.is_exit = True

    exit_response = rm.validate_order(exit_order)
    assert exit_response.approved, "Emergency exit order was deadlocked! Bypass failed."
    assert exit_response.adjusted_volume == 10, f"Expected 10 lots close approved, got {exit_response.adjusted_volume}"
    assert rm.state.current_pos == 0, "Position should be flattened to 0 after exit bypass"
    assert rm.state.used_margin == 0.0, "Used margin should be fully cleared"


def test_event_driven_gap_liquidation_discretization():
    """
    Verify Event-Driven Overnight Gap Liquidation executes precisely at row.open
    and applies tick size floor/ceil discretization mapping.
    """
    dates = pd.date_range(start="2026-01-01", periods=3, freq="D")
    df = pd.DataFrame({
        'open':  [4000.0, 4050.0, 3600.0],  # Severe gap down on day 3
        'high':  [4020.0, 4060.0, 3620.0],
        'low':   [3990.0, 4030.0, 3580.0],
        'close': [4010.0, 4040.0, 3610.0],
        'factor': [0.0, 0.0, 0.0],
        'atr': [20.0, 20.0, 20.0],
        'adx': [25.0, 25.0, 25.0],
        'signal': [1, 1, 0] # LONG entry on day 1 -> buy at day 2 open (4050)
    }, index=dates)

    engine = EventDrivenBacktest()
    
    # Capital = 6000, margin per lot = 5000 -> 1 lot
    # Maintenance margin rate = 0.8 -> limit = 4000
    # Day 2 entry: buy 1 lot at 4050 (with 1.0 slippage, tick size 1.0) -> entry = 4051.0
    # Day 3 open: gap opens at 3600. PnL at open = (3600 - 4051) * 25.0 * 1 = -11275.
    # Open equity = 6000 - 15 (commission) - 11275 = -5290 < 4000 (breached maint limit!)
    # Must trigger Margin_Call_Gap_Open at row.open = 3600
    # Long gap exit price = Floor((3600 - 1.0) / 1.0) * 1.0 = 3599.0
    
    cfg = RiskConfig(
        initial_capital=6000.0,
        initial_margin=5000.0,
        risk_target_pct=999.0, # Pure lot sizing
        max_position_size=1,
        multiplier=25.0,
        adx_filter_enabled=False,
        leverage_limit=99.0
    )
    
    res = engine.run(
        df=df.copy(),
        asset_symbol="FCPO", # tick_size = 1.0
        RiskManagerClass=lambda *a, **kw: Interceptor(cfg),
        multiplier=25.0,
        commission=15.0,
        slippage=1.0,
        initial_capital=6000.0,
        initial_margin=5000.0,
        allow_lunch=True,
        allow_overnight=True,
        execution_mode='Next Open'
    )
    
    trades = res['trades']
    assert len(trades) == 1
    trade = trades.iloc[0]
    
    assert trade['exit_reason'] == "Margin_Call_Gap_Open"
    assert trade['exit_price'] == 3599.0
    assert trade['requested_price'] == 3600.0 # row.open


def test_vectorized_gap_liquidation_loss_conservation():
    """
    Verify Vectorized Engine captures the full gap liquidation loss on the
    liquidation bar, rounding prices through Floor/Ceil discretizations.
    """
    dates = pd.date_range(start="2026-01-01", periods=3, freq="D")
    df = pd.DataFrame({
        'open':  [4000.0, 4050.0, 3600.0],
        'high':  [4020.0, 4060.0, 3620.0],
        'low':   [3990.0, 4030.0, 3580.0],
        'close': [4010.0, 4040.0, 3610.0],
        'factor': [0.0, 0.0, 0.0],
        'atr': [20.0, 20.0, 20.0],
        'adx': [25.0, 25.0, 25.0]
    }, index=dates)

    # Simulate position: LONG entry on day 2 (pos=1), gap open breach on day 3
    df['pos'] = [0, 1, 1]
    df['pos_raw'] = [0, 1, 1]
    df['ref_price'] = [0.0, 4050.0, 4040.0]
    df['pos_change'] = [0, 1, 0]
    df['cost'] = [0.0, 40.0, 0.0]
    df['gross_pnl'] = [0.0, -250.0, -10000.0] # Dummy values to trigger run
    df['net_pnl'] = [0.0, -290.0, -10000.0]

    engine = VectorizedBacktest()

    # Run liquidation engine
    # Capital = 6000, initial margin = 5000, maint limit = 4000
    res_df = engine._calculate_equity_and_margin(
        df=df.copy(),
        initial_capital=6000.0,
        initial_margin=5000.0,
        maintenance_margin_rate=0.8,
        tick_size=1.0,
        multiplier=25.0,
        slippage=1.0,
        execution_mode='Next Open'
    )

    # Day 3 open = 3600. Gap exit = Floor((3600 - 1) / 1) * 1 = 3599
    # ref_price on Day 3 is 4040.
    # realized loss = (3599 - 4040) * 25.0 * 1 = -441 * 25 = -11025.
    # Expect gross_pnl on day 3 to be exactly -11025.0 (NO loss-wiping to 0.0!)
    assert res_df.loc[dates[2], 'is_liquidated'] == True
    assert res_df.loc[dates[2], 'gross_pnl'] == pytest.approx(-11025.0), f"Expected gross_pnl -11025.0, got {res_df.loc[dates[2], 'gross_pnl']}"
    assert res_df.loc[dates[2], 'pos'] == 0, "Position must be truncated to 0 on liquidation"
