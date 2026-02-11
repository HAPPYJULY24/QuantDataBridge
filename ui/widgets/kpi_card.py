
from PyQt6.QtWidgets import (QFrame, QVBoxLayout, QLabel, QMenu)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction

class KPICard(QFrame):
    """
    Enhanced KPI Card for Risk Dashboard.
    Supports dynamic coloring and click interactions for detailed breakdown.
    """
    clicked = pyqtSignal()

    def __init__(self, title, value="--", tooltip_text="", is_interactive=False):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)
        self.is_interactive = is_interactive
        self.breakdown_data = {}

        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)

        self.title_lbl = QLabel(title.upper())
        self.title_lbl.setStyleSheet("color: #AAAAAA; font-size: 10px; font-weight: bold;")
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_lbl)

        self.value_lbl = QLabel(str(value))
        self.value_lbl.setStyleSheet("color: white; font-size: 18px; font-weight: bold;")
        self.value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.value_lbl)

        self.setLayout(layout)
        self.setToolTip(tooltip_text)
        
        self.setStyleSheet("""
            KPICard {
                background-color: #2D2D2D;
                border-radius: 8px;
                border: 1px solid #3D3D3D;
            }
            KPICard:hover {
                background-color: #383838;
                border: 1px solid #555555;
            }
        """)

    def update_value(self, value, metric_type=None):
        """
        Update value with conditional coloring logic.
        metric_type: 'calmar', 'mdd_duration', 'block_rate', etc.
        """
        display_val = value
        color = "white"

        if metric_type == 'calmar':
            try:
                val = float(str(value).replace(',', ''))
                display_val = f"{val:.2f}"
                if val < 1.0: color = "#FF9800"  # Orange
                elif val > 2.0: color = "#4CAF50" # Green
            except: pass
            
        elif metric_type == 'mdd_duration':
            try:
                # Value expected as "X days" or int
                val = int(str(value).split()[0])
                display_val = f"{val} days"
                if val > 14: color = "#FF5252" # Red
            except: pass
            
        elif metric_type == 'recovery_factor':
            try:
                val = float(str(value))
                display_val = f"{val:.2f}"
                if val > 5: color = "#4CAF50"
            except: pass

        self.value_lbl.setText(str(display_val))
        self.value_lbl.setStyleSheet(f"color: {color}; font-size: 18px; font-weight: bold;")

    def set_breakdown(self, data: dict):
        """Set data for breakdown popup (e.g., ADX: 10, Margin: 5)"""
        self.breakdown_data = data
        if self.is_interactive and data:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            
    def mousePressEvent(self, event):
        if self.is_interactive and self.breakdown_data:
            self.show_breakdown_menu(event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def show_breakdown_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #2D2D2D; border: 1px solid #555; coloe: white; }
            QMenu::item { padding: 5px 20px; color: white; }
            QMenu::item:selected { background-color: #3D3D3D; }
        """)
        
        title_action = QAction("🛑 Block Breakdown", self)
        title_action.setEnabled(False)
        menu.addAction(title_action)
        menu.addSeparator()
        
        for k, v in self.breakdown_data.items():
            menu.addAction(f"{k}: {v}")
            
        menu.exec(pos)
