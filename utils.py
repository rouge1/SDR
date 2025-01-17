from PyQt5 import Qt  #type: ignore


#This function is called to apply the theme to the launcher
def apply_launcher_theme(widget):
    stylesheet = """
    QMainWindow {
        background-color: #2e2e2e;
    }
    QLabel {
        color: #ffffff;
    }
    QPushButton {
        background-color: #4b4b4b;
        color: #ffffff;
        border: 2px solid #5c5c5c;
        border-radius: 10px;
        padding: 0px;  /* Remove padding to allow icon to fill */
    }
    QPushButton:hover {
        background-color: #656565;
        border: 2px solid #767676;
    }
    QPushButton:pressed {
        background-color: #3d3d3d;
        border: 2px solid #4e4e4e;
    }
    QMessageBox {
        background-color: #2e2e2e;
        color: #ffffff;
    }
    """
    widget.setStyleSheet(stylesheet)

#This function is called to apply the theme to the dialog
def apply_dark_theme(widget):
    # Set minimum dialog size
    if isinstance(widget, Qt.QDialog):
        widget.setMinimumWidth(350)
        widget.setMinimumHeight(400)
    
    stylesheet = """
    QDialog, QWidget {
        background-color: #2e2e2e;
        color: #ffffff;
    }
    QLabel {
        color: #ffffff;
        margin-top: 10px;  /* Add spacing above labels */
    }
    QPushButton {
        background-color: #4b4b4b;
        color: #ffffff;
        border: 2px solid #5c5c5c;
        border-radius: 5px;
        padding: 5px;
        min-width: 80px;
    }
    QPushButton:hover {
        background-color: #656565;
        border: 2px solid #767676;
    }
    QPushButton:pressed {
        background-color: #3d3d3d;
        border: 2px solid #4e4e4e;
    }
    QComboBox {
        background-color: #4b4b4b;
        color: #ffffff;
        border: 2px solid #5c5c5c;
        border-radius: 5px;
        padding: 5px;
        margin: 5px 0px;  /* Add vertical spacing */
    }
    QComboBox:hover {
        background-color: #656565;
        border: 2px solid #767676;
    }
    QComboBox QAbstractItemView {
        background-color: #4b4b4b;
        color: #ffffff;
        selection-background-color: #656565;
    }
    QSlider {
        background-color: transparent;
        margin: 15px 0px;  /* Add more vertical spacing around sliders */
    }
    QSlider::groove:horizontal {
        background-color: #4b4b4b;
        height: 8px;
        border-radius: 4px;
    }
    QSlider::handle:horizontal {
        background-color: #ffffff;
        border: none;
        width: 16px;
        margin: -4px 0;
        border-radius: 8px;
    }
    QSlider::handle:horizontal:hover {
        background-color: #dddddd;
    }
    QHBoxLayout {
        margin: 10px 0px;  /* Add spacing around horizontal layouts */
    }
    QVBoxLayout {
        margin: 10px 0px;  /* Add spacing around vertical layouts */
    }
    """
    widget.setStyleSheet(stylesheet)
