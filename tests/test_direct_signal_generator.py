import sys
import pytest
import pandas as pd
import numpy as np
from PyQt6.QtWidgets import QApplication, QMessageBox
from src.core.signal_generator import SignalFactory, DirectSignalGenerator
from ui.tabs.backtest_tab import BacktestTab

def test_direct_signal_generator_basic():
    # Create generator
    generator = SignalFactory.create("Direct Signal")
    assert isinstance(generator, DirectSignalGenerator)
    
    # Create a test dataframe with datetime index to test index alignment
    dates = pd.date_range("2026-06-04", periods=10, freq="min")
    df = pd.DataFrame({
        "factor": [
            0.5, 1.2, 0.0, -0.5, -1.5, 
            0.49, -0.49, np.nan, "0.8", "-0.9"
        ]
    }, index=dates)
    
    signals = generator.generate(df)
    
    # 1. Assert type and index alignment (no list conversion that ignores index)
    assert isinstance(signals, pd.Series)
    assert signals.index.equals(df.index), "Returned signals index must exactly match df index!"
    
    # 2. Assert values with pandas testing utility
    expected = pd.Series([1, 1, 0, -1, -1, 0, 0, 0, 1, -1], index=dates, dtype=np.int32)
    pd.testing.assert_series_equal(signals.astype(int), expected.astype(int), check_names=False)

def test_direct_signal_generator_ignores_bounds():
    generator = SignalFactory.create("Direct Signal")
    
    dates = pd.date_range("2026-06-04", periods=4, freq="min")
    df = pd.DataFrame({
        "factor": [0.3, -0.3, 0.8, -0.8]
    }, index=dates)
    
    # Pass custom bounds, but the generator should ignore them and still use >= 0.5 and <= -0.5
    signals = generator.generate(df, upper_bound=0.2, lower_bound=-0.2)
    
    assert isinstance(signals, pd.Series)
    assert signals.index.equals(df.index), "Returned signals index must exactly match df index!"
    
    expected = pd.Series([0, 0, 1, -1], index=dates, dtype=int)
    pd.testing.assert_series_equal(signals.astype(int), expected, check_names=False)

def test_direct_signal_generator_missing_column():
    generator = SignalFactory.create("Direct Signal")
    
    # Create a DataFrame without the 'factor' column to test missing column fallback
    dates = pd.date_range("2026-06-04", periods=5, freq="min")
    df = pd.DataFrame({
        "other_column": [1.0, 2.0, 3.0, 4.0, 5.0]
    }, index=dates)
    
    signals = generator.generate(df)
    
    # Assert type, index alignment and all zeros output
    assert isinstance(signals, pd.Series)
    assert signals.index.equals(df.index), "Returned signals index must exactly match df index even when factor is missing!"
    
    expected = pd.Series([0, 0, 0, 0, 0], index=dates, dtype=int)
    pd.testing.assert_series_equal(signals.astype(int), expected, check_names=False)

def test_backtest_tab_ui_bound_locking():
    app = QApplication.instance() or QApplication(sys.argv)
    
    tab = BacktestTab()
    
    # 1. Initially, default strategy is "Mean Reversion", so bounds should be shown (not hidden)
    assert tab.strategy_combo.currentText() == "Mean Reversion"
    assert tab.upper_bound.isHidden() == False
    assert tab.lower_bound.isHidden() == False
    
    # 2. Switch to "Direct Signal", bounds should be hidden
    tab.strategy_combo.setCurrentText("Direct Signal")
    assert tab.upper_bound.isHidden() == True
    assert tab.lower_bound.isHidden() == True
    
    # 3. Switch to "Momentum Breakout", bounds should be shown again
    tab.strategy_combo.setCurrentText("Momentum Breakout")
    assert tab.upper_bound.isHidden() == False
    assert tab.lower_bound.isHidden() == False
    
    # Clean up widget
    tab.deleteLater()

def test_direct_signal_generator_dynamic_injection_basic():
    generator = SignalFactory.create("Direct Signal")
    
    dates = pd.date_range("2026-06-04", periods=5, freq="min")
    df = pd.DataFrame({
        "close": [10.0, 9.0, 11.0, 8.5, 12.0],
        "orb_low": [9.5, 9.5, 9.5, 9.5, 9.5],
        "zscore": [1.0, 2.0, 1.2, 1.8, 0.5]
    }, index=dates)
    
    # Custom signal logic code using zscore and close < orb_low
    code = "df['signal'] = np.where((df['close'] < df['orb_low']) & (df['zscore'] > 1.5), -1, 0)"
    
    signals = generator.generate(df, signal_logic_code=code)
    
    # Assert type and index alignment
    assert isinstance(signals, pd.Series)
    assert signals.index.equals(df.index), "Returned signals index must exactly match df index!"
    
    # Expected: 
    # Row 0: close=10.0 >= orb_low(9.5) -> 0
    # Row 1: close=9.0 < orb_low(9.5) & zscore=2.0 > 1.5 -> -1 (Short)
    # Row 2: close=11.0 >= orb_low(9.5) -> 0
    # Row 3: close=8.5 < orb_low(9.5) & zscore=1.8 > 1.5 -> -1 (Short)
    # Row 4: close=12.0 >= orb_low(9.5) -> 0
    expected = pd.Series([0, -1, 0, -1, 0], index=dates, dtype=int)
    pd.testing.assert_series_equal(signals.astype(int), expected, check_names=False)

def test_direct_signal_generator_dynamic_injection_exceptions():
    generator = SignalFactory.create("Direct Signal")
    df = pd.DataFrame({"close": [10.0, 9.0]}, index=pd.date_range("2026-06-04", periods=2))
    
    # Case 1: SyntaxError
    invalid_syntax_code = "df['signal'] = np.where((df['close'] < 10) &"
    with pytest.raises(ValueError) as excinfo:
        generator.generate(df, signal_logic_code=invalid_syntax_code)
    assert "动态信号代码执行失败" in str(excinfo.value)
    
    # Case 2: KeyError (Missing Column)
    missing_col_code = "df['signal'] = df['non_existent_column']"
    with pytest.raises(ValueError) as excinfo:
        generator.generate(df, signal_logic_code=missing_col_code)
    assert "动态信号代码执行失败" in str(excinfo.value)

def test_direct_signal_generator_dynamic_injection_pre_init_and_clip():
    generator = SignalFactory.create("Direct Signal")
    dates = pd.date_range("2026-06-04", periods=3)
    df = pd.DataFrame({"close": [10.0, 9.0, 11.0]}, index=dates)
    
    # Case 1: Pre-initialization fallback (no df['signal'] assignment in user code)
    # Do not call restricted builtins like print() since __builtins__ is restricted to {}
    no_assignment_code = "x = 42"
    signals_fallback = generator.generate(df, signal_logic_code=no_assignment_code)
    assert isinstance(signals_fallback, pd.Series)
    assert signals_fallback.index.equals(df.index)
    pd.testing.assert_series_equal(signals_fallback.astype(int), pd.Series([0, 0, 0], index=dates, dtype=int), check_names=False)
    
    # Case 2: Post-execution clipping safety (inputs outside [-1, 1])
    clipping_code = "df['signal'] = pd.Series([2.5, -3.0, 0.0], index=df.index)"
    signals_clipped = generator.generate(df, signal_logic_code=clipping_code)
    expected = pd.Series([1, -1, 0], index=dates, dtype=int)
    pd.testing.assert_series_equal(signals_clipped.astype(int), expected, check_names=False)

def test_backtest_tab_ui_dynamic_injection_visibility():
    app = QApplication.instance() or QApplication(sys.argv)
    
    tab = BacktestTab()
    
    # 1. Initially, default strategy is "Mean Reversion", so signal logic input should be hidden
    assert tab.strategy_combo.currentText() == "Mean Reversion"
    assert tab.signal_logic_input.isHidden() == True
    assert tab.signal_logic_label.isHidden() == True
    
    # 2. Switch to "Direct Signal", custom signal logic edit box should be shown (not hidden)
    tab.strategy_combo.setCurrentText("Direct Signal")
    assert tab.signal_logic_input.isHidden() == False
    assert tab.signal_logic_label.isHidden() == False
    
    # 3. Switch back to "Momentum Breakout", it should be hidden again
    tab.strategy_combo.setCurrentText("Momentum Breakout")
    assert tab.signal_logic_input.isHidden() == True
    assert tab.signal_logic_label.isHidden() == True
    
    # Clean up widget
    tab.deleteLater()

def test_backtest_tab_ui_empty_code_intercept():
    app = QApplication.instance() or QApplication(sys.argv)
    
    tab = BacktestTab()
    tab.strategy_combo.setCurrentText("Direct Signal")
    
    # Mock a selected file to pass the file selection check
    tab.file_combo.addItem("test_file.parquet", "test_path.parquet")
    tab.file_combo.setCurrentIndex(0)
    
    # Clear the input box code
    tab.signal_logic_input.setPlainText("")
    
    # Mock QMessageBox.warning to verify it gets called
    warning_called = False
    def mock_warning(*args, **kwargs):
        nonlocal warning_called
        warning_called = True
        return None
        
    original_warning = QMessageBox.warning
    QMessageBox.warning = mock_warning
    
    try:
        # Trigger run backtest
        tab._run_backtest()
        assert warning_called == True, "Should have intercepted the run and called QMessageBox.warning"
        
        # Reset warning flag
        warning_called = False
        # Trigger pressure test
        tab._run_pressure_test()
        assert warning_called == True, "Should have intercepted the pressure test and called QMessageBox.warning"
        
    finally:
        QMessageBox.warning = original_warning
        tab.deleteLater()
