
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QComboBox, QGroupBox, QFormLayout, 
                             QDoubleSpinBox, QSplitter, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QMessageBox, QSpinBox, QCheckBox, QFrame)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor
import pandas as pd
import pyqtgraph as pg
import numpy as np
from pathlib import Path

from core.backtest_engine import BacktestEngine
from ui.widgets.kpi_card import KPICard

class RiskWorker(QThread):
    """
    Worker for Risk Dashboard.
    Runs TWO passes:
    1. Base Run (Risk Manager Disabled) - Pure Vectorized
    2. Audited Run (Risk Manager Enabled) - Iterative/Hybrid
    """
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, data_path, params):
        super().__init__()
        self.data_path = data_path
        self.params = params
        self.engine = BacktestEngine()
        
    def run(self):
        try:
            df = pd.read_parquet(self.data_path)
            
            # --- Pass 1: Base Run (No Risk Manager) ---
            # "Gross Strategy": No filters, no stops, max leverage allowed
            base_params = self.params.copy()
            base_params.pop('max_leverage', None) 
            base_params.pop('risk_per_trade', None) 
            base_params.pop('adx_threshold', None) # Engine doesn't accept this directly
            
            base_params['use_risk_manager'] = False
            base_params['use_adx_filter'] = False 
            base_params['sl_pct'] = 0.0 
            base_params['risk_target'] = 0.0 # Disabled for base
            
            base_results = self.engine.run_backtest(df, **base_params)
            
            # --- Pass 2: Audited Run (With Risk Manager) ---
            audit_params = self.params.copy()
            max_lev = audit_params.pop('max_leverage', 10.0)
            rpt = audit_params.pop('risk_per_trade', 0.02)
            adx_th = audit_params.pop('adx_threshold', 20)
            
            audit_params['use_risk_manager'] = True 
            
            # Construct risk_params dict for RiskManager
            audit_params['risk_params'] = {
                'use_adx': self.params.get('use_adx_filter', False),
                'adx_threshold': adx_th,
                'sl_pct': self.params.get('sl_pct', 0.0),
                'risk_per_trade': rpt,
                'max_leverage': max_lev,
                'buffer_ratio': 0.9,
                'margin_per_lot': self.params.get('initial_margin', 5000), 
                'margin_call_level': 1.1
            }
            
            audited_results = self.engine.run_backtest(df, **audit_params)
            
            # Combine
            final_res = {
                'base': base_results,
                'audited': audited_results
            }
            
            self.finished.emit(final_res)
            
        except Exception as e:
            import traceback
            self.error.emit(str(e) + "\n" + traceback.format_exc())

class RiskTab(QWidget):
    """
    Risk Audit Dashboard.
    Compares 'Net Strategy' vs 'Gross Strategy' (Pre-Risk).
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
        left_panel.setFixedWidth(320)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 10, 0)
        
        # Title
        title = QLabel("🛡️ Risk Sentinel")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #4CAF50;")
        left_layout.addWidget(title)
        
        # 1. Data Selection
        data_group = QGroupBox("Target Strategy")
        data_layout = QFormLayout()
        
        self.file_combo = QComboBox()
        data_layout.addRow("Signal Source:", self.file_combo)
        
        refresh_btn = QPushButton("Refresh List")
        refresh_btn.clicked.connect(self.refresh_files)
        data_layout.addRow(refresh_btn)
        
        data_group.setLayout(data_layout)
        left_layout.addWidget(data_group)
        
        # 1.5 Strategy Parameters
        strat_group = QGroupBox("Strategy Parameters")
        strat_layout = QFormLayout()
        
        self.sb_upper_bound = QDoubleSpinBox()
        self.sb_upper_bound.setRange(-5.0, 5.0)
        self.sb_upper_bound.setValue(0.5)
        self.sb_upper_bound.setSingleStep(0.1)
        strat_layout.addRow("Upper Bound:", self.sb_upper_bound)
        
        self.sb_lower_bound = QDoubleSpinBox()
        self.sb_lower_bound.setRange(-5.0, 5.0)
        self.sb_lower_bound.setValue(-0.5)
        self.sb_lower_bound.setSingleStep(0.1)
        strat_layout.addRow("Lower Bound:", self.sb_lower_bound)
        
        strat_group.setLayout(strat_layout)
        left_layout.addWidget(strat_group)
        
        # 2. Account Settings
        account_group = QGroupBox("Account & Leverage")
        acct_layout = QFormLayout()
        
        self.capital_spin = QDoubleSpinBox()
        self.capital_spin.setRange(1000, 10000000)
        self.capital_spin.setValue(100000)
        self.capital_spin.setSingleStep(1000)
        acct_layout.addRow("Capital (RM):", self.capital_spin)
        
        self.max_lev_spin = QDoubleSpinBox()
        self.max_lev_spin.setRange(1.0, 50.0)
        self.max_lev_spin.setValue(10.0)
        self.max_lev_spin.setSingleStep(0.5)
        self.max_lev_spin.setToolTip("Hard cap on leverage.")
        acct_layout.addRow("Max Leverage:", self.max_lev_spin)

        self.margin_spin = QDoubleSpinBox()
        self.margin_spin.setRange(0, 50000)
        self.margin_spin.setValue(5000)
        acct_layout.addRow("Initial Margin:", self.margin_spin)
        
        account_group.setLayout(acct_layout)
        left_layout.addWidget(account_group)
        
        # 3. Risk Parameters (The Firewalls)
        risk_group = QGroupBox("Risk Firewalls")
        risk_layout = QFormLayout()
        
        # Position Sizing
        self.risk_per_trade = QDoubleSpinBox()
        self.risk_per_trade.setRange(0.1, 10.0)
        self.risk_per_trade.setValue(2.0)
        self.risk_per_trade.setSuffix("%")
        risk_layout.addRow("Risk / Trade:", self.risk_per_trade)
        
        # Regime Audit
        self.adx_chk = QCheckBox("Enable ADX Filter")
        self.adx_chk.setChecked(True)
        risk_layout.addRow(self.adx_chk)
        
        self.adx_thresh = QSpinBox()
        self.adx_thresh.setRange(10, 50)
        self.adx_thresh.setValue(20)
        risk_layout.addRow("ADX Threshold:", self.adx_thresh)
        
        # Intra-bar
        self.sl_pct = QDoubleSpinBox()
        self.sl_pct.setRange(0.0, 10.0)
        self.sl_pct.setValue(1.0)
        self.sl_pct.setSingleStep(0.1)
        self.sl_pct.setSuffix("%")
        risk_layout.addRow("Hard Stop Loss:", self.sl_pct)
        
        risk_group.setLayout(risk_layout)
        left_layout.addWidget(risk_group)
        
        left_layout.addStretch()
        
        # Run Button
        self.run_btn = QPushButton("🚀 Run Audit")
        self.run_btn.setMinimumHeight(50)
        self.run_btn.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; font-size: 14px;")
        self.run_btn.clicked.connect(self._run_audit)
        left_layout.addWidget(self.run_btn)
        
        main_layout.addWidget(left_panel)
        
        # === Right Panel: Dashboard ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # 1. KPI Cards Row
        kpi_layout = QHBoxLayout()
        self.card_calmar = KPICard("Calmar Ratio")
        self.card_mdd_dur = KPICard("Max DD Duration", tooltip_text="Longest period in drawdown")
        self.card_recv = KPICard("Recovery Factor")
        self.card_block = KPICard("Signals Blocked", is_interactive=True, tooltip_text="Click for details")
        
        kpi_layout.addWidget(self.card_calmar)
        kpi_layout.addWidget(self.card_mdd_dur)
        kpi_layout.addWidget(self.card_recv)
        kpi_layout.addWidget(self.card_block)
        
        right_layout.addLayout(kpi_layout)
        
        # 2. Charts & Table Splitter
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # Chart Container
        chart_container = QWidget()
        chart_layout = QVBoxLayout(chart_container)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        
        self.plot_widget = pg.PlotWidget(axisItems={'bottom': pg.DateAxisItem(orientation='bottom')})
        self.plot_widget.setBackground('#1E1E1E')
        # Concise Title
        self.plot_widget.setTitle("Risk Audit Verification", color='#FFF', size='12pt')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.addLegend()
        
        # Axis Labels & Settings
        p1 = self.plot_widget.getPlotItem()
        p1.setLabel('left', "Equity (RM)")
        p1.setLabel('right', "Margin Occupancy Ratio")
        p1.getAxis('right').setZValue(10) # Ensure visibility over grid
        
        # User requested: self.plot_item.getAxis('left').setScientificMode(False)
        p1.getAxis('left').enableAutoSIPrefix(False)
        
        # Adjust Margins to prevent right-axis clipping
        # p1.setContentsMargins(10, 10, 40, 10) # PlotItem margins
        # User requested: self.plot_widget.setContentsMargins(10, 10, 40, 10) 
        # But PlotWidget is the container. Let's try to apply to plotItem if possible or widget.
        # PyQtGraph's layout system usually handles labels, but sometimes right axis clips window.
        # Setting layout padding on the PlotItem is usually effective.
        # However, passing it to setContentsMargins of the widget might clip the canvas.
        # Let's trust user instruction specifically for the widget or plot item.
        # "Suggest using self.plot_widget.setContentsMargins(...)"
        self.plot_widget.setContentsMargins(10, 10, 40, 10)
        
        chart_layout.addWidget(self.plot_widget)
        
        splitter.addWidget(chart_container)
        
        # Comparison Table
        self.comp_table = QTableWidget()
        self.comp_table.setColumnCount(3)
        self.comp_table.setHorizontalHeaderLabels(["Metric", "Base Strategy (Gross)", "Audited Strategy (Net)"])
        self.comp_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.comp_table.verticalHeader().setVisible(False)
        self.comp_table.setAlternatingRowColors(True)
        splitter.addWidget(self.comp_table)
        
        splitter.setSizes([500, 200])
        right_layout.addWidget(splitter)
        
        main_layout.addWidget(right_panel)
        self.setLayout(main_layout)
        
        self.refresh_files()

    def refresh_files(self):
        path = Path("data/signals")
        if not path.exists(): path.mkdir(parents=True, exist_ok=True)
        files = list(path.glob("*.parquet"))
        self.file_combo.clear()
        if files:
            self.file_combo.addItems([f.name for f in files])
        else:
            self.file_combo.addItem("No signals found")
            self.run_btn.setEnabled(False)
            
        if self.file_combo.count() > 0 and self.file_combo.currentText() != "No signals found":
             self.run_btn.setEnabled(True)

    def _get_params(self):
        # FCPO defaults for now, can be parameterized if needed
        return {
            'multiplier': 25, 
            'commission': 15,
            'slippage': 1,
            'initial_capital': self.capital_spin.value(),
            'initial_margin': self.margin_spin.value(),
            'max_leverage': self.max_lev_spin.value(),
            'risk_per_trade': self.risk_per_trade.value() / 100.0,
            'use_adx_filter': self.adx_chk.isChecked(),
            'adx_threshold': self.adx_thresh.value(),
            'sl_pct': self.sl_pct.value(),
            'upper_bound': self.sb_upper_bound.value(),
            'lower_bound': self.sb_lower_bound.value(),
            # Base engine params
            'execution_mode': 'Next Open', # Default to robust mode for audit
            'allow_lunch': True,
            'allow_overnight': True
        }

    def _run_audit(self):
        filename = self.file_combo.currentText()
        if not filename or filename == "No signals found": return
        path = str(Path("data/signals") / filename)
        
        params = self._get_params()
        
        self.run_btn.setEnabled(False)
        self.run_btn.setText("⏳ Auditing...")
        
        self.worker = RiskWorker(path, params)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()
        
    def _on_finished(self, results):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("🚀 Run Audit")
        self.current_results = results
        
        base_metrics = results['base']['metrics']
        audit_metrics = results['audited']['metrics']
        
        self._update_table(base_metrics, audit_metrics)
        self._update_kpis(audit_metrics, results['audited'].get('audit_log', [])) # Engine needs to return audit_log
        self._plot_chart(results['base']['equity_curve'], results['audited']['equity_curve'])
        
        QMessageBox.information(self, "Audit Complete", "Risk Audit Analysis Finished.")

    def _on_error(self, msg):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("🚀 Run Audit")
        QMessageBox.critical(self, "Error", msg)

    def _update_table(self, base, audit):
        metrics = [
            ("Net Profit", "Net Profit"),
            ("Max Drawdown (%)", "Max Drawdown (%)"),
            ("Sharpe Ratio", "Sharpe Ratio"),
            ("Calmar Ratio", "Calmar Ratio"),
            ("Win Rate (%)", "Win Rate (%)"),
            ("Total Trades", "Total Trades"),
            ("Profit Factor", "Profit Factor")
        ]
        
        self.comp_table.setRowCount(len(metrics))
        for i, (name, key) in enumerate(metrics):
            self.comp_table.setItem(i, 0, QTableWidgetItem(name))
            
            b_val = base.get(key, 0)
            a_val = audit.get(key, 0)
            
            # Formatting
            if isinstance(b_val, float): b_str = f"{b_val:,.2f}"
            else: b_str = str(b_val)
            
            if isinstance(a_val, float): a_str = f"{a_val:,.2f}"
            else: a_str = str(a_val)
            
            self.comp_table.setItem(i, 1, QTableWidgetItem(b_str))
            
            # Audited column with color diff
            item_a = QTableWidgetItem(a_str)
            if isinstance(a_val, (int, float)) and isinstance(b_val, (int, float)):
                if a_val > b_val and "Drawdown" not in name:
                    item_a.setForeground(QColor("#4CAF50")) # Better
                elif a_val < b_val and "Drawdown" not in name:
                    item_a.setForeground(QColor("#FF5252")) # Worse
                elif "Drawdown" in name:
                     if abs(a_val) < abs(b_val): item_a.setForeground(QColor("#4CAF50")) # Lower DD is green
            
            self.comp_table.setItem(i, 2, item_a)

    def _update_kpis(self, metrics, audit_log=None):
        self.card_calmar.update_value(f"{metrics.get('Calmar Ratio', 0):.2f}", 'calmar')
        self.card_recv.update_value(f"{metrics.get('Recovery Factor', 0):.2f}", 'recovery_factor')
        
        # Mock MDD Duration (Now calculated in engine)
        mdd_dur = metrics.get('Max DD Duration', 0)
        self.card_mdd_dur.update_value(f"{mdd_dur} Days", 'mdd_duration')
        
        # Block Breakdown
        # In a real scenario, we'd parse `audit_log` from RiskManager
        # Since we modified RiskManager to have `audit_log`, we need to get it out.
        # Assuming result['audited_log'] or similar passed out.
        # For now, simulate breakdown
        breakdown = {'ADX Filter': 0, 'Margin': 0, 'Intra-bar SL': 0}
        total_blocked = 0
        
        if audit_log is not None:
             # Need to ensure audit_log is a dataframe or list of dicts
             # If passed as DataFrame:
             if isinstance(audit_log, pd.DataFrame) and not audit_log.empty:
                 counts = audit_log['Type'].value_counts()
                 breakdown['ADX Filter'] = counts.get('Regime_Audit', 0)
                 breakdown['Margin'] = counts.get('Position_Sizing', 0) # Reduced/Blocked
                 breakdown['Intra-bar SL'] = counts.get('Intra_SL', 0) + counts.get('Gap_SL', 0)
                 total_blocked = len(audit_log)
        
        self.card_block.update_value(total_blocked)
        self.card_block.set_breakdown(breakdown)

    def _plot_chart(self, base_df, audit_df):
        self.plot_widget.clear()
        
        # Helper to convert index to timestamp array
        def get_ts(df):
            if df.empty: return np.array([])
            return df.index.astype(np.int64).values // 10**9
            
        x_base = get_ts(base_df)
        x_audit = get_ts(audit_df)
        
        # 1. Base Equity (Gray Dashed)
        if not base_df.empty:
            self.plot_widget.plot(
                x=x_base, 
                y=base_df['equity'].values, 
                pen=pg.mkPen(color='#666666', width=1, style=Qt.PenStyle.DashLine),
                name="Base Strategy"
            )
        
        # 2. Audited Equity (Green Solid)
        if not audit_df.empty:
            self.plot_widget.plot(
                x=x_audit, 
                y=audit_df['equity'].values, 
                pen=pg.mkPen(color='#4CAF50', width=2),
                name="Audited Strategy"
            )
        
        # 3. Used Margin (Right Axis)
        p1 = self.plot_widget.getPlotItem()
        # Clean up old ViewBox if exists? Not easily.
        # But we clear plot widget which clears plot items, but maybe not ViewBox attached to scene.
        # Re-adding ViewBox every time might leak or overlap.
        # We should check if we already added a ViewBox.
        
        # Simplified: Check if p1 has a ViewBox attached that is not p1.vb
        # Actually, let's just create a new one. In repeated calls, this adds more ViewBoxes.
        # Better: Store p2 in self.
        
        if not hasattr(self, 'p2'):
            self.p2 = pg.ViewBox()
            p1.showAxis('right')
            p1.scene().addItem(self.p2)
            p1.getAxis('right').linkToView(self.p2)
            self.p2.setXLink(p1)
            
            def updateViews():
                self.p2.setGeometry(p1.vb.sceneBoundingRect())
                self.p2.linkedViewChanged(p1.vb, self.p2.XAxis)
            p1.vb.sigResized.connect(updateViews)
            # updateViews() called below
        else:
             self.p2.clear()
             
        # Plot Margin on p2
        if not audit_df.empty:
            margin = audit_df['used_margin'].values if 'used_margin' in audit_df else np.zeros(len(audit_df))
            
            # Fill (Blue)
            margin_curve = pg.PlotCurveItem(x=x_audit, y=margin, pen=pg.mkPen(color='#2196F3', width=1))
            margin_fill = pg.FillBetweenItem(
                curve1=margin_curve, 
                curve2=pg.PlotCurveItem(x=x_audit, y=np.zeros(len(x_audit)), pen=None),
                brush=pg.mkBrush(color=(33, 150, 243, 50)) 
            )
            self.p2.addItem(margin_fill)
            
            # Stress Zone (Red) -> Margin / Equity > 0.8
            equity = audit_df['equity'].values
            utilization = np.zeros_like(equity)
            mask = equity != 0
            utilization[mask] = margin[mask] / equity[mask]
            
            stress_y = margin.copy()
            stress_y[utilization <= 0.8] = 0 # Hide
            
            stress_curve = pg.PlotCurveItem(x=x_audit, y=stress_y, pen=None)
            stress_fill = pg.FillBetweenItem(
                 curve1=stress_curve,
                 curve2=pg.PlotCurveItem(x=x_audit, y=np.zeros(len(x_audit)), pen=None),
                 brush=pg.mkBrush(color=(255, 82, 82, 100)) 
            )
            self.p2.addItem(stress_fill)
            
            # Force update views
            self.p2.setGeometry(p1.vb.sceneBoundingRect())
            self.p2.linkedViewChanged(p1.vb, self.p2.XAxis)
