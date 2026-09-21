"""PyQt6 Tab 1: Shelf Designer view with metadata, dynamic row slot editors, and 2D visualizer."""

from __future__ import annotations

from typing import Callable
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from mapper.common import clean_location_segment, make_slot_name


class ShelfVisualizerWidget(QScrollArea):
    """2D interactive visualizer for the shelf rows and slots."""

    slot_clicked = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setStyleSheet("background-color: #ffffff; border: 1px solid #d1d5db; border-radius: 4px;")

        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(16, 16, 16, 16)
        self.container_layout.setSpacing(6)
        self.setWidget(self.container)

        self.selected_slot: str | None = None
        self.slot_buttons: dict[str, QPushButton] = {}

    def clear(self, message: str = "Build or load a shelf to preview layout."):
        # Clear children
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.slot_buttons.clear()

        placeholder = QLabel(message)
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: #6b7280; font-size: 13px; padding: 40px;")
        self.container_layout.addWidget(placeholder)

    def render_shelf(
        self,
        floor: str,
        side: str,
        shelf_code: str,
        layout: list[int],
        slot_counts: dict[str, tuple[int, int]] | None = None,
        selected_slot: str | None = None,
    ):
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.slot_buttons.clear()
        self.selected_slot = selected_slot

        if not layout:
            self.clear()
            return

        slot_counts = slot_counts or {}

        # Header Title
        title_lbl = QLabel(f"FLOOR {floor.upper()}  —  SIDE {side.upper()}  —  SHELF {shelf_code.upper()}")
        title_lbl.setStyleSheet("font-weight: 700; font-size: 15px; color: #1f2328; margin-bottom: 6px;")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.container_layout.addWidget(title_lbl)

        sub_lbl = QLabel("CELLS — numbered across each row (Row 1 is at ground level)")
        sub_lbl.setStyleSheet("color: #6b7280; font-size: 11px; margin-bottom: 12px;")
        sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.container_layout.addWidget(sub_lbl)

        # Draw rows from top row down to Row 1
        for row_number in range(len(layout), 0, -1):
            count = layout[row_number - 1]
            row_frame = QFrame()
            row_frame.setStyleSheet("background-color: #f7f8fa; border: 1px solid #e5e7eb; border-radius: 4px;")
            row_layout = QHBoxLayout(row_frame)
            row_layout.setContentsMargins(8, 6, 8, 6)
            row_layout.setSpacing(6)

            row_lbl = QLabel(f"Row {row_number}" + (" (Ground)" if row_number == 1 else ""))
            row_lbl.setFixedWidth(85)
            row_lbl.setStyleSheet("font-weight: 600; color: #374151; font-size: 12px;")
            row_layout.addWidget(row_lbl)

            for slot_index in range(1, count + 1):
                slot_name = make_slot_name(floor, shelf_code, row_number, slot_index, side=side)
                saved_count, staged_count = slot_counts.get(slot_name, (0, 0))

                btn = QPushButton(f"S{slot_index}")
                btn.setFixedHeight(36)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)

                # Colors based on state
                is_selected = slot_name == self.selected_slot
                if is_selected:
                    bg = "#3574f0"
                    fg = "#ffffff"
                    border = "#1d4ed8"
                elif staged_count:
                    bg = "#fff2b2"
                    fg = "#1f2328"
                    border = "#eab308"
                elif saved_count:
                    bg = "#d9ead3"
                    fg = "#1f2328"
                    border = "#86efac"
                else:
                    bg = "#ffffff"
                    fg = "#1f2328"
                    border = "#d1d5db"

                btn.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {bg};
                        color: {fg};
                        border: 1px solid {border};
                        border-radius: 3px;
                        font-family: 'JetBrains Mono', monospace;
                        font-weight: 500;
                        font-size: 11px;
                        padding: 2px 4px;
                    }}
                    QPushButton:hover {{
                        border: 1px solid #3574f0;
                    }}
                """)

                badge_text = f"S{slot_index}"
                if staged_count:
                    badge_text += f" (+{staged_count})"
                elif saved_count:
                    badge_text += f" ({saved_count})"
                btn.setText(badge_text)

                btn.clicked.connect(lambda checked, s=slot_name: self._on_slot_click(s))
                self.slot_buttons[slot_name] = btn
                row_layout.addWidget(btn)

            row_layout.addStretch()
            self.container_layout.addWidget(row_frame)

        self.container_layout.addStretch()

    def _on_slot_click(self, slot_name: str):
        self.selected_slot = slot_name
        self.slot_clicked.emit(slot_name)


class ShelfDesignerView(QWidget):
    """Tab 1: Shelf Designer with toolbar, metadata, row editor, and 2D visualizer."""

    def __init__(
        self,
        parent: QWidget | None,
        on_build: Callable[[], bool],
        can_resize: Callable[[int], bool],
        on_commit: Callable[[], None],
        on_new_shelf: Callable[[], None],
        on_load_shelf: Callable[[], None],
        on_import_csv: Callable[[], None],
        on_import_catalog_csv: Callable[[], None],
    ):
        super().__init__(parent)
        self.on_build = on_build
        self.can_resize = can_resize
        self.on_commit = on_commit
        self.on_new_shelf = on_new_shelf
        self.on_load_shelf = on_load_shelf
        self.on_import_csv = on_import_csv
        self.on_import_catalog_csv = on_import_catalog_csv

        self.row_spinboxes: list[QSpinBox] = []

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(10)

        # 1. Top Action Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.import_csv_btn = QPushButton("Import working products CSV")
        self.import_csv_btn.clicked.connect(self.on_import_csv)
        toolbar.addWidget(self.import_csv_btn)

        self.import_catalog_btn = QPushButton("Import full catalog CSV")
        self.import_catalog_btn.clicked.connect(self.on_import_catalog_csv)
        toolbar.addWidget(self.import_catalog_btn)

        toolbar.addSpacing(12)

        self.new_shelf_btn = QPushButton("New shelf")
        self.new_shelf_btn.clicked.connect(self.on_new_shelf)
        toolbar.addWidget(self.new_shelf_btn)

        toolbar.addWidget(QLabel("Edit existing shelf:"))
        self.shelf_selector = QComboBox()
        self.shelf_selector.setFixedWidth(240)
        toolbar.addWidget(self.shelf_selector)

        self.load_shelf_btn = QPushButton("Load for editing")
        self.load_shelf_btn.clicked.connect(self.on_load_shelf)
        toolbar.addWidget(self.load_shelf_btn)

        toolbar.addStretch()

        self.commit_btn = QPushButton("Commit shelf design")
        self.commit_btn.setProperty("primary", "true")
        self.commit_btn.setFixedHeight(30)
        self.commit_btn.clicked.connect(self.on_commit)
        toolbar.addWidget(self.commit_btn)

        main_layout.addLayout(toolbar)

        # 2. Main Content Splitter (Left: Controls & Rows, Right: 2D Visualizer)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        # Metadata Box
        meta_box = QGroupBox("Shelf metadata")
        meta_layout = QGridLayout(meta_box)
        meta_layout.setContentsMargins(12, 16, 12, 12)
        meta_layout.setSpacing(8)

        meta_layout.addWidget(QLabel("Floor:"), 0, 0)
        self.floor_input = QLineEdit("1")
        self.floor_input.setFixedWidth(80)
        meta_layout.addWidget(self.floor_input, 0, 1)

        meta_layout.addWidget(QLabel("Side:"), 0, 2)
        self.side_input = QLineEdit("1")
        self.side_input.setFixedWidth(60)
        meta_layout.addWidget(self.side_input, 0, 3)

        meta_layout.addWidget(QLabel("Shelf code:"), 1, 0)
        self.shelf_code_input = QLineEdit("A")
        self.shelf_code_input.setFixedWidth(80)
        meta_layout.addWidget(self.shelf_code_input, 1, 1)

        meta_layout.addWidget(QLabel("Number of rows:"), 1, 2)
        self.row_count_spin = QSpinBox()
        self.row_count_spin.setRange(1, 100)
        self.row_count_spin.setValue(3)
        self.row_count_spin.setFixedWidth(60)
        self.row_count_spin.valueChanged.connect(self._on_row_count_changed)
        meta_layout.addWidget(self.row_count_spin, 1, 3)

        btn_row = QHBoxLayout()
        self.apply_rows_btn = QPushButton("Apply row count")
        self.apply_rows_btn.clicked.connect(self._apply_row_count)
        btn_row.addWidget(self.apply_rows_btn)

        self.build_btn = QPushButton("Build / refresh 2D shelf")
        self.build_btn.setProperty("primary", "true")
        self.build_btn.clicked.connect(self.on_build)
        btn_row.addWidget(self.build_btn)
        btn_row.addStretch()

        meta_layout.addLayout(btn_row, 2, 0, 1, 4)

        info_lbl = QLabel("Row 1 is at ground level. New rows are added at the top.\nLocation example: L1-1A8-10.")
        info_lbl.setStyleSheet("color: #6b7280; font-size: 11px;")
        meta_layout.addWidget(info_lbl, 3, 0, 1, 4)

        left_layout.addWidget(meta_box)

        # Rows Editor Box
        rows_box = QGroupBox("Rows — front view (slot counts)")
        rows_layout = QVBoxLayout(rows_box)
        rows_layout.setContentsMargins(12, 16, 12, 12)
        rows_layout.setSpacing(8)

        row_ctrls = QHBoxLayout()
        add_row_btn = QPushButton("Add row at top")
        add_row_btn.clicked.connect(self._add_row)
        row_ctrls.addWidget(add_row_btn)

        rem_row_btn = QPushButton("Remove top row")
        rem_row_btn.clicked.connect(self._remove_top_row)
        row_ctrls.addWidget(rem_row_btn)
        row_ctrls.addStretch()
        rows_layout.addLayout(row_ctrls)

        # Scroll area for rows
        self.rows_scroll = QScrollArea()
        self.rows_scroll.setWidgetResizable(True)
        self.rows_scroll_container = QWidget()
        self.rows_scroll_layout = QVBoxLayout(self.rows_scroll_container)
        self.rows_scroll_layout.setContentsMargins(6, 6, 6, 6)
        self.rows_scroll_layout.setSpacing(6)
        self.rows_scroll.setWidget(self.rows_scroll_container)
        rows_layout.addWidget(self.rows_scroll)

        left_layout.addWidget(rows_box)
        splitter.addWidget(left_panel)

        # Right Panel: 2D Visualizer
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        vis_box = QGroupBox("2D Shelf Visualizer")
        vis_layout = QVBoxLayout(vis_box)
        vis_layout.setContentsMargins(8, 16, 8, 8)
        self.visualizer = ShelfVisualizerWidget()
        vis_layout.addWidget(self.visualizer)

        right_layout.addWidget(vis_box)
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        main_layout.addWidget(splitter)

        self._rebuild_row_inputs()

    def _on_row_count_changed(self, count: int):
        self._apply_row_count()

    def _apply_row_count(self):
        target = self.row_count_spin.value()
        current = len(self.row_spinboxes)
        if target < current and not self.can_resize(target):
            self.row_count_spin.blockSignals(True)
            self.row_count_spin.setValue(current)
            self.row_count_spin.blockSignals(False)
            return
        self._rebuild_row_inputs(target)

    def _add_row(self):
        self.row_count_spin.setValue(len(self.row_spinboxes) + 1)

    def _remove_top_row(self):
        if len(self.row_spinboxes) > 1:
            self.row_count_spin.setValue(len(self.row_spinboxes) - 1)

    def _rebuild_row_inputs(self, count: int | None = None, default_layout: list[int] | None = None):
        target_count = count if count is not None else self.row_count_spin.value()
        while self.rows_scroll_layout.count():
            item = self.rows_scroll_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        # Capture old values
        old_values = [spin.value() for spin in self.row_spinboxes]
        self.row_spinboxes.clear()

        # Create spinboxes for rows 1 to target_count (storage is bottom-up)
        for row_idx in range(target_count):
            spin = QSpinBox()
            spin.setRange(1, 100)
            if default_layout and row_idx < len(default_layout):
                spin.setValue(default_layout[row_idx])
            elif row_idx < len(old_values):
                spin.setValue(old_values[row_idx])
            else:
                spin.setValue(10)
            spin.setFixedWidth(70)
            self.row_spinboxes.append(spin)

        # Display rows from Top down to Row 1
        for row_number in range(target_count, 0, -1):
            row_idx = row_number - 1
            row_widget = QWidget()
            h = QHBoxLayout(row_widget)
            h.setContentsMargins(4, 2, 4, 2)

            lbl = QLabel(f"Row {row_number}:" + (" (Ground)" if row_number == 1 else ""))
            lbl.setFixedWidth(100)
            lbl.setStyleSheet("font-weight: 500;")
            h.addWidget(lbl)

            h.addWidget(self.row_spinboxes[row_idx])
            h.addWidget(QLabel("slots"))
            h.addStretch()

            self.rows_scroll_layout.addWidget(row_widget)

        self.rows_scroll_layout.addStretch()

    def set_metadata(self, floor: str, side: str, shelf_code: str, layout: list[int]):
        self.floor_input.setText(str(floor))
        self.side_input.setText(str(side))
        self.shelf_code_input.setText(str(shelf_code))
        self.row_count_spin.blockSignals(True)
        self.row_count_spin.setValue(len(layout))
        self.row_count_spin.blockSignals(False)
        self._rebuild_row_inputs(len(layout), default_layout=layout)

    def validated_layout(self) -> tuple[str, str, str, list[int]] | None:
        floor = clean_location_segment(self.floor_input.text())
        side = clean_location_segment(self.side_input.text())
        shelf_code = clean_location_segment(self.shelf_code_input.text()).upper()

        if not floor or not side or not shelf_code:
            QMessageBox.warning(self, "Missing Metadata", "Floor, Side, and Shelf code are required.")
            return None

        layout = [spin.value() for spin in self.row_spinboxes]
        if not layout:
            QMessageBox.warning(self, "Invalid Layout", "At least one row is required.")
            return None

        return floor, side, shelf_code, layout
