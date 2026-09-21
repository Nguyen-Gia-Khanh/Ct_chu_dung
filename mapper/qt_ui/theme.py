"""IntelliJ IDEA inspired QSS stylesheet for native PyQt6 desktop UI."""

INTELLI_J_STYLESHEET = """
/* Global Window & Font Settings */
QWidget {
    background-color: #f7f8fa;
    color: #1f2328;
    font-family: 'Inter', 'Segoe UI', sans-serif;
    font-size: 13px;
    selection-background-color: #2670e8;
    selection-color: #ffffff;
}

/* Group Boxes & Panels */
QGroupBox {
    background-color: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    margin-top: 18px;
    padding-top: 14px;
    padding-left: 8px;
    padding-right: 8px;
    padding-bottom: 8px;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: #374151;
    background-color: #f7f8fa;
}

/* Tabs */
QTabWidget::pane {
    border: 1px solid #d1d5db;
    background-color: #ffffff;
    border-radius: 0 0 6px 6px;
}

QTabBar::tab {
    background-color: #f0f2f5;
    color: #4b5563;
    padding: 8px 18px;
    border-top: 1px solid #d1d5db;
    border-left: 1px solid #d1d5db;
    border-right: 1px solid #d1d5db;
    border-bottom: 1px solid #d1d5db;
    margin-right: 2px;
    font-weight: 500;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}

QTabBar::tab:selected {
    background-color: #ffffff;
    color: #1f2328;
    border-bottom: 2px solid #3574f0;
    font-weight: 600;
}

QTabBar::tab:hover:!selected {
    background-color: #e5e7eb;
    color: #1f2328;
}

/* Buttons */
QPushButton {
    background-color: #ffffff;
    color: #1f2328;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    padding: 5px 12px;
    font-weight: 500;
    min-height: 20px;
}

QPushButton:hover {
    background-color: #f3f4f6;
    border-color: #9ca3af;
}

QPushButton:pressed {
    background-color: #e5e7eb;
    border-color: #6b7280;
}

QPushButton:disabled {
    background-color: #f3f4f6;
    color: #9ca3af;
    border-color: #e5e7eb;
}

/* Primary Action Buttons */
QPushButton[primary="true"] {
    background-color: #3574f0;
    color: #ffffff;
    border: 1px solid #2a65d8;
    font-weight: 600;
}

QPushButton[primary="true"]:hover {
    background-color: #2c62cc;
    border-color: #2351a8;
}

QPushButton[primary="true"]:pressed {
    background-color: #2451a8;
    border-color: #1d428a;
}

/* Danger Buttons */
QPushButton[danger="true"] {
    background-color: #ffffff;
    color: #cf222e;
    border: 1px solid #d1d5db;
}

QPushButton[danger="true"]:hover {
    background-color: #ffebe9;
    border-color: #ff8182;
}

/* Inputs & Comboboxes */
QLineEdit, QSpinBox, QComboBox {
    background-color: #ffffff;
    color: #1f2328;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    padding: 4px 8px;
    min-height: 20px;
}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #3574f0;
    background-color: #ffffff;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #1f2328;
    border: 1px solid #d1d5db;
    selection-background-color: #3574f0;
    selection-color: #ffffff;
    padding: 4px;
}

/* Tables */
QTableWidget, QTableView {
    background-color: #ffffff;
    alternate-background-color: #fafbfc;
    color: #1f2328;
    border: 1px solid #d1d5db;
    gridline-color: #f0f2f5;
    selection-background-color: #dbeafe;
    selection-color: #1e3a8a;
    font-size: 12px;
}

QHeaderView::section {
    background-color: #f7f8fa;
    color: #4b5563;
    padding: 5px 8px;
    border: none;
    border-right: 1px solid #e5e7eb;
    border-bottom: 1px solid #d1d5db;
    font-weight: 600;
    font-size: 12px;
}

QTableCornerButton::section {
    background-color: #f7f8fa;
    border: none;
    border-bottom: 1px solid #d1d5db;
}

/* Splitters */
QSplitter::handle {
    background-color: #e5e7eb;
}

QSplitter::handle:horizontal {
    width: 3px;
}

QSplitter::handle:vertical {
    height: 3px;
}

QSplitter::handle:hover {
    background-color: #3574f0;
}

/* Scrollbars */
QScrollBar:vertical {
    background-color: #f7f8fa;
    width: 10px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background-color: #d1d5db;
    border-radius: 5px;
    min-height: 24px;
    margin: 2px;
}

QScrollBar::handle:vertical:hover {
    background-color: #9ca3af;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background-color: #f7f8fa;
    height: 10px;
    margin: 0px;
}

QScrollBar::handle:horizontal {
    background-color: #d1d5db;
    border-radius: 5px;
    min-width: 24px;
    margin: 2px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #9ca3af;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* Status Bar */
QStatusBar {
    background-color: #f0f2f5;
    border-top: 1px solid #d1d5db;
    color: #4b5563;
    font-size: 12px;
    padding: 2px 10px;
}

QStatusBar::item {
    border: none;
}

/* Badges & Chips */
QLabel[chip="true"] {
    background-color: #e5e7eb;
    color: #374151;
    border-radius: 3px;
    padding: 2px 6px;
    font-size: 11px;
    font-weight: 600;
}

QLabel[chip-primary="true"] {
    background-color: #dbeafe;
    color: #1d4ed8;
    border-radius: 3px;
    padding: 2px 6px;
    font-size: 11px;
    font-weight: 600;
}

QLabel[chip-warning="true"] {
    background-color: #fef3c7;
    color: #92400e;
    border-radius: 3px;
    padding: 2px 6px;
    font-size: 11px;
    font-weight: 600;
}

QLabel[chip-success="true"] {
    background-color: #d1fae5;
    color: #065f46;
    border-radius: 3px;
    padding: 2px 6px;
    font-size: 11px;
    font-weight: 600;
}

/* Monospace text */
QLabel[mono="true"], QLineEdit[mono="true"] {
    font-family: 'JetBrains Mono', 'Consolas', monospace;
}
"""
