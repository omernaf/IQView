import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QLabel, QFrame
from PyQt6.QtCore import Qt, QRectF
from .themes import get_palette

class MultiRowSpectrogramView(QWidget):
    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # Scroll Area to hold stacked row plots
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("background: transparent; border: none;")
        
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(10, 10, 10, 10)
        self.scroll_layout.setSpacing(15)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.scroll_area.setWidget(self.scroll_content)
        self.main_layout.addWidget(self.scroll_area)
        
        self.rows = []
        self._block_sync = False
        
        # Cache variables
        self.rate = 1.0
        self.fc = 0.0
        self.start_samples = 0
        self.samples_per_row = 1000
        self.period = 1000

    def apply_levels_and_colormap(self):
        """Applies the current colormap and level settings from the parent's spectrogram view."""
        if not hasattr(self.parent_window, 'spectrogram_view'):
            return
        spec_view = self.parent_window.spectrogram_view
        if not hasattr(spec_view, 'gradient'):
            return
            
        colormap = spec_view.gradient.colorMap()
        low, high = spec_view.level_region.getRegion()
        
        for row in self.rows:
            row['img'].setColorMap(colormap)
            row['img'].setLevels([low, high])

    def update_spectrograms(self, spectrograms, rate, fc, start_samples, samples_per_row, period):
        """
        spectrograms: list of 2D numpy arrays.
        """
        self._block_sync = True
        try:
            self.rate = rate
            self.fc = fc
            self.start_samples = start_samples
            self.samples_per_row = samples_per_row
            self.period = period
            
            num_rows = len(spectrograms)
            if num_rows == 0:
                return
                
            is_waterfall = bool(self.parent_window.settings_mgr.get("ui/waterfall", False))
            theme = self.parent_window.settings_mgr.get("ui/theme", "Dark")
            p = get_palette(theme)
            
            # 1. Adjust row count in our pool
            while len(self.rows) < num_rows:
                row_frame = QFrame()
                row_frame.setObjectName("spec_row_frame")
                row_frame.setStyleSheet(f"QFrame#spec_row_frame {{ background: {p.bg_sidebar}; border: 1px solid {p.border}; border-radius: 4px; }}")
                row_layout = QVBoxLayout(row_frame)
                row_layout.setContentsMargins(5, 5, 5, 5)
                row_layout.setSpacing(2)
                
                label = QLabel()
                label.setStyleSheet("color: #e0e0e0; font-family: 'Segoe UI', sans-serif; font-size: 11px; font-weight: bold; border: none; background: transparent;")
                
                plot_widget = pg.PlotWidget()
                plot_widget.setBackground(p.bg_widget)
                plot_widget.setMenuEnabled(False)
                plot_widget.setMouseEnabled(x=True, y=True) # allow zooming
                
                img = pg.ImageItem()
                img.setZValue(-100)
                plot_widget.addItem(img)
                
                row_layout.addWidget(label)
                row_layout.addWidget(plot_widget)
                self.scroll_layout.addWidget(row_frame)
                
                # Connect range changes
                plot_widget.getViewBox().sigRangeChanged.connect(self._on_row_range_changed)
                
                self.rows.append({
                    'frame': row_frame,
                    'label': label,
                    'plot': plot_widget,
                    'img': img
                })
                
            while len(self.rows) > num_rows:
                row_data = self.rows.pop()
                self.scroll_layout.removeWidget(row_data['frame'])
                row_data['frame'].deleteLater()
                
            # 2. Show and style row plots
            for i, row in enumerate(self.rows):
                row['frame'].show()
                row['plot'].setMinimumHeight(180)
                
                # Apply color themes to axes
                row['plot'].getAxis('bottom').setPen(p.text_dim)
                row['plot'].getAxis('left').setPen(p.text_dim)
                row['plot'].getAxis('bottom').setTextPen(p.text_dim)
                row['plot'].getAxis('left').setTextPen(p.text_dim)
                row['frame'].setStyleSheet(f"QFrame#spec_row_frame {{ background: {p.bg_sidebar}; border: 1px solid {p.border}; border-radius: 4px; }}")
                row['plot'].setBackground(p.bg_widget)

            # 3. Update individual row content
            for i, spec in enumerate(spectrograms):
                row = self.rows[i]
                
                t_row_start = (start_samples + i * period) / rate
                t_row_end = (start_samples + i * period + samples_per_row) / rate
                t_duration = t_row_end - t_row_start
                
                if num_rows > 1:
                    row['label'].setText(f"Row {i+1}: Samples {start_samples + i * period:,} - {start_samples + i * period + samples_per_row:,} ({t_row_start:.6f} s - {t_row_end:.6f} s)")
                    row['label'].show()
                else:
                    row['label'].hide()
                    
                f_min = fc - rate / 2
                f_max = fc + rate / 2
                f_span = f_max - f_min
                
                # Waterfall coordinate alignment and range set
                if is_waterfall:
                    row['img'].setRect(QRectF(f_min, t_row_start, f_span, t_duration))
                    row['plot'].setRange(xRange=[f_min, f_max], yRange=[t_row_start, t_row_end], padding=0)
                    row['plot'].getAxis('bottom').setLabel('Frequency', units='Hz')
                    row['plot'].getAxis('left').setLabel('Time', units='s')
                else:
                    row['img'].setRect(QRectF(t_row_start, f_min, t_duration, f_span))
                    row['plot'].setRange(xRange=[t_row_start, t_row_end], yRange=[f_min, f_max], padding=0)
                    row['plot'].getAxis('bottom').setLabel('Time', units='s')
                    row['plot'].getAxis('left').setLabel('Frequency', units='Hz')
                    
                if is_waterfall:
                    row['img'].setImage(spec.T, autoLevels=False)
                else:
                    row['img'].setImage(spec, autoLevels=False)
                    
            # 4. Sync colormap and levels
            self.apply_levels_and_colormap()
        finally:
            self._block_sync = False

    def _on_row_range_changed(self):
        """Relative time zoom/pan and absolute frequency synchronization."""
        if self._block_sync or len(self.rows) == 0:
            return
            
        self._block_sync = True
        try:
            # Find the sender viewbox/plot
            sender = self.sender()
            trigger_idx = -1
            for i, r in enumerate(self.rows):
                if r['plot'].getViewBox() is sender or r['plot'] is sender:
                    trigger_idx = i
                    break
                    
            if trigger_idx != -1:
                is_waterfall = bool(self.parent_window.settings_mgr.get("ui/waterfall", False))
                
                # Fetch trigger range coordinates
                tr = self.rows[trigger_idx]['plot'].viewRange()
                if is_waterfall:
                    f_min_curr, f_max_curr = tr[0]
                    t_min_curr, t_max_curr = tr[1]
                else:
                    t_min_curr, t_max_curr = tr[0]
                    f_min_curr, f_max_curr = tr[1]
                    
                # Calculate relative percentage offsets
                t_k_start = (self.start_samples + trigger_idx * self.period) / self.rate
                t_k_span = self.samples_per_row / self.rate
                
                pct_start = (t_min_curr - t_k_start) / t_k_span if t_k_span > 0 else 0.0
                pct_end = (t_max_curr - t_k_start) / t_k_span if t_k_span > 0 else 1.0
                
                # Propagate proportionally to all row plots
                for i, r in enumerate(self.rows):
                    t_i_start = (self.start_samples + i * self.period) / self.rate
                    t_i_span = self.samples_per_row / self.rate
                    
                    t_i_min = t_i_start + pct_start * t_i_span
                    t_i_max = t_i_start + pct_end * t_i_span
                    
                    if is_waterfall:
                        r['plot'].setRange(xRange=[f_min_curr, f_max_curr], yRange=[t_i_min, t_i_max], padding=0)
                    else:
                        r['plot'].setRange(xRange=[t_i_min, t_i_max], yRange=[f_min_curr, f_max_curr], padding=0)
                        
                # Update the sidebar input fields
                if hasattr(self.parent_window, 'sidebar'):
                    start_s = int(round(self.start_samples + pct_start * self.samples_per_row))
                    width_s = int(round((pct_end - pct_start) * self.samples_per_row))
                    self.parent_window.sidebar.update_multirow_fields(start_s, width_s, f_min_curr, f_max_curr)
        finally:
            self._block_sync = False
