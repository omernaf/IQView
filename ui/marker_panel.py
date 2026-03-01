from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QLineEdit, QCheckBox
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

class MarkerPanel(QFrame):
    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.setup_ui()

    def setup_ui(self):
        self.setStyleSheet("""
            QFrame { 
                background-color: #1e1e1e; 
                border: 1px solid #444; 
                border-radius: 6px; 
                padding: 4px; 
            }
            QLabel { 
                color: #DDD; 
            }
            QLineEdit {
                background-color: #111;
                color: #FFF;
                border: 1px solid #555;
                padding: 2px;
                border-radius: 2px;
            }
        """)
        self.grid = QGridLayout(self)
        self.grid.setSpacing(8)
        
        header_font = QFont("Inter", 9, QFont.Weight.Bold)
        mono_font = QFont("Courier New", 10)

        # Table Headers (Columns)
        self.grid.addWidget(QLabel(""), 0, 0)
        col_headers = ["Marker 1", "Marker 2", "Delta (Δ)", "Center"]
        for col, text in enumerate(col_headers):
            h = QLabel(text)
            h.setFont(header_font)
            h.setStyleSheet("color: #AAA;")
            h.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(h, 0, col + 1)

        # Row Labels
        r1_label = QLabel("Time (sec)")
        r2_label = QLabel("Samples")
        r1_label.setFont(header_font)
        r2_label.setFont(header_font)
        self.grid.addWidget(r1_label, 1, 0)
        self.grid.addWidget(r2_label, 2, 0)

        # Edit Widgets
        self.widgets = []
        for i in range(2):
            sec_edit = QLineEdit()
            sec_edit.setFixedWidth(150)
            sec_edit.setFont(mono_font)
            sec_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sec_edit.setObjectName(f"m{i}_sec")
            
            sam_edit = QLineEdit()
            sam_edit.setFixedWidth(150)
            sam_edit.setFont(mono_font)
            sam_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sam_edit.setObjectName(f"m{i}_sam")
            
            sec_edit.returnPressed.connect(self.parent_window.marker_edit_finished)
            sam_edit.returnPressed.connect(self.parent_window.marker_edit_finished)
            
            self.grid.addWidget(sec_edit, 1, i + 1)
            self.grid.addWidget(sam_edit, 2, i + 1)
            self.widgets.append({'sec': sec_edit, 'sam': sam_edit})

        # Delta Edits
        self.delta_sec = QLineEdit()
        self.delta_sec.setFixedWidth(150)
        self.delta_sec.setFont(mono_font)
        self.delta_sec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delta_sec.setObjectName("delta_sec")
        self.delta_sec.returnPressed.connect(self.parent_window.marker_edit_finished)
        self.grid.addWidget(self.delta_sec, 1, 3)

        self.delta_sam = QLineEdit()
        self.delta_sam.setFixedWidth(150)
        self.delta_sam.setFont(mono_font)
        self.delta_sam.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.delta_sam.setObjectName("delta_sam")
        self.delta_sam.returnPressed.connect(self.parent_window.marker_edit_finished)
        self.grid.addWidget(self.delta_sam, 2, 3)

        # Center Edits
        self.center_sec = QLineEdit()
        self.center_sec.setFixedWidth(150)
        self.center_sec.setFont(mono_font)
        self.center_sec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_sec.setObjectName("center_sec")
        self.center_sec.returnPressed.connect(self.parent_window.marker_edit_finished)
        self.grid.addWidget(self.center_sec, 1, 4)

        self.center_sam = QLineEdit()
        self.center_sam.setFixedWidth(150)
        self.center_sam.setFont(mono_font)
        self.center_sam.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_sam.setObjectName("center_sam")
        self.center_sam.returnPressed.connect(self.parent_window.marker_edit_finished)
        self.grid.addWidget(self.center_sam, 2, 4)

        # Lock Row
        lock_label = QLabel("Lock State")
        lock_label.setFont(header_font)
        self.grid.addWidget(lock_label, 3, 0)
        
        self.lock_delta_cb = QCheckBox("Lock Delta (Δ)")
        self.lock_center_cb = QCheckBox("Lock Center")
        self.lock_delta_cb.setStyleSheet("color: #DDD;")
        self.lock_center_cb.setStyleSheet("color: #DDD;")
        
        self.lock_delta_cb.toggled.connect(lambda checked: self.parent_window.handle_lock_change('delta', checked))
        self.lock_center_cb.toggled.connect(lambda checked: self.parent_window.handle_lock_change('center', checked))
        
        self.grid.addWidget(self.lock_delta_cb, 3, 3)
        self.grid.addWidget(self.lock_center_cb, 3, 4)
