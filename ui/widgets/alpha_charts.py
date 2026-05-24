"""
AlphaCharts Widget - Alpha Factor Analysis Visualization Component

Extracted from alpha_tab.py to improve maintainability and reusability.
Phase 5B.3: UI Refactor conforming to Single Responsibility Principle.

Provides 4 analysis chart tabs: IC Analysis, IC Decay, Quantile Analysis, and Risk Analysis.
"""

from PyQt6.QtWidgets import QWidget, QTabWidget, QVBoxLayout, QSplitter, QSizePolicy
from PyQt6.QtCore import Qt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np


class AlphaCharts(QTabWidget):
    """
    Reusable alpha factor analysis visualization widget.
    
    Provides four chart tabs:
    1. IC Analysis - Information Coefficient over time
    2. IC Decay - Coefficient decay over prediction periods
    3. Quantile Analysis - Factor distribution and cumulative returns
    4. Risk Analysis - Correlation heatmap or placeholder
    """
    
    def __init__(self):
        super().__init__()
        self._setup_charts()
    
    def _setup_charts(self):
        """Initialize all chart tabs."""
        # Tab 1: IC over time
        tab1 = QWidget()
        tab1_layout = QVBoxLayout(tab1)
        tab1_layout.setContentsMargins(0, 0, 0, 0)
        
        self.ic_figure = plt.figure()
        self.ic_canvas = FigureCanvas(self.ic_figure)
        self.ic_canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        tab1_layout.addWidget(self.ic_canvas)
        
        self.addTab(tab1, "IC Analysis")
        
        # Tab 2: IC Decay
        tab2 = QWidget()
        tab2_layout = QVBoxLayout(tab2)
        tab2_layout.setContentsMargins(0, 0, 0, 0)
        
        self.decay_figure = plt.figure()
        self.decay_canvas = FigureCanvas(self.decay_figure)
        tab2_layout.addWidget(self.decay_canvas)
        
        self.addTab(tab2, "IC Decay")
        
        # Tab 3: Quantile Analysis (Splitter: Distribution + Cumulative)
        tab3 = QWidget()
        tab3_layout = QVBoxLayout(tab3)
        tab3_layout.setContentsMargins(0, 0, 0, 0)
        
        tab3_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        self.q_figure = plt.figure()
        self.q_canvas = FigureCanvas(self.q_figure)
        tab3_splitter.addWidget(self.q_canvas)
        
        self.q_cum_figure = plt.figure()
        self.q_cum_canvas = FigureCanvas(self.q_cum_figure)
        tab3_splitter.addWidget(self.q_cum_canvas)
        
        tab3_layout.addWidget(tab3_splitter)
        self.addTab(tab3, "Quantile Analysis")
        
        # Tab 4: Risk Analysis
        tab4 = QWidget()
        tab4_layout = QVBoxLayout(tab4)
        tab4_layout.setContentsMargins(0, 0, 0, 0)
        
        self.risk_figure = plt.figure()
        self.risk_canvas = FigureCanvas(self.risk_figure)
        tab4_layout.addWidget(self.risk_canvas)
        
        self.addTab(tab4, "Risk Analysis")

        # Tab 5: Stability & Reality (New Phase 5)
        tab5 = QWidget()
        tab5_layout = QVBoxLayout(tab5)
        tab5_layout.setContentsMargins(0, 0, 0, 0)
        
        self.setup_stability_tab(tab5_layout)
        
        self.addTab(tab5, "Stability & Reality")
    
    def setup_stability_tab(self, layout):
        """Initialize Stability & Reality tab components."""
        from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
        
        # 1. Summary Table
        self.stability_table = QTableWidget()
        self.stability_table.setColumnCount(3)
        self.stability_table.setHorizontalHeaderLabels(["Metric", "Value", "Rating"])
        self.stability_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.stability_table.verticalHeader().setVisible(False)
        self.stability_table.setMaximumHeight(200)
        layout.addWidget(self.stability_table)
        
        # 2. Charts (Splitter)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Turnover Chart
        self.turnover_figure = plt.figure()
        self.turnover_canvas = FigureCanvas(self.turnover_figure)
        splitter.addWidget(self.turnover_canvas)
        
        # Autocorrelation Chart (or anything else relevant)
        # Maybe rolling turnover? Or Factor Autocorrelation visual?
        # Let's do Factor Autocorrelation if available, or just a placeholder for now
        self.autocorr_figure = plt.figure()
        self.autocorr_canvas = FigureCanvas(self.autocorr_figure)
        splitter.addWidget(self.autocorr_canvas)
        
        layout.addWidget(splitter)

    def update_ic_analysis(self, ic_series):
        """
        Update IC over time chart.
        
        Args:
            ic_series: pandas Series or DataFrame with IC values
        """
        self.ic_figure.clear()
        if ic_series is not None and not ic_series.empty:
            ax = self.ic_figure.add_subplot(111)
            
            # Handle both DataFrame and Series
            if isinstance(ic_series, pd.DataFrame):
                # Extract IC column (usually 'Rank_IC' or first column)
                if 'Rank_IC' in ic_series.columns:
                    ic_values = ic_series['Rank_IC'].values
                    ic_index = ic_series.index
                else:
                    ic_values = ic_series.iloc[:, 0].values
                    ic_index = ic_series.index
            else:
                ic_values = ic_series.values
                ic_index = ic_series.index
            
            x = range(len(ic_values))
            colors = ['#4CAF50' if float(v) >= 0 else '#FF5252' for v in ic_values]
            ax.bar(x, ic_values, color=colors)
            ax.axhline(0, color='white', linewidth=0.8, linestyle='--')
            ax.set_title('Information Coefficient (IC) Over Time')
            ax.set_xlabel('Period')
            ax.set_ylabel('IC')
            ax.grid(True, alpha=0.3)
            
            # Add some labels if not too many
            if len(ic_values) <= 50:
                ax.set_xticks(x[::max(1, len(x)//10)])
                ax.set_xticklabels([str(ic_index[i])[:10] for i in x[::max(1, len(x)//10)]], rotation=45)
                self.ic_figure.autofmt_xdate()
            
            # Calculate mean IC skipping NaNs
            mean_ic = np.nanmean(ic_values)
            ax.text(0.02, 0.98, f'Mean IC: {mean_ic:.4f}', transform=ax.transAxes, 
                   verticalalignment='top', fontsize=10, bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
        
        self.ic_canvas.draw()
    
    def update_ic_decay(self, decay_data):
        """
        Update IC decay chart.
        
        Args:
            decay_data: pandas Series with period index and IC values
        """
        self.decay_figure.clear()
        if decay_data is not None and not decay_data.empty:
            ax = self.decay_figure.add_subplot(111)
            ax.plot(decay_data.index, decay_data.values, marker='o', color='#2196F3', linewidth=2)
            ax.set_title('IC Decay Over Prediction Periods')
            ax.set_xlabel('Prediction Period')
            ax.set_ylabel('IC')
            ax.grid(True, alpha=0.3)
            ax.axhline(0, color='gray', linestyle='--', alpha=0.5)
        
        self.decay_canvas.draw()
    
    def update_quantile_analysis(self, quantile_rets, quantile_cum):
        """
        Update quantile distribution and cumulative returns.
        
        Args:
            quantile_rets: DataFrame with quantile returns
            quantile_cum: DataFrame with cumulative returns by quantile
        """
        # Distribution chart
        self.q_figure.clear()
        if quantile_rets is not None and not quantile_rets.empty:
            ax = self.q_figure.add_subplot(111)
            quantile_rets.plot(kind='bar', ax=ax, color='#4CAF50')
            ax.set_title('Mean Return by Quantile')
            ax.set_ylabel('Mean Return')
            ax.grid(True, alpha=0.3)
        
        self.q_canvas.draw()
        
        # Cumulative returns chart
        self.q_cum_figure.clear()
        if quantile_cum is not None and not quantile_cum.empty:
            ax = self.q_cum_figure.add_subplot(111)
            
            # Plot each quantile
            colors = ['#FF5252', '#FFA726', '#FFEB3B', '#66BB6A', '#4CAF50']
            for i, col in enumerate(quantile_cum.columns):
                color = colors[i % len(colors)]
                ax.plot(quantile_cum.index, quantile_cum[col], label=f'Q{col}', 
                       color=color, linewidth=2, alpha=0.8)
            
            ax.set_title('Cumulative Returns by Quantile')
            ax.set_xlabel('Date')
            ax.set_ylabel('Cumulative Return')
            ax.legend(loc='best')
            ax.grid(True, alpha=0.3)
            
            # Format x-axis if datetime
            if isinstance(quantile_cum.index, pd.DatetimeIndex):
                self.q_cum_figure.autofmt_xdate()
        
        self.q_cum_canvas.draw()
    
    def update_risk_analysis(self, corr_matrix):
        """
        Update risk correlation heatmap.
        
        Args:
            corr_matrix: DataFrame with correlation matrix
        """
        self.risk_figure.clear()
        
        if corr_matrix is not None and not corr_matrix.empty:
            ax = self.risk_figure.add_subplot(111)
            im = ax.imshow(corr_matrix.values, cmap='coolwarm', aspect='auto', vmin=-1, vmax=1)
            self.risk_figure.colorbar(im, ax=ax)
            
            # Set ticks
            ax.set_xticks(range(len(corr_matrix.columns)))
            ax.set_yticks(range(len(corr_matrix.index)))
            ax.set_xticklabels(corr_matrix.columns, rotation=45, ha='right')
            ax.set_yticklabels(corr_matrix.index)
            
            # Add values
            for i in range(len(corr_matrix.index)):
                for j in range(len(corr_matrix.columns)):
                    val = corr_matrix.iloc[i, j]
                    color = 'white' if abs(val) > 0.5 else 'black'
                    ax.text(j, i, f'{val:.2f}', ha='center', va='center', 
                           color=color, fontsize=8)
            
            ax.set_title('Factor Correlation Matrix')
            self.risk_figure.tight_layout()
            self.risk_canvas.draw()
        else:
            # Placeholder
            if hasattr(corr_matrix, '__len__') and len(corr_matrix) == 0:
                ax = self.risk_figure.add_subplot(111)
                ax.text(0.5, 0.5, 'No data available', ha='center', va='center', fontsize=14)
                ax.axis('off')
                self.risk_canvas.draw()
            else:
                ax = self.risk_figure.add_subplot(111)
                ax.text(0.5, 0.5, 'Insufficient data for correlation analysis', 
                       ha='center', va='center', fontsize=12, color='gray')
                ax.axis('off')
                self.risk_canvas.draw()

    def update_stability_analysis(self, metrics, turnover_series=None):
        """
        Update Stability & Reality tab.
        
        Args:
            metrics (dict): Professional metrics dictionary.
            turnover_series (list/array): Time-series of turnover for visualization.
        """
        # 1. Update Table
        rows = [
            ("IC Mean", metrics.get('ic_mean', 0), 0.05), # Thresholds logic needs to be robust
            ("IC IR", metrics.get('ic_ir', 0), 0.5),
            ("T-Stat", metrics.get('t_stat', 0), 2.0),
            ("Turnover (Q)", metrics.get('quantile_turnover', 0), 0.2), # Lower is better for turnover
            ("Autocorrelation", metrics.get('autocorrelation', 0), 0.9),
            ("Factor Coverage", metrics.get('coverage', 0), 0.95),
            ("Half-Life", metrics.get('half_life', 0), 5) # dependent on freq
        ]
        
        # Custom Metric extraction if not direct keys (some might be from alpha_engine calc)
        # The metrics dict passed here is the 'professional_metrics' sub-dict
        
        # Re-define rows based on actual keys from alpha_engine
        display_rows = []
        display_rows.append(("Rank IC IR", metrics.get('rank_ic_ir', 0), "High > 0.5"))
        display_rows.append(("T-Stat", metrics.get('t_stat', 0), "Sig > 2.0"))
        display_rows.append(("IC Win Rate", metrics.get('ic_win_rate', 0), "High > 55%"))
        display_rows.append(("Turnover", metrics.get('quantile_turnover', 0), "Low < 20%"))
        display_rows.append(("Autocorrelation", metrics.get('autocorrelation', 0), "High > 0.9"))
        display_rows.append(("Half-Life", metrics.get('half_life', 0), "Context"))
        display_rows.append(("Coverage", metrics.get('coverage', 0), "High > 95%"))
        
        self.stability_table.setRowCount(len(display_rows))
        
        from PyQt6.QtWidgets import QTableWidgetItem
        from PyQt6.QtGui import QColor
        
        for i, (name, val, criterion) in enumerate(display_rows):
            self.stability_table.setItem(i, 0, QTableWidgetItem(name))
            
            # Format Value
            val_str = f"{val:.4f}"
            if name in ["IC Win Rate", "Turnover", "Coverage"]:
                val_str = f"{val*100:.1f}%"
            elif name == "Half-Life":
                if val == float('inf'):
                    val_str = "∞ (极稳定)"
                else:
                    val_str = f"{val:.1f}"
                
            self.stability_table.setItem(i, 1, QTableWidgetItem(val_str))
            
            # Rating Logic
            rating_item = QTableWidgetItem("Neutral")
            color = None
            
            if name == "Rank IC IR":
                if abs(val) > 1.0: 
                    rating_item.setText("Excellent"); color = QColor("#4CAF50")
                elif abs(val) > 0.5:
                    rating_item.setText("Good"); color = QColor("#8BC34A")
                else:
                    rating_item.setText("Weak"); color = QColor("#FF9800")
            elif name == "T-Stat":
                if abs(val) > 2.0:
                    rating_item.setText("Significant"); color = QColor("#4CAF50")
                else:
                    rating_item.setText("Insignif."); color = QColor("#F44336")
            elif name == "Turnover":
                if val < 0.2:
                    rating_item.setText("Low Cost"); color = QColor("#4CAF50")
                elif val < 0.5:
                    rating_item.setText("Medium"); color = QColor("#FF9800")
                else:
                    rating_item.setText("High Cost"); color = QColor("#F44336")
            elif name == "IC Win Rate":
                 if val > 0.55:
                     rating_item.setText("Consistent"); color = QColor("#4CAF50")
                 else:
                     rating_item.setText("Unstable"); color = QColor("#FF9800")
                     
            if color:
                rating_item.setBackground(color)
                rating_item.setForeground(QColor("white"))
                
            self.stability_table.setItem(i, 2, rating_item)

        # 2. Update Charts
        # Turnover Series
        self.turnover_figure.clear()
        if turnover_series and len(turnover_series) > 0:
            ax = self.turnover_figure.add_subplot(111)
            ax.plot(turnover_series, color='#FF9800', alpha=0.7, label='Turnover')
            ax.set_title('Quantile Turnover (Time Series)')
            ax.set_xlabel('Period')
            ax.set_ylabel('Turnover Ratio')
            ax.axhline(np.mean(turnover_series), color='white', linestyle='--', label='Mean')
            ax.legend()
            ax.grid(True, alpha=0.3)
        else:
             ax = self.turnover_figure.add_subplot(111)
             ax.text(0.5, 0.5, 'No Turnover Data', ha='center', va='center', color='gray')
        self.turnover_canvas.draw()
        
        # Autocorrelation (Visualizing Lag Scatter?)
        # Or just text? Let's do a placeholder or lag plot if we had data?
        # We only passed metrics and turnover_series. 
        # For now, maybe just show the scalar Autocorrelation as a gauge or simple bar?
        # Let's reuse this chart for "Cumulative Wins" or something else useful.
        # Actually, user asked for "Factor Autocorrelation (Line)". 
        # A single number 'autocorrelation' is a scalar. 
        # To show a line we need rolling autocorrelation or autocorrelation structure (lag 1, 2, 3...)
        # Since logic only computes Lag-1 Autocorrelation scalar, we can't show a line chart of it unless we compute rolling.
        # The user req says: "Factor Autocorrelation: Correlation between Factor_t and Factor_t-1"
        # And "Visualization: ... line chart for Factor Autocorrelation."
        # This implies Rolling Autocorrelation.
        # I should probably add rolling autocorrelation to calculation or just plot a flat line?
        # Let's assume the user might want Rolling AutoCorr. 
        # I will update the chart to show "Autocorrelation" text for now as we don't have the series passed in yet.
        # Update: I will check if I can pass rolling autocorrelation series from engine.
        
        self.autocorr_figure.clear()
        ax2 = self.autocorr_figure.add_subplot(111)
        # Placeholder for now until we decide to calc rolling AC
        val = metrics.get('autocorrelation', 0)
        ax2.bar(['Lag-1 Autocorr'], [val], color='#2196F3', width=0.3)
        ax2.set_ylim(-1, 1)
        ax2.set_title(f'Factor Autocorrelation: {val:.3f}')
        ax2.grid(True, alpha=0.3)
        self.autocorr_canvas.draw()
        
    def update_all_charts(self, result):
        """
        Convenience method to update all charts from result dict.
        
        Args:
            result: Dict with analysis results
        """
        from PyQt6.QtWidgets import QApplication
        
        # IC Analysis
        ic_series = result.get('ic_series')
        self.update_ic_analysis(ic_series)
        QApplication.processEvents()
        
        # IC Decay
        ic_decay = result.get('ic_decay')
        self.update_ic_decay(ic_decay)
        QApplication.processEvents()
        
        # Quantile Analysis
        quantile_rets = result.get('quantile_returns')
        quantile_cum = result.get('quantile_cum_ret') # Fixed key
        self.update_quantile_analysis(quantile_rets, quantile_cum)
        QApplication.processEvents()
        
        # Risk Analysis
        corr_matrix = result.get('risk_correlation_matrix') # Fixed key
        self.update_risk_analysis(corr_matrix)
        QApplication.processEvents()

        # Stability Analysis (New)
        prof_metrics = result.get('professional_metrics', {})
        turnover_ts = prof_metrics.get('turnover_series', [])
        self.update_stability_analysis(prof_metrics, turnover_ts)
        QApplication.processEvents()
