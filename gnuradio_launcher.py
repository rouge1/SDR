#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from PyQt5 import Qt
from PyQt5.QtWidgets import QMainWindow, QWidget, QGridLayout, QPushButton, QLabel, QApplication
from PyQt5.QtCore import Qt as QtCore
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
        self.create_app_button("AM Sine Generator", "amSineGenerator", grid, 1, 0)
        self.create_app_button("ASK Generator", "askGenerator", grid, 1, 1)
        # Add more buttons here for future applications
        
    def create_app_button(self, name, module_name, grid, row, col):
        btn = QPushButton(name)
        btn.setMinimumSize(200, 100)
        btn.setFont(Qt.QFont('Arial', 12))
        btn.clicked.connect(lambda: self.launch_application(module_name))
        grid.addWidget(btn, row, col)
        
    def launch_application(self, module_name):
        try:
            # Import the module
            spec = importlib.util.spec_from_file_location(
                module_name, f"{module_name}.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Hide launcher and start the GNU Radio application
            self.hide()
            module.main(app=self.app)
            
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