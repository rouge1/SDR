#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from PyQt5 import Qt
from PyQt5.QtWidgets import QMainWindow, QWidget, QGridLayout, QPushButton, QLabel, QApplication
from PyQt5.QtCore import Qt as QtCore, QSize
from PyQt5.QtGui import QIcon
from utils import apply_launcher_theme
import importlib.util

class GNURadioLauncher(QMainWindow):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app  # Store reference to QApplication
        self.setWindowTitle("GNU Radio Applications Launcher")
        self.setMinimumSize(800, 600)
        
        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        grid = QGridLayout(main_widget)
        
        # Add title
        title = QLabel("GNU Radio Applications")
        title.setFont(Qt.QFont('Arial', 20))
        title.setAlignment(QtCore.AlignCenter)
        grid.addWidget(title, 0, 0, 1, 3)
        
        # Add application buttons
        self.create_app_button("AM Sine Generator", "amSineGenerator", "amSine.jpg", grid, 1, 0)
        self.create_app_button("AM Audio Generator", "amAudioInternalGeneratorLive", "amAudio.jpg", grid, 1, 1)
        self.create_app_button("ASK Generator", "askGenerator", "ask.jpg", grid, 1, 2)
        self.create_app_button("FSK Signal Generator", "fskGenerator", "fsk.jpg", grid, 1, 3)
        self.create_app_button("PSK Signal Generator", "pskGenerator", "psk.jpg", grid, 1, 4)
        self.create_app_button("NTSC Analog Video", "ntscAnalogVideoRecorded", "ntsc.jpg", grid, 2, 0)
        
        # Apply stylesheet
        apply_launcher_theme(self)

    def create_app_button(self, name, module_name, icon_name, grid, row, col):
        # Create container widget for button and label
        container = QWidget()
        container_layout = Qt.QVBoxLayout(container)
        container_layout.setSpacing(5)
        container_layout.setAlignment(QtCore.AlignCenter)
        
        # Create square button
        btn = QPushButton()
        size = 200  # Square size
        btn.setFixedSize(size, size)
        btn.setFont(Qt.QFont('Arial', 12))
        
        # Set the button icon to fill the button
        icon_path = f"icons/{icon_name}"
        btn.setIcon(QIcon(icon_path))
        btn.setIconSize(QSize(size - 20, size - 20))
        
        # Create label below button
        label = QLabel(name)
        label.setFont(Qt.QFont('Arial', 12))
        label.setAlignment(QtCore.AlignCenter)
        label.setWordWrap(True)
        label.setFixedWidth(size)
        
        # Add widgets to container
        container_layout.addWidget(btn)
        container_layout.addWidget(label)
        
        btn.clicked.connect(lambda: self.launch_application(module_name))
        grid.addWidget(container, row, col, QtCore.AlignCenter)
        
    def launch_application(self, module_name):
        try:
            # Import the module
            spec = importlib.util.spec_from_file_location(
                module_name, f"{module_name}.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Create configuration dialog
            config_dialog = module.ConfigDialog()
            
            # Show dialog and wait for user response
            if config_dialog.exec_() == Qt.QDialog.Accepted:
                # Get configuration values
                config_values = config_dialog.get_values()
                
                # Hide launcher
                self.hide()
                
                # Start the GNU Radio application with configuration
                tb = module.main(app=self.app, config_values=config_values)
                
                # Connect close event to show launcher again
                if hasattr(tb, 'closeEvent'):
                    original_close_event = tb.closeEvent
                    def new_close_event(event):
                        original_close_event(event)
                        self.show()
                    tb.closeEvent = new_close_event
                
            # If user clicks Cancel, launcher stays visible and nothing happens
            
        except Exception as e:
            error_dialog = Qt.QMessageBox()
            error_dialog.setIcon(Qt.QMessageBox.Critical)
            error_dialog.setText(f"Error launching {module_name}")
            error_dialog.setInformativeText(str(e))
            error_dialog.setWindowTitle("Error")
            error_dialog.exec_()

if __name__ == '__main__':
    app = Qt.QApplication.instance()
    if not app:
        app = Qt.QApplication(sys.argv)
    
    launcher = GNURadioLauncher(app)
    launcher.show()
    sys.exit(app.exec_())