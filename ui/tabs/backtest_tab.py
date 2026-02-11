
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QComboBox, QGroupBox, QFormLayout, 
                             QDoubleSpinBox, QSplitter, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QMessageBox, QSpinBox, QTabWidget, QCheckBox, QFileDialog)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
import os
from pathlib import Path

# Set backend
matplotlib.use('QtAgg')
plt.style.use('dark_background')

from core.backtest_engine import BacktestEngine

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
            
            if self.task_type == 'run':
                # 1. Run Standard Backtest
                results = self.engine.run_backtest(
                    df, 
                    multiplier=self.params['multiplier'],
                    commission=self.params['commission'],
                    slippage=self.params['slippage'],
                    initial_capital=self.params['initial_capital'],
                    upper_bound=self.params['upper_bound'],
                    lower_bound=self.params['lower_bound'],
                    initial_margin=self.params['initial_margin'],
                    maintenance_margin_rate=0.8,
                    allow_lunch=self.params['allow_lunch'],
                    allow_overnight=self.params['allow_overnight'],
                    execution_mode=self.params.get('execution_mode', 'Close'),
                    risk_target=self.params.get('risk_target', 0.0),
                    sl_pct=self.params.get('sl_pct', 0.0),
                    use_adx_filter=self.params.get('use_adx_filter', False),
                    max_lots=self.params.get('max_lots', 20)
                )
                
                # 2. Run Audit (Lookahead Bias)
                audit_res = self.engine.audit_lookahead(df, self.params)
                results['audit'] = audit_res
                
                # 3. Generate Trade Log
                trade_log = self.engine.generate_trade_log(results['equity_curve'])
                results['trade_log'] = trade_log
                
                self.finished.emit(results)
                
            elif self.task_type == 'sensitivity':
                # Run Slippage Sensitivity
                sens_res = self.engine.run_sensitivity_test(df, self.params)
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
        
    def init_ui(self):
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # === Left Panel: Settings ===
        left_panel = QWidget()
        left_panel.setFixedWidth(320) # Widened for new controls
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 10, 0)
        
        # Title
        title = QLabel("Backtest Engine")
        font = title.font()
        font.setPointSize(14)
        font.setBold(True)
        title.setFont(font)
        left_layout.addWidget(title)
        
        # 1. Data Selection
        data_group = QGroupBox("Signal Source")
        data_layout = QFormLayout()
        
        self.file_combo = QComboBox()

        data_layout.addRow("File:", self.file_combo)
        
        refresh_btn = QPushButton("Refresh List")
        refresh_btn.clicked.connect(self.refresh_files)
        data_layout.addRow(refresh_btn)
        
        data_group.setLayout(data_layout)
        left_layout.addWidget(data_group)
        
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
        left_layout.addWidget(market_group)
        
        # 3. Strategy Parameters
        strat_group = QGroupBox("Strategy Params")
        strat_layout = QFormLayout()
        
        self.capital_spin = QDoubleSpinBox()
        self.capital_spin.setRange(1000, 10000000)
        self.capital_spin.setValue(100000)
        self.capital_spin.setSingleStep(1000)
        strat_layout.addRow("Capital (RM):", self.capital_spin)
        
        self.upper_bound = QDoubleSpinBox()
        self.upper_bound.setRange(-10, 10)
        self.upper_bound.setValue(0.5)
        self.upper_bound.setSingleStep(0.1)
        strat_layout.addRow("Upper Bound (>):", self.upper_bound)
        
        self.lower_bound = QDoubleSpinBox()
        self.lower_bound.setRange(-10, 10)
        self.lower_bound.setValue(-0.5)
        self.lower_bound.setSingleStep(0.1)
        strat_layout.addRow("Lower Bound (<):", self.lower_bound)
        
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
        self.exec_mode_combo.addItems(["Close (T+1)", "Next Open (T+1)"])
        self.exec_mode_combo.setToolTip("Close: Exec at Close T+1 via Signal T\nNext Open: Exec at Open T+1 via Signal T-1 (Robust)")
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
        left_layout.addWidget(strat_group)
        
        left_layout.addStretch()
        
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
        
        self.export_btn = QPushButton("💾 Export Trade Log")
        self.export_btn.setEnabled(False) # Enabled after run
        self.export_btn.clicked.connect(self._export_trade_log)
        header_layout.addWidget(self.export_btn)
        
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
        self.sens_table.setHorizontalHeaderLabels(["Slippage", "Net Profit", "Calmar", "Trades"])
        self.sens_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.sens_table.verticalHeader().setVisible(False)
        self.sens_table.setAlternatingRowColors(True)
        metrics_splitter.addWidget(self.sens_table)
        
        # Set initial sizes
        metrics_splitter.setSizes([400, 200])
        
        right_layout.addWidget(metrics_splitter)
        right_layout.setStretchFactor(metrics_splitter, 1) # Small portion for metrics
        
        # Charts Tabs
        self.chart_tabs = QTabWidget()
        
        # 1. Equity Curve
        self.equity_fig = plt.figure()
        self.equity_canvas = FigureCanvas(self.equity_fig)
        self.chart_tabs.addTab(self.equity_canvas, "Equity Curve")
        
        # 2. Position Plot
        self.pos_fig = plt.figure()
        self.pos_canvas = FigureCanvas(self.pos_fig)
        self.chart_tabs.addTab(self.pos_canvas, "Position Analysis")
        
        # 3. Drawdown
        self.dd_fig = plt.figure()
        self.dd_fig.clear() # Clear before init to be safe? No, just create new.
        self.dd_canvas = FigureCanvas(self.dd_fig)
        self.chart_tabs.addTab(self.dd_canvas, "Drawdown")
        
        # 4. Risk Indicators (Phase 5.2)
        self.risk_fig = plt.figure()
        self.risk_canvas = FigureCanvas(self.risk_fig)
        self.chart_tabs.addTab(self.risk_canvas, "Risk Indicators")
        
        right_layout.addWidget(self.chart_tabs)
        right_layout.setStretchFactor(self.chart_tabs, 3) # Larger portion for charts
        
        main_layout.addWidget(right_panel)
        
        self.setLayout(main_layout)
        
        # Initial refresh
        self.refresh_files()
        
    def refresh_files(self):
        """Scan data/signals/"""
        path = Path("data/signals")
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            
        files = list(path.glob("*.parquet"))
        self.file_combo.clear()
        if files:
            self.file_combo.addItems([f.name for f in files])
        else:
            self.file_combo.addItem("No signals found")
            self.run_btn.setEnabled(False)
            self.pressure_btn.setEnabled(False)
            
        if self.file_combo.count() > 0 and self.file_combo.currentText() != "No signals found":
             self.run_btn.setEnabled(True)
             self.pressure_btn.setEnabled(True)

    def _get_params(self):
        return {
            'multiplier': self.multiplier_spin.value(),
            'commission': self.commission_spin.value(),
            'slippage': self.slippage_spin.value(),
            'initial_capital': self.capital_spin.value(),
            'upper_bound': self.upper_bound.value(),
            'lower_bound': self.lower_bound.value(),
            'initial_margin': self.margin_spin.value(),
            'allow_overnight': self.intraday_chk.isChecked(),
            'allow_lunch': self.lunch_chk.isChecked(),
            'execution_mode': 'Next Open' if "Next Open" in self.exec_mode_combo.currentText() else 'Close',
            'risk_target': self.risk_target.value(),
            'sl_pct': self.sl_pct.value(),
            'use_adx_filter': self.adx_chk.isChecked(),
            'max_lots': self.max_lots.value()
        }

    def _run_backtest(self):
        filename = self.file_combo.currentText()
        if not filename or filename == "No signals found": return
        path = str(Path("data/signals") / filename)
        
        params = self._get_params()
        
        self.run_btn.setEnabled(False)
        self.run_btn.setText("⏳ Running...")
        self.audit_label.setText("") 
        
        self.worker = BacktestWorker(path, params, task_type='run')
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()
        
    def _run_pressure_test(self):
        filename = self.file_combo.currentText()
        if not filename or filename == "No signals found": return
        path = str(Path("data/signals") / filename)
        
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
        self.current_results = results
        self.export_btn.setEnabled(True)
        
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
        
    def _on_sensitivity_finished(self, results):
        self.pressure_btn.setEnabled(True)
        self.pressure_btn.setText("🔥 Pressure Test")
        
        self.sens_table.setRowCount(len(results))
        for i, res in enumerate(results):
            self.sens_table.setItem(i, 0, QTableWidgetItem(str(res['Slippage'])))
            self.sens_table.setItem(i, 1, QTableWidgetItem(f"{res['Net Profit']:,.0f}"))
            self.sens_table.setItem(i, 2, QTableWidgetItem(f"{res['Calmar']:.2f}"))
            self.sens_table.setItem(i, 3, QTableWidgetItem(str(res['Trades'])))
            
        QMessageBox.information(self, "Pressure Test", "Slippage Sensitivity Test Complete!")

    def _on_error(self, msg):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("🚀 Run Backtest")
        self.pressure_btn.setEnabled(True)
        self.pressure_btn.setText("🔥 Pressure Test")
        
        if "must contain 'close'" in msg:
            QMessageBox.critical(self, "Data Error", 
                "The selected signal file is missing price data ('close' column).\n\n"
                "Possible Fixes:\n"
                "1. Regenerate the signal in 'Alpha Research' tab (Code updated to fix this).\n"
                "2. Ensure your original data has a 'close', 'last', or 'price' column."
            )
        else:
            QMessageBox.critical(self, "Error", msg)
            
    def _export_trade_log(self):
        if not self.current_results or 'trade_log' not in self.current_results:
            return
            
        df = self.current_results['trade_log']
        if df.empty:
            QMessageBox.information(self, "Export", "No trades were generated.")
            return

        filename, _ = QFileDialog.getSaveFileName(self, "Export Trade Log", "trade_log.csv", "CSV Files (*.csv)")
        if filename:
            try:
                df.to_csv(filename, index=False)
                QMessageBox.information(self, "Success", f"Trade log exported to:\n{filename}")
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
        df = results['equity_curve']
        
        # 1. Equity Curve & Margin Line
        self.equity_fig.clear()
        ax1 = self.equity_fig.add_subplot(111)
        ax1.plot(df.index, df['equity'], color='#4CAF50', linewidth=2, label='Equity')
        
        # Plot Maintenance Level (Red Line)
        if 'maint_level' in df.columns:
             ax1.plot(df.index, df['maint_level'], color='#FF5252', linestyle='--', linewidth=1, label='Margin Call Level')
             
        ax1.set_title("Equity Curve (RM)")
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        self.equity_fig.autofmt_xdate()
        self.equity_canvas.draw()
        
        # 2. Position Plot (Step Chart)
        self.pos_fig.clear()
        ax2 = self.pos_fig.add_subplot(111)
        # Plot signal/position
        ax2.step(df.index, df['pos'], where='post', color='#2196F3', linewidth=1.5)
        ax2.set_yticks([-1, 0, 1])
        ax2.set_yticklabels(['Short', 'Neutral', 'Long'])
        ax2.set_title("Position Status")
        ax2.grid(True, alpha=0.3)
        self.pos_fig.autofmt_xdate()
        self.pos_canvas.draw()
        
        # 3. Drawdown Area
        self.dd_fig.clear()
        ax3 = self.dd_fig.add_subplot(111)
        ax3.fill_between(df.index, df['drawdown_pct'] * 100, 0, color='#FF5252', alpha=0.6)
        ax3.set_title("Drawdown (%)")
        ax3.set_ylabel("Drawdown %")
        ax3.grid(True, alpha=0.3)
        self.dd_fig.autofmt_xdate()
        self.dd_fig.autofmt_xdate()
        self.dd_canvas.draw()
        
        # 4. Risk Indicators (ATR/ADX)
        self.risk_fig.clear()
        ax4 = self.risk_fig.add_subplot(111)
        
        has_risk_data = False
        if 'atr' in df.columns:
            ax4.plot(df.index, df['atr'], label='ATR(14)', color='cyan', linewidth=1.5)
            has_risk_data = True
            
        if 'adx' in df.columns:
            ax4_2 = ax4.twinx()
            ax4_2.plot(df.index, df['adx'], label='ADX(14)', color='magenta', linestyle='--', linewidth=1.5)
            ax4_2.axhline(20, color='gray', linestyle=':', alpha=0.5)
            ax4_2.legend(loc='upper right')
            has_risk_data = True
        
        if has_risk_data:
            ax4.set_title("Risk Indicators (ATR & ADX)")
            ax4.legend(loc='upper left')
            ax4.grid(True, alpha=0.3)
            self.risk_fig.autofmt_xdate()
            self.risk_canvas.draw()
