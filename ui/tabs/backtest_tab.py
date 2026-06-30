
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QComboBox, QGroupBox, QFormLayout,
                             QDoubleSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
                             QHeaderView, QMessageBox, QSpinBox, QTabWidget, QCheckBox,
                             QFileDialog, QPlainTextEdit, QScrollArea)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
import os
import json
import uuid
from pathlib import Path
from datetime import datetime, timezone
import io
import base64
import hashlib
import html

# Set backend
matplotlib.use('QtAgg')
plt.style.use('dark_background')

from src.quant_bridge import BacktestEngine
from ui.widgets.backtest_charts import BacktestCharts
from logic.localization import tr


class BacktestWorker(QThread):
    """
    Worker thread to run the backtest engine without freezing UI.
    Supports 'run' (standard), 'audit', and 'sensitivity'.
    """
    finished = pyqtSignal(dict)
    sensitivity_finished = pyqtSignal(list)
    error = pyqtSignal(str)
    
    def __init__(self, data_path, params, task_type='run'):
        super().__init__()
        self.data_path = data_path
        self.params = params
        self.task_type = task_type # 'run', 'sensitivity'
        self.engine = BacktestEngine()
        
    def run(self):
        try:
            # Load Data
            df = pd.read_parquet(self.data_path)
            p  = self.params

            if self.task_type == 'run':
                # ── Build RiskConfig from UI params (no JSON needed) ──────────
                from logic.risk_manager_interceptor import (
                    RiskManager as RMInterceptor, RiskConfig)
                config = RiskConfig(
                    initial_capital    = p['initial_capital'],
                    initial_margin     = p['initial_margin'],
                    risk_target_pct    = p.get('risk_target', 1.0),
                    max_position_size  = p.get('max_lots', 20),
                    multiplier         = p['multiplier'],
                    adx_filter_enabled = p.get('use_adx_filter', False),
                    sl_pct             = p.get('sl_pct', 0.0)
                )
                RMClass = lambda *a, **kw: RMInterceptor(config)

                # ── Generate signals ──────────────────────────────────────────
                from src.core.signal_generator import SignalFactory
                df['signal'] = SignalFactory.create(
                    p.get('strategy', 'Mean Reversion')
                ).generate(df,
                    upper_bound=p['upper_bound'],
                    lower_bound=p['lower_bound'],
                    signal_logic_code=p.get('signal_logic_code'))

                # ── Run via event_driven.run() — same call-site as Risk Tab ───
                results = self.engine.event_driven.run(
                    df=df,
                    asset_symbol="BACKTEST",
                    RiskManagerClass=RMClass,
                    multiplier=p['multiplier'],
                    commission=p['commission'],
                    slippage=p['slippage'],
                    initial_capital=p['initial_capital'],
                    initial_margin=p['initial_margin'],
                    maintenance_margin_rate=0.8,
                    allow_lunch=p['allow_lunch'],
                    allow_overnight=p['allow_overnight'],
                    execution_mode=p.get('execution_mode', 'Close'),
                    risk_params={'max_lots': p.get('max_lots', 20), 'sl_pct': p.get('sl_pct', 0.0)}
                )

                # ── Lookahead audit (fast vectorized sub-run) ─────────────────
                audit_res = self.engine.audit_lookahead(df, p)
                results['audit'] = audit_res

                # ── Trade log forwarding ──────────────────────────────────────
                if 'trades' in results and not results['trades'].empty:
                    results['trade_log'] = results['trades']
                else:
                    trade_log = self.engine.generate_trade_log(results['equity_curve'])
                    results['trade_log'] = trade_log

                self.finished.emit(results)

                
            elif self.task_type == 'sensitivity':
                # Run Slippage Sensitivity
                sens_res = self.engine.run_pressure_test(df, self.params)
                self.sensitivity_finished.emit(sens_res)
            
        except Exception as e:
            import traceback
            self.error.emit(str(e) + "\n" + traceback.format_exc())

class BacktestTab(QWidget):
    """
    Tab for Vectorized Strategy Backtesting.
    Phase 5.1: Robustness (Next Open, Audit, Pressure Test).
    """
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.current_results = None
        # Snapshot of params used for the LAST completed backtest run.
        # This is set in _run_backtest() BEFORE the worker starts,
        # ensuring DNA always matches the actual Trade Log (anti state-mismatch).
        self._last_run_params: dict = {}
        self._last_signal_path: str = ""
        
    def init_ui(self):
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # === Left Panel: Settings ===
        left_panel = QWidget()
        left_panel.setFixedWidth(320) # Widened for new controls
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 10, 0)
        
        # Scroll Area for left settings
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 5, 0)
        
        # Title
        title = QLabel("Backtest Engine")
        font = title.font()
        font.setPointSize(14)
        font.setBold(True)
        title.setFont(font)
        scroll_layout.addWidget(title)
        
        # 1. Data Selection
        data_group = QGroupBox("Signal Source")
        data_layout = QFormLayout()
        
        self.file_combo = QComboBox()
        self.file_combo.setMaximumWidth(200)

        data_layout.addRow("File:", self.file_combo)
        
        refresh_btn = QPushButton(tr("alignment.buttons.refresh"))
        refresh_btn.setMinimumHeight(30)
        refresh_btn.setStyleSheet("background-color: #37474F; color: white; font-weight: bold; border-radius: 4px; border: 1px solid #555;")
        refresh_btn.clicked.connect(self.refresh_files)
        data_layout.addRow(refresh_btn)
        
        data_group.setLayout(data_layout)
        scroll_layout.addWidget(data_group)
        
        # 2. Market Parameters
        market_group = QGroupBox("Market Params")
        market_layout = QFormLayout()
        
        self.multiplier_spin = QDoubleSpinBox()
        self.multiplier_spin.setRange(1, 1000)
        self.multiplier_spin.setValue(25) # FCPO default
        market_layout.addRow("Multiplier:", self.multiplier_spin)
        
        self.commission_spin = QDoubleSpinBox()
        self.commission_spin.setRange(0, 500)
        self.commission_spin.setValue(15) # Example RM15 per side
        market_layout.addRow("Comm (RM/Lot):", self.commission_spin)
        
        self.slippage_spin = QDoubleSpinBox()
        self.slippage_spin.setRange(0, 50)
        self.slippage_spin.setValue(1) # 1 Tick slippage
        market_layout.addRow("Slippage (Pts):", self.slippage_spin)
        
        # Risk / Margin
        self.margin_spin = QDoubleSpinBox()
        self.margin_spin.setRange(0, 100000)
        self.margin_spin.setValue(5000) # Default Initial Margin
        self.margin_spin.setSingleStep(100)
        market_layout.addRow("Init Margin (RM):", self.margin_spin)
        
        market_group.setLayout(market_layout)
        scroll_layout.addWidget(market_group)
        
        # 3. Strategy Parameters
        strat_group = QGroupBox("Strategy Params")
        strat_layout = QFormLayout()
        
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(["Mean Reversion", "Momentum Breakout", "Direct Signal"])
        strat_layout.addRow("Strategy Type:", self.strategy_combo)
        
        # Signal Logic (Python) Container
        self.signal_logic_container = QWidget()
        sl_layout = QVBoxLayout(self.signal_logic_container)
        sl_layout.setContentsMargins(0, 5, 0, 5)
        
        self.signal_logic_label = QLabel("Signal Logic (Python):")
        self.signal_logic_input = QPlainTextEdit()
        self.signal_logic_input.setPlaceholderText("Enter Python signal logic, e.g.:\ndf['signal'] = np.where((df['close'] < df['orb_low']) & (df['zscore'] > 1.5), -1, 0)")
        self.signal_logic_input.setPlainText("df['signal'] = np.where((df['close'] < df['orb_low']) & (df['zscore'] > 1.5), -1, 0)")
        self.signal_logic_input.setMinimumHeight(150)
        
        sl_layout.addWidget(self.signal_logic_label)
        sl_layout.addWidget(self.signal_logic_input)
        strat_layout.addRow(self.signal_logic_container)
        
        self.capital_spin = QDoubleSpinBox()
        self.capital_spin.setRange(1000, 10000000)
        self.capital_spin.setValue(100000)
        self.capital_spin.setSingleStep(1000)
        strat_layout.addRow("Capital (RM):", self.capital_spin)
        
        # Bounds Container
        self.bounds_container = QWidget()
        bounds_layout = QFormLayout(self.bounds_container)
        bounds_layout.setContentsMargins(0, 0, 0, 0)
        
        self.upper_bound_label = QLabel("Upper Bound (>):")
        self.upper_bound = QDoubleSpinBox()
        self.upper_bound.setRange(-10, 10)
        self.upper_bound.setValue(0.5)
        self.upper_bound.setSingleStep(0.1)
        bounds_layout.addRow(self.upper_bound_label, self.upper_bound)
        
        self.lower_bound_label = QLabel("Lower Bound (<):")
        self.lower_bound = QDoubleSpinBox()
        self.lower_bound.setRange(-10, 10)
        self.lower_bound.setValue(-0.5)
        self.lower_bound.setSingleStep(0.1)
        bounds_layout.addRow(self.lower_bound_label, self.lower_bound)
        
        strat_layout.addRow(self.bounds_container)
        
        # Volatility Targeting (Phase 5.2)
        self.risk_target = QDoubleSpinBox()
        self.risk_target.setRange(0.0, 100.0)
        self.risk_target.setValue(1.0)
        self.risk_target.setSingleStep(0.1)
        self.risk_target.setToolTip("Target Risk % per trade (based on ATR). 0 = Fixed 1 Lot.")
        strat_layout.addRow("Risk Target (%):", self.risk_target)
        
        self.max_lots = QSpinBox()
        self.max_lots.setRange(1, 1000)
        self.max_lots.setValue(20)
        strat_layout.addRow("Max Lots:", self.max_lots)

        # Robustness Filters (Phase 5.2)
        self.adx_chk = QCheckBox("ADX Filter (>20)")
        self.adx_chk.setToolTip("Skip trades if ADX < 20 (Choppy Market)")
        strat_layout.addRow(self.adx_chk)

        self.sl_pct = QDoubleSpinBox()
        self.sl_pct.setRange(0.0, 10.0)
        self.sl_pct.setValue(0.0)
        self.sl_pct.setSingleStep(0.1)
        self.sl_pct.setToolTip("Intra-bar Stop Loss %. 0 = Off.")
        strat_layout.addRow("Intra-bar SL (%):", self.sl_pct)
        
        # Execution Mode (Phase 5.1)
        self.exec_mode_combo = QComboBox()
        self.exec_mode_combo.addItems(["Close (T)", "Next Open (T+1)"])
        self.exec_mode_combo.setToolTip("Close: Exec at Close T via Signal T\nNext Open: Exec at Open T+1 via Signal T (Robust)")
        strat_layout.addRow("Exec Mode:", self.exec_mode_combo)
        
        # Trading Hours
        self.intraday_chk = QCheckBox("Hold Overnight?")
        self.intraday_chk.setChecked(True)
        self.intraday_chk.setToolTip("If unchecked, positions are closed at 18:00 daily.")
        strat_layout.addRow(self.intraday_chk)
        
        self.lunch_chk = QCheckBox("Hold Lunch?")
        self.lunch_chk.setChecked(True)
        self.lunch_chk.setToolTip("If unchecked, positions are closed at 12:30.")
        strat_layout.addRow(self.lunch_chk)
        
        strat_group.setLayout(strat_layout)
        scroll_layout.addWidget(strat_group)
        
        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_widget)
        left_layout.addWidget(scroll_area)
        
        # Run Button
        self.run_btn = QPushButton("🚀 Run Backtest")
        self.run_btn.setMinimumHeight(40)
        self.run_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; font-size: 14px;")
        self.run_btn.clicked.connect(self._run_backtest)
        left_layout.addWidget(self.run_btn)
        
        # Pressure Test Button (Phase 5.1)
        self.pressure_btn = QPushButton("🔥 Pressure Test")
        self.pressure_btn.setMinimumHeight(30)
        self.pressure_btn.setStyleSheet("background-color: #FF9800; color: white; font-weight: bold;")
        self.pressure_btn.clicked.connect(self._run_pressure_test)
        left_layout.addWidget(self.pressure_btn)
        
        main_layout.addWidget(left_panel)
        
        # === Right Panel: Results ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # Header with Export
        header_layout = QHBoxLayout()
        self.audit_label = QLabel("") # For Audit Warning
        self.audit_label.setStyleSheet("color: orange; font-weight: bold;")
        header_layout.addWidget(self.audit_label)
        
        header_layout.addStretch()
        
        self.report_btn = QPushButton("📋 Generate Backtest Report")
        self.report_btn.setEnabled(False)
        self.report_btn.setStyleSheet(
            "background:#2E7D32; color:#B0BEC5; padding:4px 10px; border-radius:4px; font-weight:bold;")
        self.report_btn.clicked.connect(self._export_complete_report)
        header_layout.addWidget(self.report_btn)
        
        right_layout.addLayout(header_layout)
        
        # Metrics Splitter (Main Metrics vs Sensitivity)
        metrics_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Main Metrics Table
        self.metrics_table = QTableWidget()
        self.metrics_table.setColumnCount(4)
        self.metrics_table.setHorizontalHeaderLabels(["Metric", "Value", "Metric", "Value"])
        self.metrics_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.metrics_table.setRowCount(3) 
        self.metrics_table.verticalHeader().setVisible(False)
        metrics_splitter.addWidget(self.metrics_table)
        
        # Sensitivity Table (Initially Hidden or Small)
        self.sens_table = QTableWidget()
        self.sens_table.setColumnCount(4)
        self.sens_table.setHorizontalHeaderLabels(["Slippage", "Net Profit", "MDD (%)", "Trades"])
        self.sens_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.sens_table.verticalHeader().setVisible(False)
        self.sens_table.setAlternatingRowColors(True)
        metrics_splitter.addWidget(self.sens_table)
        
        # Set initial sizes
        metrics_splitter.setSizes([400, 200])
        
        right_layout.addWidget(metrics_splitter)
        right_layout.setStretchFactor(metrics_splitter, 1) # Small portion for metrics
        
        # Charts Widget (Phase 5B.1: Extracted to separate widget)
        self.charts = BacktestCharts()
        
        right_layout.addWidget(self.charts)
        right_layout.setStretchFactor(self.charts, 3) # Larger portion for charts
        
        main_layout.addWidget(right_panel)
        
        self.setLayout(main_layout)
        
        # Initial refresh
        self.refresh_files()
        
        # Connect strategy change handler for UI protection
        self.strategy_combo.currentTextChanged.connect(self._on_strategy_changed)
        self._on_strategy_changed(self.strategy_combo.currentText())
        
    def refresh_files(self):
        """Scan datacenter/Alpha_data/"""
        from utils.cache_manager import CacheManager
        
        alpha_path = CacheManager.get_alpha_storage_dir()
        
        files = []
        if alpha_path.exists():
            files.extend(list(alpha_path.rglob("*.parquet")))
            
        self.file_combo.clear()
        if files:
            seen = set()
            for f in files:
                abs_str = str(f.absolute())
                if abs_str in seen:
                    continue
                seen.add(abs_str)
                rel_path = str(f.relative_to(alpha_path))
                self.file_combo.addItem(rel_path, str(f))
        else:
            self.file_combo.addItem("No signals found")
            self.run_btn.setEnabled(False)
            self.pressure_btn.setEnabled(False)
            
        if self.file_combo.count() > 0 and self.file_combo.currentText() != "No signals found":
             self.run_btn.setEnabled(True)
             self.pressure_btn.setEnabled(True)

    def _on_strategy_changed(self, text: str):
        """Hide upper/lower bounds if Direct Signal strategy is selected, and manage signal logic visibility."""
        is_direct = (text == "Direct Signal")
        
        # Hide/show bounds container and widgets
        self.bounds_container.setVisible(not is_direct)
        self.upper_bound_label.setVisible(not is_direct)
        self.upper_bound.setVisible(not is_direct)
        self.lower_bound_label.setVisible(not is_direct)
        self.lower_bound.setVisible(not is_direct)
        
        # Manage visibility of custom signal logic container and widgets
        self.signal_logic_container.setVisible(is_direct)
        self.signal_logic_label.setVisible(is_direct)
        self.signal_logic_input.setVisible(is_direct)

    def _get_params(self):
        return {
            'multiplier': self.multiplier_spin.value(),
            'commission': self.commission_spin.value(),
            'slippage': self.slippage_spin.value(),
            'strategy': self.strategy_combo.currentText(),
            'initial_capital': self.capital_spin.value(),
            'upper_bound': self.upper_bound.value(),
            'lower_bound': self.lower_bound.value(),
            'initial_margin': self.margin_spin.value(),
            'allow_overnight': self.intraday_chk.isChecked(),
            'allow_lunch': self.lunch_chk.isChecked(),
            'execution_mode': self.exec_mode_combo.currentText(),
            'risk_target': self.risk_target.value(),
            'sl_pct': self.sl_pct.value(),
            'use_adx_filter': self.adx_chk.isChecked(),
            'max_lots': self.max_lots.value(),
            'signal_logic_code': self.signal_logic_input.toPlainText()
        }

    def _run_backtest(self):
        filename = self.file_combo.currentText()
        if not filename or filename == "No signals found": return
        
        # Intercept empty code in Direct Signal mode
        if self.strategy_combo.currentText() == "Direct Signal" and not self.signal_logic_input.toPlainText().strip():
            QMessageBox.warning(self, "参数校验失败", "在 Direct Signal 模式下，必须输入 Signal Logic (Python) 代码。")
            return
        
        # Pull absolute path from the combo item's hidden data
        path = self.file_combo.currentData()
        if not path:
            # Fallback just in case
            path = str(Path("datacenter/Alpha_data") / filename)
            
        import os
        from src.core.models.strategy_config import StrategyConfig
        
        # 1. 自动读取与装载 (Load)
        import re
        stem = Path(path).stem
        match = re.search(r'^(.*)_data(?:_.*_v\d{8})?$', stem)
        if match:
            safe_stg_id = match.group(1)
            json_path = str(Path(path).parent / f"{safe_stg_id}_config.json")
        else:
            json_path = path.replace('_data.parquet', '_config.json')
            if json_path == path or not os.path.exists(json_path):
                json_path = path.replace('.parquet', '.json')
            
        configurator = None
        if os.path.exists(json_path):
            try:
                configurator = StrategyConfig.from_json(json_path)
                
                # Check Lock State
                if configurator.metadata.status == "PRODUCTION_READY":
                    reply = QMessageBox.question(
                        self, 
                        "状态锁警告 (Status Lock)", 
                        "该策略当前状态为 PRODUCTION_READY，通常禁止修改。\n\n您确定要强行重新回测并覆盖现有的质检结果吗？", 
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply != QMessageBox.StandardButton.Yes:
                        return
                        
            except Exception as e:
                QMessageBox.critical(self, "Parse Error", f"Cannot parse strategy DNA: {e}")
                return

        params = self._get_params()

        # === SNAPSHOT: capture run-time state BEFORE worker starts ===
        # DNA will read from these frozen snapshots, NOT from live UI controls.
        self._last_run_params = dict(params)
        self._last_signal_path = path
        self._last_json_path = json_path

        self.run_btn.setEnabled(False)
        self.run_btn.setText("⏳ Running...")
        self.audit_label.setText("")
        self.report_btn.setEnabled(False)
        self.report_btn.setStyleSheet(
            "background:#2E7D32; color:#B0BEC5; padding:4px 10px; border-radius:4px; font-weight:bold;")

        self.worker = BacktestWorker(path, params, task_type='run')
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()
        
    def _run_pressure_test(self):
        filename = self.file_combo.currentText()
        if not filename or filename == "No signals found": return
        
        # Intercept empty code in Direct Signal mode
        if self.strategy_combo.currentText() == "Direct Signal" and not self.signal_logic_input.toPlainText().strip():
            QMessageBox.warning(self, "参数校验失败", "在 Direct Signal 模式下，必须输入 Signal Logic (Python) 代码进行敏感度压力测试。")
            return
        
        path = self.file_combo.currentData()
        if not path:
            path = str(Path("datacenter/Alpha_data") / filename)
        
        params = self._get_params()
        
        self.pressure_btn.setEnabled(False)
        self.pressure_btn.setText("⏳ Testing...")
        
        self.worker = BacktestWorker(path, params, task_type='sensitivity')
        self.worker.sensitivity_finished.connect(self._on_sensitivity_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_finished(self, results):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("🚀 Run Backtest")
        
        # Robust Cleanup: Wait for the thread to fully exit its C++ loop before destroying
        if hasattr(self, 'worker') and self.worker:
            self.worker.wait()
            self.worker.deleteLater()
            self.worker = None
            
        self.audit_label.setText("✅ Backtest Finished")
        self.current_results = results
        self.report_btn.setEnabled(True)
        self.report_btn.setStyleSheet(
            "background:#2E7D32; color:white; padding:4px 10px; border-radius:4px; font-weight:bold;")
        
        self._update_metrics(results['metrics'])
        self._update_charts(results)
        
        # Check Audit Result
        audit = results.get('audit', {})
        if audit.get('warning', False):
            self.audit_label.setText("⚠️ POTENTIAL LOOK-AHEAD BIAS DETECTED")
            QMessageBox.warning(self, "Audit Warning", 
                                f"Future Function Detected!\n\n"
                                f"Original Profit: {audit['base_profit']:.2f}\n"
                                f"Audited (Shift+1): {audit['audit_profit']:.2f}\n"
                                f"Deviation: {audit['diff_pct']*100:.1f}%\n\n"
                                "Please check your Alpha Factor logic.")
        else:
            self.audit_label.setText("✅ Audit Passed")
            
        # Check Margin Status
        status = results['metrics'].get('Margin Status', 'Safe')
        if "MARGIN CALL" in status:
            QMessageBox.warning(self, "Risk Warning", f"Strategy triggered a {status}")
        else:
            QMessageBox.information(self, "Backtest Complete", "Backtest finished successfully!")
            
        # ========================================================
        # Phase 2: Baton Relay State Transition (Auto-Export to Backtest_data)
        # ========================================================
        import os
        import shutil
        from src.core.models.strategy_config import StrategyConfig
        from utils.cache_manager import CacheManager
        
        json_path = getattr(self, '_last_json_path', None)
        signal_path = getattr(self, '_last_signal_path', None)
        
        if json_path and signal_path:
            try:
                stg_name = Path(signal_path).parent.name
                
                # 1. Deserialize from Alpha_data (Read-only) or Initialize
                if os.path.exists(json_path):
                    config = StrategyConfig.from_json(json_path)
                else:
                    from src.core.models.strategy_config import StrategyMetadata, EnvironmentConfig, AlphaPipelineConfig, AlphaProfile, BacktestProfile
                    config = StrategyConfig(
                        metadata=StrategyMetadata(
                            strategy_id=stg_name,
                            strategy_name=stg_name,
                            status="BACKTESTED"
                        ),
                        environment_config=EnvironmentConfig(universe="unknown", timeframe="unknown"),
                        alpha_pipeline=AlphaPipelineConfig(expression=""),
                        alpha_profile=AlphaProfile(metrics={}, professional_metrics={}),
                        backtest_profile=BacktestProfile(settings={}, metrics={})
                    )
                
                # 2. Update Profile & Embed Metrics
                config.backtest_profile.settings = self._last_run_params
                
                # Safe-copy primitives out of the metrics dict to avoid serialization issues
                clean_metrics = {}
                for k, v in results.get('metrics', {}).items():
                    if isinstance(v, (int, float, str, bool)):
                        clean_metrics[k] = v
                    elif hasattr(v, 'item'):  # Handle numpy types cleanly
                        clean_metrics[k] = v.item()
                    else:
                        clean_metrics[k] = str(v)
                config.backtest_profile.metrics = clean_metrics
                
                # 3. State Transition: Enforce status upgrade
                config.metadata.status = "BACKTESTED"
                
                # 4. Determine Target Directory under Backtest_data
                target_dir = CacheManager.get_backtest_storage_dir() / stg_name
                target_dir.mkdir(parents=True, exist_ok=True)
                
                stg_id = config.metadata.strategy_id
                
                # Suffix generation is disabled to overwrite previous runs and simplify file names
                suffix = ""
                
                # 5. Save modern config `{stg_id}_config_{suffix}.json` inside Backtest_data
                config.to_json(str(target_dir / f"{stg_id}_config{suffix}.json"))
                
                # 6. Save Legacy DNA backup `{stg_id}_{suffix}.json` inside Backtest_data
                try:
                    dna = self.generate_strategy_dna()
                    # Ensure stg_id in DNA identification matches config
                    dna["identification"]["strategy_id"] = stg_id
                    with open(target_dir / f"{stg_id}{suffix}.json", "w", encoding="utf-8") as f:
                        json.dump(dna, f, indent=2, ensure_ascii=False)
                except Exception as dna_ex:
                    print(f"[WARNING] Failed to generate legacy DNA: {dna_ex}")
                
                # 7. Dump Trade Log CSV `{stg_id}_tradelog_{suffix}.csv` into Backtest_data
                trades_df = results.get('trades')
                if trades_df is not None and not trades_df.empty:
                    trades_df.to_csv(target_dir / f"{stg_id}_tradelog{suffix}.csv", index=False)
                elif 'trade_log' in results and results['trade_log'] is not None and not results['trade_log'].empty:
                    results['trade_log'].to_csv(target_dir / f"{stg_id}_tradelog{suffix}.csv", index=False)
                
                # 8. Dump Equity Curve CSV `{stg_id}_{suffix}.csv` into Backtest_data
                if 'equity_curve' in results and results['equity_curve'] is not None:
                    eq_df = results['equity_curve']
                    if isinstance(eq_df, list):
                        eq_df = pd.DataFrame(eq_df)
                    if hasattr(eq_df, 'to_csv'):
                        eq_df.to_csv(target_dir / f"{stg_id}{suffix}.csv", index=False)
                elif trades_df is not None and not trades_df.empty:
                    trades_df.to_csv(target_dir / f"{stg_id}{suffix}.csv", index=False)
                
                # 9. Copy the source signal Parquet file from Alpha_data to Backtest_data as `{stg_id}_data_{suffix}.parquet`
                if os.path.exists(signal_path):
                    shutil.copy2(signal_path, target_dir / f"{stg_id}_data{suffix}.parquet")
                    print(f"[INFO] Copied signal parquet to backtest folder: {target_dir / f'{stg_id}_data{suffix}.parquet'}")
                
                # Update UI Alert Banner to confirm Relay
                self.audit_label.setText(self.audit_label.text() + " | 🔋 Auto-Relay: SAVED TO BACKTEST_DATA")
                
            except Exception as e:
                print(f"[ERROR] Baton Relay Phase 2 save failed: {e}")
                import traceback
                traceback.print_exc()
                QMessageBox.warning(self, "Relay Update Error", f"Failed to save backtest signature mapping to DNA:\n{e}")
        
    def _on_sensitivity_finished(self, results):
        self.pressure_btn.setEnabled(True)
        self.pressure_btn.setText("🔥 Pressure Test")
        
        self.sens_table.setRowCount(len(results))
        for i, res in enumerate(results):
            self.sens_table.setItem(i, 0, QTableWidgetItem(str(res['Slippage'])))
            self.sens_table.setItem(i, 1, QTableWidgetItem(f"{res['Net Profit']:,.0f}"))
            self.sens_table.setItem(i, 2, QTableWidgetItem(f"{res.get('MDD (%)', 0.0):.2f}"))
            self.sens_table.setItem(i, 3, QTableWidgetItem(str(res['Trades'])))
            
        QMessageBox.information(self, "Pressure Test", "Slippage Sensitivity Test Complete!")

    def _on_error(self, msg):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("🚀 Run Backtest")
        self.pressure_btn.setEnabled(True)
        self.pressure_btn.setText("🔥 Pressure Test")
        self.report_btn.setEnabled(False)
        self.report_btn.setStyleSheet(
            "background:#2E7D32; color:#B0BEC5; padding:4px 10px; border-radius:4px; font-weight:bold;")
        
        if "must contain 'close'" in msg:
            QMessageBox.critical(self, "Data Error", 
                "The selected signal file is missing price data ('close' column).\n\n"
                "Possible Fixes:\n"
                "1. Regenerate the signal in 'Alpha Research' tab (Code updated to fix this).\n"
                "2. Ensure your original data has a 'close', 'last', or 'price' column."
            )
        else:
            QMessageBox.critical(self, "Error", msg)
            
    def _read_signal_metadata(self, parquet_path: str) -> dict:
        """
        Read universe (symbol) and timeframe from the Parquet file's key-value metadata.
        Falls back to filename stem parsing if metadata is absent or unreadable.
        """
        try:
            import pyarrow.parquet as pq
            raw_meta = pq.read_schema(parquet_path).metadata or {}
            universe = raw_meta.get(b"symbol", b"").decode().strip()
            timeframe = raw_meta.get(b"timeframe", b"").decode().strip()
            if universe and timeframe:
                return {"universe": universe, "timeframe": timeframe}
        except Exception:
            pass

        # Fallback: parse filename stem (e.g. "FCPO1!_5m" → symbol="FCPO1!", tf="5m")
        stem = Path(parquet_path).stem
        parts = stem.rsplit("_", 1)
        return {
            "universe": parts[0] if len(parts) == 2 else stem,
            "timeframe": parts[1] if len(parts) == 2 else "unknown",
        }

    def generate_strategy_dna(self) -> dict:
        """
        Build the strategy_dna dict from the FROZEN snapshot captured at
        backtest run-time (_last_run_params). Never reads from live UI controls.
        """
        p = self._last_run_params
        if not p:
            raise RuntimeError("No backtest has been run yet. Cannot generate Strategy DNA.")

        signal_meta = self._read_signal_metadata(self._last_signal_path)
        sl_pct = p.get('sl_pct', 0.0)
        stop_loss_type = "Intra-bar SL" if sl_pct > 0 else "None"

        return {
            "identification": {
                "strategy_id": str(uuid.uuid4())[:8].upper(),
                "backtest_version": "v1.0",
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            "environment": {
                "universe": [signal_meta["universe"]],
                "timeframe": signal_meta["timeframe"],
                "initial_capital": p.get('initial_capital', 0.0),
                "currency": "RM"
            },
            "alpha_configuration": {
                "factor_expression": p.get('strategy', 'unknown'),
                "preprocessing_params": {
                    "winsorize_limit": 0.05,
                    "neutralization": False,
                    "standardization": "z-score"
                }
            },
            "optimized_decision_parameters": {
                "entry_threshold": p.get('upper_bound', 0.0),
                "exit_threshold": p.get('lower_bound', 0.0),
                "rebalance_mode": "signal_driven",
                "order_type": "market",
                "execution_mode": p.get('execution_mode', 'Close'),
                "signal_logic_code": p.get('signal_logic_code', "")
            },
            "execution_constraints": {
                "allow_overnight": p.get('allow_overnight', True),
                "allow_lunch": p.get('allow_lunch', True),
                "adx_filter_enabled": p.get('use_adx_filter', False)
            },
            "friction_costs": {
                "multiplier": p.get('multiplier', 0.0),
                "commission_per_lot": p.get('commission', 0.0),
                "slippage_ticks": p.get('slippage', 0.0)
            },
            "backtest_risk_settings": {
                "stop_loss_type": stop_loss_type,
                "stop_loss_value": sl_pct,
                "take_profit_value": 0.0,
                "max_position_size": p.get('max_lots', 20),
                "leverage_limit": 1.0,
                "initial_margin": p.get('initial_margin', 0.0),
                "risk_target_pct": p.get('risk_target', 0.0)
            }
        }

    def _export_trade_log(self):
        if not self.current_results or 'trade_log' not in self.current_results:
            return

        df = self.current_results['trade_log']
        if df.empty:
            QMessageBox.information(self, "Export", "No trades were generated.")
            return

        from ui.export_backtest_dialog import ExportBacktestDialog
        from utils.cache_manager import CacheManager
        import shutil

        dialog = ExportBacktestDialog(self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
            
        export_data = dialog.get_export_data()
        folder_name = export_data['folder_name']
        trade_log_base = export_data['trade_log_base']
        dna_base = export_data['dna_base']
        save_mode = export_data['save_mode']

        try:
            # 1. Determine local_dir if needed
            local_dir_path = None
            if save_mode in ['local', 'both']:
                local_dir_path = QFileDialog.getExistingDirectory(
                    self, "Select Local Export Directory", "", QFileDialog.Option.ShowDirsOnly
                )
                if not local_dir_path:
                    # User canceled directory selection
                    return
            
            # 2. Prepare DNA
            dna = self.generate_strategy_dna()
            
            # Load unified config if it exists for dual-backups (E2E full pipeline integration)
            unified_config_data = None
            if hasattr(self, '_last_json_path') and self._last_json_path and os.path.exists(self._last_json_path):
                try:
                    with open(self._last_json_path, 'r', encoding='utf-8') as f:
                        unified_config_data = json.load(f)
                except Exception as ex:
                    print(f"[WARNING] Could not read unified config from {self._last_json_path}: {ex}")
            
            # 3. Create folders and write files
            paths_created = []
            
            is_workspace = False
            # 2. Prepare DNA
            dna = self.generate_strategy_dna()
            
            # Load unified config if it exists for dual-backups (E2E full pipeline integration)
            unified_config_data = None
            if hasattr(self, '_last_json_path') and self._last_json_path and os.path.exists(self._last_json_path):
                try:
                    with open(self._last_json_path, 'r', encoding='utf-8') as f:
                        unified_config_data = json.load(f)
                except Exception as ex:
                    print(f"[WARNING] Could not read unified config from {self._last_json_path}: {ex}")
            
            # Suffix generation using parameter MD5 hash and high-precision timestamp
            import hashlib
            from datetime import datetime
            param_str = "_".join(f"{k}={v}" for k, v in sorted(self._last_run_params.items()) if isinstance(v, (int, float, str)))
            param_hash = hashlib.md5(param_str.encode('utf-8')).hexdigest()[:8]
            timestamp_suffix = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            suffix = f"_{param_hash}_{timestamp_suffix}"
            
            # 3. Create folders and write files
            paths_created = []
            trade_log_filename = f"{trade_log_base}{suffix}.csv"
            dna_filename = f"{dna_base}{suffix}.json"
            unified_filename = f"{dna_base}_config{suffix}.json"
            dc_path = CacheManager.get_backtest_storage_dir() / folder_name
            
            if save_mode in ['data_center', 'both']:
                dc_path.mkdir(parents=True, exist_ok=True)
                df.to_csv(str(dc_path / trade_log_filename), index=False)
                with open(dc_path / dna_filename, "w", encoding="utf-8") as f:
                    json.dump(dna, f, indent=2, ensure_ascii=False)
                if unified_config_data:
                    with open(dc_path / unified_filename, "w", encoding="utf-8") as f:
                        json.dump(unified_config_data, f, indent=4, ensure_ascii=False)
                paths_created.append(f"Data Center:\n{dc_path}")
                
            if save_mode in ['local', 'both']:
                local_path = Path(local_dir_path) / folder_name
                local_path.mkdir(parents=True, exist_ok=True)
                
                if save_mode == 'both':
                    shutil.copy2(str(dc_path / trade_log_filename), str(local_path / trade_log_filename))
                    shutil.copy2(str(dc_path / dna_filename), str(local_path / dna_filename))
                    if unified_config_data and (dc_path / unified_filename).exists():
                        shutil.copy2(str(dc_path / unified_filename), str(local_path / unified_filename))
                else:
                    df.to_csv(str(local_path / trade_log_filename), index=False)
                    with open(local_path / dna_filename, "w", encoding="utf-8") as f:
                        json.dump(dna, f, indent=2, ensure_ascii=False)
                    if unified_config_data:
                        with open(local_path / unified_filename, "w", encoding="utf-8") as f:
                            json.dump(unified_config_data, f, indent=4, ensure_ascii=False)
                paths_created.append(f"Local Export:\n{local_path}")
            
            msg = "Successfully exported Backtest Info to:\n\n" + "\n\n".join(paths_created)
            QMessageBox.information(self, "Export Successful", msg)
            
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))
        
    def _update_metrics(self, metrics):
        # Flatten metrics into grid
        items = list(metrics.items())
        rows = (len(items) + 1) // 2
        self.metrics_table.setRowCount(rows)
        
        for i in range(rows):
            # Col 1 & 2
            k1, v1 = items[i*2]
            self.metrics_table.setItem(i, 0, QTableWidgetItem(k1))
            val1 = f"{v1:,.2f}" if isinstance(v1, (int, float)) else str(v1)
            self.metrics_table.setItem(i, 1, QTableWidgetItem(val1))
            
            # Col 3 & 4
            if i*2 + 1 < len(items):
                k2, v2 = items[i*2 + 1]
                self.metrics_table.setItem(i, 2, QTableWidgetItem(k2))
                val2 = f"{v2:,.2f}" if isinstance(v2, (int, float)) else str(v2)
                self.metrics_table.setItem(i, 3, QTableWidgetItem(val2))
            else:
                self.metrics_table.setItem(i, 2, QTableWidgetItem(""))
                self.metrics_table.setItem(i, 3, QTableWidgetItem(""))

    def _update_charts(self, results):
        """Update all charts using BacktestCharts widget."""
        self.charts.update_all_charts(results)

    def _export_complete_report(self):
        if not self.current_results:
            QMessageBox.warning(self, "No Data", "Please run the backtest first.")
            return

        from PyQt6.QtWidgets import QFileDialog, QApplication
        from PyQt6.QtGui import QCursor
        from datetime import datetime
        import html
        import re
        import hashlib
        import io
        import base64

        p = self._last_run_params
        if not p:
            QMessageBox.warning(self, "No Data", "No backtest parameters found.")
            return

        # 1. Gather inputs and metadata
        universe = Path(self._last_signal_path).stem
        if universe.endswith("_data"):
            universe = universe[:-5]
        strategy_type = p.get('strategy', 'unknown')
        
        # 2. Generate MD5 Fingerprint
        param_str = "_".join(f"{k}={v}" for k, v in sorted(p.items()) if isinstance(v, (int, float, str, bool)))
        param_str += f"&logic={p.get('signal_logic_code', '')}"
        md5_hash = hashlib.md5(param_str.encode('utf-8')).hexdigest()[:8].upper()
        
        # 3. Resolve default filename
        clean_universe = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in universe).strip("_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"BacktestReport_{clean_universe}_{strategy_type.replace(' ', '_')}_{md5_hash}_{timestamp}.html"
        
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Backtest Report",
            default_filename,
            "HTML Files (*.html)"
        )
        if not save_path:
            return

        # Disable cursor during export rendering
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        
        try:
            # 4. Convert plots to Base64
            def get_base64_img(fig):
                buf = io.BytesIO()
                fig.savefig(buf, format='png', bbox_inches='tight', dpi=100, facecolor=fig.get_facecolor())
                buf.seek(0)
                img_data = base64.b64encode(buf.read()).decode('utf-8')
                buf.close()
                return img_data

            equity_img = get_base64_img(self.charts.equity_fig)
            dist_img = get_base64_img(self.charts.dist_fig)
            dd_img = get_base64_img(self.charts.dd_fig)
            risk_img = get_base64_img(self.charts.risk_fig)

            # 5. Extract main performance metrics
            metrics = self.current_results.get('metrics', {})
            kpi_table_html = ""
            for k, v in metrics.items():
                if k == "Margin Status":
                    continue
                val_str = f"{v:,.2f}" if isinstance(v, (int, float)) else str(v)
                kpi_table_html += f"<tr><td><b>{k}</b></td><td>{val_str}</td></tr>"

            # 6. Check look-ahead audit warning
            audit = self.current_results.get('audit', {})
            audit_warning = audit.get('warning', False)
            audit_diff_pct = audit.get('diff_pct', 0.0)
            audit_base_profit = audit.get('base_profit', 0.0)
            audit_audit_profit = audit.get('audit_profit', 0.0)

            if audit_warning:
                audit_html = f"""
                <div class="alert danger">
                    <h3>🚨 Look-Ahead Bias Detected! (前瞻未来函数警告)</h3>
                    <p>
                        <b>Original Profit (Close execution):</b> RM {audit_base_profit:,.2f}<br>
                        <b>Audited Profit (Next Open execution):</b> RM {audit_audit_profit:,.2f}<br>
                        <b>Profit Deviation:</b> <span class="highlight-danger">{audit_diff_pct*100:.2f}%</span>
                    </p>
                    <p style="font-size: 12px; margin-top: 5px; color: var(--text-muted);">
                        Warning: Significant profit degradation when executing on Next Open (T+1) compared to Close (T). This indicates that the signal depends on information not available at the execution time. Check for look-ahead bias!
                    </p>
                </div>
                """
            else:
                audit_html = f"""
                <div class="alert pass">
                    <h3>✅ Look-Ahead Bias Audit Passed (前瞻安全审计通过)</h3>
                    <p>
                        <b>Original Profit (Close execution):</b> RM {audit_base_profit:,.2f}<br>
                        <b>Audited Profit (Next Open execution):</b> RM {audit_audit_profit:,.2f}<br>
                        <b>Profit Deviation:</b> {audit_diff_pct*100:.2f}% (Within safe tolerance bounds)
                    </p>
                </div>
                """

            # 7. Check margin status
            margin_status = metrics.get('Margin Status', 'Safe')
            if "MARGIN CALL" in margin_status or margin_status != "Safe":
                margin_html = f"""
                <div class="alert danger" style="margin-bottom: 20px;">
                    <h3>🚨 MARGIN CALL TRIGGERED! (追缴保证金/爆仓强平警告)</h3>
                    <p>账户爆仓强平拦截状态: <b>{margin_status}</b></p>
                </div>
                """
            else:
                margin_html = f"""
                <div class="alert pass" style="margin-bottom: 20px;">
                    <h3>🛡️ Margin Account Status: SAFE (保证金账户安全)</h3>
                    <p>无追缴维持保证金（Margin Call）或日内强平事件发生。</p>
                </div>
                """

            # 8. Check sensitivity pressure test table
            sens_rows = []
            if self.sens_table.rowCount() > 0:
                for r in range(self.sens_table.rowCount()):
                    slip_pts = self.sens_table.item(r, 0).text() if self.sens_table.item(r, 0) else ""
                    net_prof = self.sens_table.item(r, 1).text() if self.sens_table.item(r, 1) else ""
                    mdd_val = self.sens_table.item(r, 2).text() if self.sens_table.item(r, 2) else ""
                    trades_val = self.sens_table.item(r, 3).text() if self.sens_table.item(r, 3) else ""
                    sens_rows.append({
                        "slippage": slip_pts,
                        "profit": net_prof,
                        "mdd": mdd_val,
                        "trades": trades_val
                    })

            if sens_rows:
                sens_table_rows = ""
                for sr in sens_rows:
                    sens_table_rows += f"""
                    <tr>
                        <td>{sr['slippage']} Ticks</td>
                        <td><b>RM {sr['profit']}</b></td>
                        <td>{sr['mdd']}</td>
                        <td>{sr['trades']}</td>
                    </tr>
                    """
                sens_html = f"""
                <div class="card" style="margin-top: 20px;">
                    <h2>🔥 滑点敏感性压力测试 (Slippage Sensitivity Test)</h2>
                    <table>
                        <thead>
                            <tr>
                                <th>滑点摩擦 (Slippage)</th>
                                <th>回测净利润 (Net Profit)</th>
                                <th>最大盯市回撤 (Max Drawdown)</th>
                                <th>交易笔数 (Trades)</th>
                            </tr>
                        </thead>
                        <tbody>
                            {sens_table_rows}
                        </tbody>
                    </table>
                </div>
                """
            else:
                sens_html = """
                <div class="card" style="margin-top: 20px; text-align: center; color: var(--text-muted);">
                    <h2>🔥 滑点敏感性压力测试 (Slippage Sensitivity Test)</h2>
                    <p style="padding: 20px 0;">未运行滑点压力测试。可以在界面左下方点击 “🔥 Pressure Test” 按钮来进行多维度摩擦成本测试。</p>
                </div>
                """

            # 9. Strategy parameters table
            bounds_html = ""
            if strategy_type != "Direct Signal":
                bounds_html = f"""
                <tr><td>入场上轨 (Upper Bound >)</td><td>{p.get('upper_bound', 0.0)}</td></tr>
                <tr><td>入场下轨 (Lower Bound <)</td><td>{p.get('lower_bound', 0.0)}</td></tr>
                """

            code_html = ""
            if strategy_type == "Direct Signal" and p.get('signal_logic_code'):
                safe_code = html.escape(p.get('signal_logic_code', ''))
                code_html = f"""
                <div class="card" style="margin-top: 20px;">
                    <h2>💻 自定义信号生成逻辑 (Signal Logic Code)</h2>
                    <div class="code-block">{safe_code}</div>
                </div>
                """

            # 10. Construct HTML Report Content
            html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Strategy Backtest Report - {clean_universe}</title>
    <style>
        :root {{
            --bg-color: #0d1117;
            --card-bg: #161b22;
            --border-color: #30363d;
            --text-color: #c9d1d9;
            --text-muted: #8b949e;
            --primary: #4CAF50;
            --primary-muted: rgba(76, 175, 80, 0.15);
            --accent: #2196F3;
            --accent-muted: rgba(33, 150, 243, 0.15);
            --warning: #ff9800;
            --warning-muted: rgba(255, 152, 0, 0.15);
            --danger: #f44336;
            --danger-muted: rgba(244, 67, 54, 0.15);
        }}
        body {{
            background-color: var(--bg-color);
            color: var(--text-color);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 40px 20px;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        header {{
            border-bottom: 2px solid var(--border-color);
            padding-bottom: 20px;
            margin-bottom: 30px;
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
        }}
        .header-title h1 {{
            margin: 0;
            font-size: 28px;
            color: #ffffff;
            font-weight: 700;
            letter-spacing: -0.5px;
        }}
        .header-title p {{
            margin: 5px 0 0 0;
            color: var(--text-muted);
            font-size: 14px;
        }}
        .fingerprint {{
            font-family: monospace;
            background-color: #1f242c;
            padding: 4px 8px;
            border-radius: 4px;
            border: 1px solid var(--border-color);
            color: var(--accent);
        }}
        .grid-2 {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 30px;
        }}
        .card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 20px;
            position: relative;
        }}
        .card h2 {{
            margin: 0 0 15px 0;
            font-size: 18px;
            font-weight: 600;
            color: #ffffff;
        }}
        .code-block {{
            background-color: #090c10;
            border: 1px solid var(--border-color);
            padding: 15px;
            border-radius: 6px;
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, Courier, monospace;
            font-size: 13px;
            color: #ff7b72;
            word-break: break-all;
            white-space: pre-wrap;
            margin: 10px 0;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
            font-size: 13px;
        }}
        th, td {{
            text-align: left;
            padding: 10px 12px;
            border-bottom: 1px solid var(--border-color);
        }}
        th {{
            background-color: #1f242c;
            color: #ffffff;
            font-weight: 600;
        }}
        tr:nth-child(even) {{
            background-color: #161b2255;
        }}
        .alert {{
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 15px;
        }}
        .alert.pass {{ background-color: var(--primary-muted); color: var(--primary); border: 1px solid var(--primary); }}
        .alert.danger {{ background-color: var(--danger-muted); color: var(--danger); border: 1px solid var(--danger); }}
        .alert h3 {{ margin: 0 0 8px 0; font-size: 15px; }}
        .alert p {{ margin: 0; font-size: 13px; }}
        .highlight-danger {{ color: var(--danger); font-weight: bold; }}

        .chart-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-top: 30px;
        }}
        .chart-card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 15px;
            text-align: center;
        }}
        .chart-card h3 {{
            margin: 0 0 10px 0;
            font-size: 15px;
            color: #ffffff;
            text-align: left;
        }}
        .chart-card img {{
            max-width: 100%;
            height: auto;
            border-radius: 4px;
            background-color: #000;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="header-title">
                <h1>🚀 Strategy Backtest Performance Report</h1>
                <p>策略源: {universe} | 回测时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            </div>
            <div>
                实验指纹: <span class="fingerprint">{md5_hash}</span>
            </div>
        </header>

        {margin_html}
        {audit_html}

        <div class="grid-2">
            <!-- Parameters Card -->
            <div class="card">
                <h2>⚙ 1. 交易规则与摩擦参数 (Params & Friction)</h2>
                <table>
                    <thead>
                        <tr><th>回测配置参数</th><th>设定数值</th></tr>
                    </thead>
                    <tbody>
                        <tr><td>初始资金 (Initial Capital)</td><td>RM {p.get('initial_capital', 0.0):,.2f}</td></tr>
                        <tr><td>策略类型 (Strategy Type)</td><td><b>{strategy_type}</b></td></tr>
                        {bounds_html}
                        <tr><td>波动率仓位管理 (Risk Target %)</td><td>{p.get('risk_target', 0.0)}% (0 = 固定 1 手)</td></tr>
                        <tr><td>允许持仓手数上限 (Max Lots)</td><td>{p.get('max_lots', 20)}</td></tr>
                        <tr><td>ADX 趋势过滤器</td><td>{p.get('use_adx_filter', False)}</td></tr>
                        <tr><td>条内止损阈值 (Intra-bar SL)</td><td>{p.get('sl_pct', 0.0)}%</td></tr>
                        <tr><td>执行委托时点 (Exec Mode)</td><td><b>{p.get('execution_mode', 'Close')}</b></td></tr>
                        <tr><td>允许隔夜持仓 / 允许午盘持仓</td><td>{p.get('allow_overnight', True)} / {p.get('allow_lunch', True)}</td></tr>
                        <tr><td>合约乘数价值 (Multiplier)</td><td>RM {p.get('multiplier', 0.0):,.2f}</td></tr>
                        <tr><td>单手单边佣金 (Commission)</td><td>RM {p.get('commission', 0.0):,.2f}</td></tr>
                        <tr><td>成交滑点点数 (Slippage)</td><td>{p.get('slippage', 0.0)} Pts</td></tr>
                        <tr><td>单手初始保证金 (Init Margin)</td><td>RM {p.get('initial_margin', 0.0):,.2f}</td></tr>
                    </tbody>
                </table>
            </div>

            <!-- Performance Stats Card -->
            <div class="card">
                <h2>📈 2. 回测绩效总览 (Performance KPI)</h2>
                <table>
                    <thead>
                        <tr><th>评估绩效指标</th><th>测试表现值</th></tr>
                    </thead>
                    <tbody>
                        {kpi_table_html}
                    </tbody>
                </table>
            </div>
        </div>

        {code_html}
        {sens_html}

        <!-- Visualizations -->
        <div class="chart-grid">
            <div class="chart-card">
                <h3>Equity Curve (盯着市值权益曲线)</h3>
                <img src="data:image/png;base64,{equity_img}" alt="Equity Curve">
            </div>
            <div class="chart-card">
                <h3>Net PnL Distribution (净损益交易直方图)</h3>
                <img src="data:image/png;base64,{dist_img}" alt="Net PnL Distribution">
            </div>
            <div class="chart-card">
                <h3>Drawdown (盯市最大回撤曲线)</h3>
                <img src="data:image/png;base64,{dd_img}" alt="Drawdown">
            </div>
            <div class="chart-card">
                <h3>Risk Indicators (ADX / ATR 市场环境指标)</h3>
                <img src="data:image/png;base64,{risk_img}" alt="Risk Indicators">
            </div>
        </div>
    </div>
</body>
</html>
"""
            with open(save_path, 'w', encoding='utf-8') as f:
                f.write(html_content)

            QMessageBox.information(
                self,
                "Report Exported",
                f"Successfully exported beautiful backtest report to:\n\n{save_path}"
            )
        except Exception as e:
            import traceback
            QMessageBox.critical(
                self,
                "Export Error",
                f"An error occurred while compiling the report:\n{str(e)}\n\n{traceback.format_exc()}"
            )
        finally:
            QApplication.restoreOverrideCursor()
