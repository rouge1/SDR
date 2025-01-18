#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import re
from PyQt5.QtWidgets import QDialog, QGroupBox, QHBoxLayout, QVBoxLayout, QPushButton, QLineEdit, QListWidget, QFileDialog, QMessageBox, QRadioButton # type: ignore

class SettingsDialog(QDialog):
    def __init__(self, settings_file, parent=None):
        super().__init__(parent)
        self.settings_file = settings_file
        self.setWindowTitle("Settings")
        self.setMinimumSize(500, 400)
        self.resize(500, 400)
        
        # Load existing settings
        self.settings = self.load_settings()
        
        # Ensure ip_addresses exists in settings
        if 'ip_addresses' not in self.settings:
            self.settings['ip_addresses'] = []
            
        layout = QVBoxLayout(self)
        
        # Media Directory Section
        media_group = QGroupBox("Media Directory")
        media_layout = QHBoxLayout()
        self.media_path = QLineEdit(self.settings.get('media_directory', ''))
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.browse_media_dir)
        media_layout.addWidget(self.media_path)
        media_layout.addWidget(browse_btn)
        media_group.setLayout(media_layout)
        
        # Add Radio Mode Section (after media_group)
        mode_group = QGroupBox("GNUradio Launcher Mode")
        mode_layout = QHBoxLayout()
        self.single_mode = QRadioButton("Single")
        self.multi_mode = QRadioButton("Multi")
        
        # Set default or load saved mode
        current_mode = self.settings.get('radio_mode', 'single')
        self.single_mode.setChecked(current_mode == 'single')
        self.multi_mode.setChecked(current_mode == 'multi')
        
        # Connect mode change handlers
        self.single_mode.clicked.connect(self.validate_mode)
        self.multi_mode.clicked.connect(self.validate_mode)
        
        mode_layout.addWidget(self.single_mode)
        mode_layout.addWidget(self.multi_mode)
        mode_group.setLayout(mode_layout)
        
        # IP Addresses Section
        ip_group = QGroupBox("Software Defined Radio IP Addresses:")
        ip_layout = QVBoxLayout()
        
        # IP input and add button
        ip_input_layout = QHBoxLayout()
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("Enter IP address")
        add_ip_btn = QPushButton("Add")
        add_ip_btn.clicked.connect(self.add_ip)
        ip_input_layout.addWidget(self.ip_input)
        ip_input_layout.addWidget(add_ip_btn)
        
        # IP list
        self.ip_list = QListWidget()
        self.ip_list.addItems(self.settings['ip_addresses'])  # Now safe since we initialized it
        
        # Remove IP button
        remove_ip_btn = QPushButton("Remove Selected")
        remove_ip_btn.clicked.connect(self.remove_ip)
        
        ip_layout.addLayout(ip_input_layout)
        ip_layout.addWidget(self.ip_list)
        ip_layout.addWidget(remove_ip_btn)
        ip_group.setLayout(ip_layout)
        
        # Add groups to main layout
        layout.addWidget(media_group)
        layout.addWidget(ip_group)
        layout.addWidget(mode_group)
        
        # Add Save/Cancel buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        save_btn = QPushButton("Save")
        cancel_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self.accept)
        
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(save_btn)
        layout.addLayout(button_layout)
    
    def browse_media_dir(self):
        directory = QFileDialog.getExistingDirectory(
            self, "Select Media Directory",
            self.media_path.text(),
            QFileDialog.ShowDirsOnly
        )
        if directory:
            self.media_path.setText(directory)
    
    def add_ip(self):
        ip_address = self.ip_input.text().strip()
        if self.validate_ip(ip_address):
            if ip_address not in self.settings['ip_addresses']:  # Check for duplicates
                self.ip_list.addItem(ip_address)
                self.settings['ip_addresses'].append(ip_address)
                self.ip_input.clear()
            else:
                QMessageBox.warning(self, "Duplicate IP", "This IP address is already in the list.")
        else:
            QMessageBox.warning(self, "Invalid IP", "The IP address entered is invalid.")
    
    def validate_ip(self, ip):
        # Check if IP address has 4 octets
        octets = ip.split('.')
        if len(octets) != 4:
            return False
        
        # Check if each octet is a number between 0 and 255
        for octet in octets:
            if not octet.isdigit() or not 0 <= int(octet) <= 255:
                return False
        
        # Check if IP address is forbidden
        if ip == "0.0.0.0" or ip == "255.255.255.255":
            return False
        
        return True
    
    def remove_ip(self):
        for item in self.ip_list.selectedItems():
            ip_address = item.text()
            self.settings['ip_addresses'].remove(ip_address)  # Remove from settings
            self.ip_list.takeItem(self.ip_list.row(item))
    
    def load_settings(self):
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading settings: {e}")
        return {'media_directory': '', 'ip_addresses': []}  # Initialize with empty list
    
    def validate_mode(self):
        if self.multi_mode.isChecked() and len(self.settings['ip_addresses']) < 2:
            QMessageBox.warning(self, "Invalid Mode", 
                              "Multi mode requires at least 2 IP addresses.")
            self.single_mode.setChecked(True)
            return False
        return True

    def accept(self):
        if not self.validate_mode():
            return
            
        existing_settings = {}
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    existing_settings = json.load(f)
        except Exception as e:
            print(f"Error loading existing settings: {e}")

        existing_settings.update({
            'media_directory': self.media_path.text(),
            'ip_addresses': self.settings['ip_addresses'],
            'radio_mode': 'multi' if self.multi_mode.isChecked() else 'single'
        })

        # Save the combined settings
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(existing_settings, f)
        except Exception as e:
            print(f"Error saving settings: {e}")
        
        super().accept()