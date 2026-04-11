from PyQt6.QtGui import QColor

class Palette:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

DARK_PALETTE = Palette(
    bg_main="#121212",
    bg_sidebar="#1a1a1a",
    bg_widget="#252525",
    bg_input="#1a1a1a",
    bg_tab_inactive="#1a1a1a",
    text_main="#e0e0e0",
    text_dim="#9e9e9e",
    text_header="#ffffff",
    accent="#00aaff",
    accent_dim="#004488",
    border="#333333",
    border_light="#444444",
    plot_bg="#121212",
    plot_grid="#333333",
    marker_time="#00ff00",
    marker_freq="#ffaa00",
    marker_mag="#ffaa00"
)

LIGHT_PALETTE = Palette(
    bg_main="#f5f5f5",
    bg_sidebar="#ffffff",
    bg_widget="#e8e8e8",
    bg_input="#ffffff",
    bg_tab_inactive="#e0e0e0",
    text_main="#222222",
    text_dim="#555555",
    text_header="#000000",
    accent="#0077cc",
    accent_dim="#cceeff",
    border="#cccccc",
    border_light="#dddddd",
    plot_bg="#ffffff",
    plot_grid="#eeeeee",
    marker_time="#008800",
    marker_freq="#cc6600",
    marker_mag="#cc6600"
)

def get_palette(theme_name):
    return LIGHT_PALETTE if theme_name == "Light" else DARK_PALETTE

def get_main_stylesheet(theme_name):
    p = get_palette(theme_name)
    return f"""
        QMainWindow, QWidget#central, QDialog {{ 
            background-color: {p.bg_main}; 
            color: {p.text_main}; 
            font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif; 
        }}
        QToolTip {{ 
            background-color: {p.bg_widget}; 
            color: {p.text_main}; 
            border: 1px solid {p.accent_dim}; 
            padding: 4px;
        }}
        QLabel {{ color: {p.text_dim}; }}
        QPushButton {{ 
            background-color: {p.bg_widget}; 
            color: {p.text_main}; 
            border: 1px solid {p.border}; 
            border-radius: 4px; padding: 6px 12px; font-size: 13px; 
        }}
        QPushButton:hover {{ background-color: {p.border_light}; }}
        QPushButton:checked {{ 
            background-color: {p.accent_dim}; 
            border-color: {p.accent}; 
            color: {p.accent}; 
        }}
        QPushButton[is_reset="true"] {{
            padding: 4px;
            font-size: 14px;
        }}
        QLineEdit {{ 
            background-color: {p.bg_input}; 
            color: {p.text_main}; 
            border: 1px solid {p.border}; 
            border-radius: 4px; padding: 4px 8px; 
        }}
        QLineEdit:focus {{ border-color: {p.accent}; }}
        QLineEdit[readOnly="true"] {{ color: {p.text_dim}; background-color: {p.bg_widget}; }}
        
        QComboBox {{ 
            background-color: {p.bg_input}; 
            color: {p.text_main}; 
            border: 1px solid {p.border}; 
            border-radius: 4px; padding: 4px 8px; 
        }}
        QComboBox::drop-down {{ border: none; width: 20px; }}
        
        /* Force the popup dropdown list to be fully opaque and hide background */
        QComboBox QAbstractItemView, QComboBox QListView, QComboBox QAbstractItemView::viewport {{ 
            background-color: {p.bg_input}; 
            qproperty-autoFillBackground: true;
            color: {p.text_main}; 
            selection-background-color: {p.accent_dim}; 
            selection-color: {p.accent};
            border: 1px solid {p.border};
            outline: none;
        }}
        QComboBox::item {{
            background-color: {p.bg_input};
            color: {p.text_main};
        }}
        
        QTabWidget::pane {{ border: 1px solid {p.border}; top: -1px; background-color: {p.bg_main}; }}
        QTabBar::tab {{ 
            background-color: {p.bg_tab_inactive}; color: {p.text_dim}; padding: 8px 20px; 
            border: 1px solid {p.border}; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px;
            margin-right: 2px; font-size: 12px; font-weight: bold;
        }}
        QTabBar::tab:hover {{ background-color: {p.bg_widget}; color: {p.text_main}; }}
        QTabBar::tab:selected {{ 
            background-color: {p.bg_main}; color: {p.accent}; 
            border-bottom: 2px solid {p.accent}; 
        }}

        QCheckBox {{ 
            color: {p.text_main};
            spacing: 8px;
        }}
        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
            background-color: {p.bg_input};
            border: 1px solid {p.border};
            border-radius: 3px;
        }}
        QCheckBox::indicator:checked {{
            background-color: {p.accent};
            border-color: {p.accent};
        }}
        QCheckBox::indicator:hover {{
            border-color: {p.accent};
        }}

        QListWidget, QTableWidget {{
            background-color: {p.bg_input};
            border: 1px solid {p.border};
            color: {p.text_main};
            gridline-color: {p.border};
            border-radius: 4px;
        }}
        QListWidget::item, QTableWidget::item {{ 
            padding: 4px 8px; 
            color: {p.text_main};
        }}
        QListWidget::item:selected, QTableWidget::item:selected {{ 
            background-color: {p.accent_dim}; 
            color: {p.accent}; 
        }}
        
        QHeaderView::section {{
            background-color: {p.bg_widget};
            color: {p.text_main};
            padding: 6px;
            border: 1px solid {p.border};
            font-weight: bold;
        }}
        QTableCornerButton::section {{
            background-color: {p.bg_widget};
            border: 1px solid {p.border};
        }}

        {get_scrollbar_stylesheet(p)}
    """

def get_scrollbar_stylesheet(p):
    return f"""
        QScrollBar:horizontal {{
            background: {p.bg_main};
            height: 10px;
            margin: 0px;
            border: none;
        }}
        QScrollBar::handle:horizontal {{
            background: {p.border_light};
            min-width: 40px;
            border-radius: 5px;
            margin: 2px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {p.accent};
        }}
        
        QScrollBar:vertical {{
            background: {p.bg_main};
            width: 10px;
            margin: 0px;
            border: none;
        }}
        QScrollBar::handle:vertical {{
            background: {p.border_light};
            min-height: 40px;
            border-radius: 5px;
            margin: 2px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {p.accent};
        }}
        
        QScrollBar::add-line, QScrollBar::sub-line {{
            width: 0px; height: 0px;
        }}
        QScrollBar::add-page, QScrollBar::sub-page {{
            background: none;
        }}
    """
