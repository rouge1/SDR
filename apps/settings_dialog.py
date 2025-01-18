#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
from PyQt5 import Qt
from PyQt5.QtWidgets import QDialog, QGroupBox, QHBoxLayout, QVBoxLayout, QPushButton, QLineEdit, QListWidget, QFileDialog

class SettingsDialog(QDialog):
    def __init__(self, settings_file, parent=None):
        super().__init__(parent)
        self.settings_file = settings_file
        self.setWindowTitle("Settings")
        self.setMinimumSize(800, 400)
        self.resize(900,400)
        
        # Load existing settings
        self.settings = self.load_settings()
        
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
        
        # IP Addresses Section
        ip_group = QGroupBox("IP Addresses")
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
        self.ip_list.addItems(self.settings.get('ip_addresses', []))
        
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
        ip = self.ip_input.text().strip()
        if ip and ip not in [self.ip_list.item(i).text() for i in range(self.ip_list.count())]:
            self.ip_list.addItem(ip)
            self.ip_input.clear()
    
    def remove_ip(self):
        for item in self.ip_list.selectedItems():
            self.ip_list.takeItem(self.ip_list.row(item))
    
    def load_settings(self):
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading settings: {e}")
        return {'media_directory': '', 'ip_addresses': []}
    
    def accept(self):
        # Save settings before closing
        settings = {
            'media_directory': self.media_path.text(),
            'ip_addresses': [self.ip_list.item(i).text() 
                           for i in range(self.ip_list.count())]
        }
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f)
        except Exception as e:
            print(f"Error saving settings: {e}")
        
        super().accept()
