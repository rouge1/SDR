#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Standard library imports
import sys
import os
import json
import importlib.util

# Third party imports
from PyQt5.QtWidgets import ( # type: ignore
    QMainWindow, 
    QWidget, 
    QGridLayout, 
    QPushButton, 
    QLabel, 
    QApplication,
    QVBoxLayout,
    QDialog,
    QMessageBox
)
from PyQt5.QtCore import Qt, QSize, QPoint # type: ignore
from PyQt5.QtGui import QIcon, QPixmap, QFont # type: ignore

# Add PIL import at the top with other imports
from PIL import Image, ImageEnhance # type: ignore
import io

# Local imports 
from apps.utils import apply_launcher_theme, apply_dark_theme
from apps.settings_dialog import SettingsDialog

class GNURadioLauncher(QMainWindow):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app  # Store reference to QApplication
        self.setWindowTitle("GNU Radio Applications Launcher")
        self.setMinimumSize(800, 600)
        
        # Create config directory if it doesn't exist
        self.config_dir = "config"
        self.settings_file = os.path.join(self.config_dir, "window_settings.json")
        os.makedirs(self.config_dir, exist_ok=True)
        
        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        grid = QGridLayout(main_widget)
        
        # Add settings button in top right with transparent background
        settings_btn = QPushButton()
        icon_path = "icons/settings.png"
        
        # Process image with PIL
        img = Image.open(icon_path)
        img = img.convert("RGBA")
        
        # Add brightness enhancement
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(1.1)  # Adjust this value to make it brighter/darker
        
        datas = img.getdata()
        new_data = []
        threshold = 100
        
        for item in datas:
            if item[0] >= threshold and item[1] >= threshold and item[2] >= threshold:
                new_data.append((255, 255, 255, 0))
            else:
                new_data.append(item)
        
        img.putdata(new_data)
        
        # Convert PIL image to QPixmap
        buffer = io.BytesIO()
        img.save(buffer, "PNG")
        buffer.seek(0)
        pixmap = QPixmap()
        pixmap.loadFromData(buffer.getvalue())
        
        icon = QIcon(pixmap)
        settings_btn.setIcon(icon)
        settings_btn.setFixedSize(40, 40)
        settings_btn.setIconSize(QSize(40, 40))
        settings_btn.clicked.connect(self.show_settings)
        grid.addWidget(settings_btn, 0, 4, Qt.AlignRight | Qt.AlignTop)
        
        # Add title
        title = QLabel("GNU Radio Applications")
        title.setFont(QFont('Arial', 20))
        title.setAlignment(Qt.AlignCenter)
        grid.addWidget(title, 0, 0, 1, 3)
        
        # Add application buttons
        self.create_app_button("AM Sine Generator", "amSineGenerator", "amSine.jpg", grid, 1, 0)
        self.create_app_button("ASK Generator", "askGenerator", "ask.jpg", grid, 1, 1)
        self.create_app_button("FSK Signal Generator", "fskGenerator", "fsk.jpg", grid, 1, 2)
        self.create_app_button("PSK Signal Generator", "pskGenerator", "psk.jpg", grid, 1, 3)
        self.create_app_button("PPM-OOK Generator", "ppmookAudioXmitter", "ppm-ook.png", grid, 1, 4)
        # Audio
        self.create_app_button("AM Audio Generator", "amAudioInternalGeneratorLive", "amAudio.jpg", grid, 2, 0)
        self.create_app_button("FM Audio Generator", "fmAudioRecordedGenerator", "fmAudio.png", grid, 2, 1)
        self.create_app_button("FM Subcarrier", "subcarrierRecordedAudio", "fmSubcarrier.jpg", grid, 2, 2)
        
        # Video
        self.create_app_button("ATSC Transmitter", "atscXmitter", "atsc.jpg", grid, 3, 0)
        self.create_app_button("NTSC Analog Video", "ntscAnalogVideoRecorded", "ntsc.jpg", grid, 3, 1)
        self.create_app_button("AM Video Transmitter", "amVideoRecordedXmitter", "amVideo.jpg", grid, 3, 2)
        
        # Apply stylesheet
        apply_launcher_theme(self)
        
        # Load last position or center if none exists
        self.load_window_position()
        
    def center_window(self):
        """Center the window on the screen and save position"""
        # Get the screen geometry
        screen = self.app.primaryScreen().geometry()
        # Calculate center position
        window_geometry = self.frameGeometry()
        center_point = screen.center()
        window_geometry.moveCenter(center_point)
        self.move(window_geometry.topLeft())
        
        # Save position to config file
        self.save_window_position()
        
    def save_window_position(self):
        """Save the current window position to settings file"""
        try:
            # Load existing settings
            settings = {}
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
            
            # Update window position
            settings['window_position'] = {
                'x': self.pos().x(),
                'y': self.pos().y()
            }
            
            # Save updated settings
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f)
        except Exception as e:
            print(f"Error saving window position: {e}")
            
    def load_window_position(self):
        """Load the saved window position from settings file or center if none exists"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                    if 'window_position' in settings:
                        position = settings['window_position']
                        # Validate position is on screen
                        screen = self.app.primaryScreen().geometry()
                        if (0 <= position['x'] <= screen.width() - self.width() and 
                            0 <= position['y'] <= screen.height() - self.height()):
                            self.move(QPoint(position['x'], position['y']))
                        else:
                            self.center_window()
                    else:
                        self.center_window()
            else:
                self.center_window()
        except Exception as e:
            print(f"Error loading window position: {e}")
            self.center_window()

    def create_app_button(self, name, module_name, icon_name, grid, row, col):
        # Create button
        btn = QPushButton()
        size = 200  # Square size
        btn.setFixedSize(size, size)
        
        # Create a widget to hold the icon and text vertically
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setSpacing(5)
        layout.setAlignment(Qt.AlignCenter)
        
        # Create label for icon
        icon_label = QLabel()
        icon_path = f"icons/{icon_name}"
        icon = QIcon(icon_path)
        pixmap = icon.pixmap(QSize(size - 0, size - 0))  # Slightly smaller to accommodate text
        icon_label.setPixmap(pixmap)
        icon_label.setAlignment(Qt.AlignCenter)
        
        # Create label for text
        text_label = QLabel(name)
        text_label.setFont(QFont('Arial', 11))
        text_label.setAlignment(Qt.AlignCenter)
        text_label.setWordWrap(True)
        
        # Add widgets to layout
        layout.addWidget(icon_label)
        layout.addWidget(text_label)
        
        # Set the content widget as the button's layout
        btn.setLayout(layout)
        
        # Connect click event
        btn.clicked.connect(lambda: self.launch_application(module_name))
        
        # Add button to grid
        grid.addWidget(btn, row, col, Qt.AlignCenter)
        
    def launch_application(self, module_name):
        try:
            # Import the module
            module_path = os.path.join('apps', f"{module_name}.py")
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Create configuration dialog (no need to pass parameters)
            config_dialog = module.ConfigDialog()
            
            # Load saved dialog position from settings file
            screen = self.app.primaryScreen().geometry()
            default_pos = self.pos() + QPoint(50, 50)

            try:
                if os.path.exists(self.settings_file):
                    with open(self.settings_file, 'r') as f:
                        settings = json.load(f)
                        if 'dialog_position' in settings:
                            position = settings['dialog_position']
                            
                            # Check if position is within screen bounds
                            valid_position = (
                                0 <= position['x'] <= screen.width() - config_dialog.width() and 
                                0 <= position['y'] <= screen.height() - config_dialog.height()
                            )
                            
                            if valid_position:
                                config_dialog.move(QPoint(position['x'], position['y']))
                            else:
                                config_dialog.move(default_pos)
                        else:
                            config_dialog.move(default_pos)
                else:
                    config_dialog.move(default_pos)
            except Exception as e:
                print(f"Error loading dialog position: {e}")
                config_dialog.move(default_pos)

            # Show dialog and wait for user response
            result = config_dialog.exec_()
            
            # Save dialog position to settings file
            try:
                settings = {}
                if os.path.exists(self.settings_file):
                    with open(self.settings_file, 'r') as f:
                        settings = json.load(f)
                
                # Save the actual geometry position
                geo = config_dialog.geometry()
                settings['dialog_position'] = {
                    'x': geo.x(),
                    'y': geo.y()
                }
                
                with open(self.settings_file, 'w') as f:
                    json.dump(settings, f)
            except Exception as e:
                print(f"Error saving dialog position: {e}")

            if result == QDialog.Accepted:
                config_values = config_dialog.get_values()
                
                # Load radio mode setting
                radio_mode = 'single'
                try:
                    if os.path.exists(self.settings_file):
                        with open(self.settings_file, 'r') as f:
                            settings = json.load(f)
                            radio_mode = settings.get('radio_mode', 'single')
                except Exception as e:
                    print(f"Error loading radio mode setting: {e}")

                # Only hide launcher in single mode
                if radio_mode == 'single':
                    self.save_window_position()
                    self.hide()
                
                # Start the GNU Radio application
                tb = module.main(app=self.app, config_values=config_values)
                
                # Modify close event only in single mode
                if radio_mode == 'single' and hasattr(tb, 'closeEvent'):
                    original_close_event = tb.closeEvent
                    def new_close_event(event):
                        original_close_event(event)
                        self.load_window_position()
                        self.show()
                    tb.closeEvent = new_close_event

        except Exception as e:
            error_dialog = QMessageBox()
            error_dialog.setIcon(QMessageBox.Critical)
            error_dialog.setText(f"Error launching {module_name}")
            error_dialog.setInformativeText(str(e))
            error_dialog.setWindowTitle("Error")
            error_dialog.exec_()

    def show_settings(self):
        settings_dialog = SettingsDialog(self.settings_file, parent=self)
        apply_dark_theme(settings_dialog)
        settings_dialog.exec_()

    def closeEvent(self, event):
        """Save window position when closing the application"""
        self.save_window_position()
        super().closeEvent(event)

if __name__ == '__main__':
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    
    launcher = GNURadioLauncher(app)
    launcher.show()
    sys.exit(app.exec_())