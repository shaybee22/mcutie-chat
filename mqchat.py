#!/usr/bin/env python3
"""
Mcutie Chat by James Powell
A simple encrypted group chat using MQTT as the relay server
FINAL VERSION - Anti-spam join detection
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog
import paho.mqtt.client as mqtt
import json
import base64
import hashlib
import time
import threading
import os
from datetime import datetime
from cryptography.fernet import Fernet

class SecureMQTTChat:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Mcutie Chat by James Powell")
        self.root.geometry("900x800")
        
        # MQTT and crypto variables
        self.mqtt_client = None
        self.cipher = None
        self.connected = False
        self.username = ""
        self.channel = ""
        self.encryption_key = ""
        
        # Topics
        self.messages_topic = ""
        self.presence_topic = ""
        self.userlist_topic = ""
        
        # User tracking
        self.online_users = set()
        self.heartbeat_timer = None
        self.recent_joins = {}  # Track recent joins to prevent spam
        
        # Room management
        self.config_file = "mqtt_chat_rooms.json"
        self.config_cipher = None
        self.saved_rooms = {}
        
        self.setup_gui()
        self.load_saved_rooms()
        
    def clear_my_presence(self):
        """Clear our own presence message to prevent duplicates"""
        if self.mqtt_client and self.username:
            self.mqtt_client.publish(f"{self.presence_topic}/{self.username}", "", retain=True)

    def force_clean_users(self):
        """Force clean the users list by removing duplicates"""
        # Convert to list, remove duplicates, convert back to set
        unique_users = list(set(self.online_users))
        self.online_users = set(unique_users)
        self.update_users_list()

    def nuclear_clean_users(self):
        """Nuclear option - completely rebuild user list"""
        print("Nuclear clean - rebuilding user list")
        self.online_users.clear()
        self.online_users.add(self.username)  # Add ourselves back
        self.update_users_list()
        
    def clear_connection_fields(self):
        """Clear all connection fields"""
        self.server_entry.delete(0, tk.END)
        self.server_entry.insert(0, "localhost")
        
        self.port_entry.delete(0, tk.END)
        self.port_entry.insert(0, "1883")
        
        self.channel_entry.delete(0, tk.END)
        self.channel_entry.insert(0, "general")
        
        self.username_entry.delete(0, tk.END)
        
        self.mqtt_username_entry.delete(0, tk.END)
        self.mqtt_password_entry.delete(0, tk.END)
        
        self.key_entry.delete(0, tk.END)
        self.key_entry.insert(0, "supersecretkey123")
        
        # Clear dropdown selection
        self.rooms_var.set("")
        
        self.update_key_display()
        messagebox.showinfo("Cleared", "All fields cleared to defaults!")
        
    def setup_gui(self):
        """Create the GUI layout"""
        # Create notebook for tabs
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Connection tab
        self.connection_frame = ttk.Frame(notebook)
        notebook.add(self.connection_frame, text="Connection")
        self.setup_connection_tab()
        
        # Chat tab
        self.chat_frame = ttk.Frame(notebook)
        notebook.add(self.chat_frame, text="Chat")
        self.setup_chat_tab()
        
        # Room Management tab
        self.rooms_frame = ttk.Frame(notebook)
        notebook.add(self.rooms_frame, text="Saved Rooms")
        self.setup_rooms_tab()
        
    def setup_connection_tab(self):
        """Setup the connection configuration tab"""
        # Title
        title_label = tk.Label(self.connection_frame, text="Mcutie Chat Configuration", 
                              font=("Arial", 16, "bold"))
        title_label.pack(pady=20)
        
        # Quick Load Frame
        quick_frame = tk.LabelFrame(self.connection_frame, text="Quick Connect", 
                                   font=("Arial", 10, "bold"))
        quick_frame.pack(pady=10, padx=20, fill=tk.X)
        
        # Saved rooms dropdown
        rooms_frame = tk.Frame(quick_frame)
        rooms_frame.pack(pady=10)
        
        tk.Label(rooms_frame, text="Saved Rooms:").pack(side=tk.LEFT, padx=5)
        self.rooms_var = tk.StringVar()
        self.rooms_dropdown = ttk.Combobox(rooms_frame, textvariable=self.rooms_var, 
                                          state="readonly", width=25)
        self.rooms_dropdown.pack(side=tk.LEFT, padx=5)
        self.rooms_dropdown.bind('<<ComboboxSelected>>', self.load_room_config)
        
        load_btn = tk.Button(rooms_frame, text="Load Room", command=self.load_room_config,
                           bg="#4CAF50", fg="white")
        load_btn.pack(side=tk.LEFT, padx=5)
        
        # Configuration frame
        config_frame = tk.LabelFrame(self.connection_frame, text="Manual Configuration", 
                                    font=("Arial", 10, "bold"))
        config_frame.pack(pady=10, padx=20, fill=tk.X)
        
        # Create inner frame for grid layout
        inner_config = tk.Frame(config_frame)
        inner_config.pack(pady=10)
        
        # MQTT Server
        tk.Label(inner_config, text="MQTT Server:").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        self.server_entry = tk.Entry(inner_config, width=30)
        self.server_entry.grid(row=0, column=1, padx=5, pady=5)
        self.server_entry.insert(0, "localhost")
        
        # Port
        tk.Label(inner_config, text="Port:").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        self.port_entry = tk.Entry(inner_config, width=30)
        self.port_entry.grid(row=1, column=1, padx=5, pady=5)
        self.port_entry.insert(0, "1883")
        
        # Channel/Room
        tk.Label(inner_config, text="Channel:").grid(row=2, column=0, sticky="e", padx=5, pady=5)
        self.channel_entry = tk.Entry(inner_config, width=30)
        self.channel_entry.grid(row=2, column=1, padx=5, pady=5)
        self.channel_entry.insert(0, "general")
        
        # MQTT Authentication frame
        auth_frame = tk.LabelFrame(inner_config, text="MQTT Authentication (Optional)", 
                                  font=("Arial", 9, "italic"))
        auth_frame.grid(row=3, column=0, columnspan=3, sticky="ew", padx=5, pady=10)
        
        # MQTT Username
        tk.Label(auth_frame, text="MQTT Username:").grid(row=0, column=0, sticky="e", padx=5, pady=3)
        self.mqtt_username_entry = tk.Entry(auth_frame, width=25)
        self.mqtt_username_entry.grid(row=0, column=1, padx=5, pady=3)
        
        # MQTT Password
        tk.Label(auth_frame, text="MQTT Password:").grid(row=1, column=0, sticky="e", padx=5, pady=3)
        self.mqtt_password_entry = tk.Entry(auth_frame, width=25, show="*")
        self.mqtt_password_entry.grid(row=1, column=1, padx=5, pady=3)
        
        # Show MQTT password checkbox
        self.show_mqtt_password_var = tk.BooleanVar()
        show_mqtt_pass_btn = tk.Checkbutton(auth_frame, text="Show Password", 
                                           variable=self.show_mqtt_password_var,
                                           command=self.toggle_mqtt_password_visibility)
        show_mqtt_pass_btn.grid(row=1, column=2, sticky="w", padx=5, pady=3)
        
        # Help text
        help_label = tk.Label(auth_frame, text="Leave blank for anonymous connection", 
                             font=("Arial", 8), fg="gray")
        help_label.grid(row=2, column=0, columnspan=3, pady=3)
        
        # Chat Username
        tk.Label(inner_config, text="Chat Username:").grid(row=4, column=0, sticky="e", padx=5, pady=5)
        self.username_entry = tk.Entry(inner_config, width=30)
        self.username_entry.grid(row=4, column=1, padx=5, pady=5)
        
        # Encryption Key
        tk.Label(inner_config, text="Encryption Key:").grid(row=5, column=0, sticky="e", padx=5, pady=5)
        self.key_entry = tk.Entry(inner_config, width=30, show="*")
        self.key_entry.grid(row=5, column=1, padx=5, pady=5)
        self.key_entry.insert(0, "supersecretkey123")
        
        # Key buttons frame
        key_buttons_frame = tk.Frame(inner_config)
        key_buttons_frame.grid(row=5, column=2, padx=5, pady=5)
        
        # Generate key button
        generate_btn = tk.Button(key_buttons_frame, text="Generate", command=self.generate_key)
        generate_btn.pack(side=tk.TOP, pady=(0, 2))
        
        # Copy key button
        copy_btn = tk.Button(key_buttons_frame, text="Copy Key", command=self.copy_key)
        copy_btn.pack(side=tk.TOP)
        
        # Show/Hide key button
        self.show_key_var = tk.BooleanVar()
        show_key_btn = tk.Checkbutton(inner_config, text="Show Key", variable=self.show_key_var, 
                                     command=self.toggle_key_visibility)
        show_key_btn.grid(row=6, column=1, sticky="w", padx=5, pady=5)
        
        # Key display area (for easy copying)
        tk.Label(inner_config, text="Share this key:").grid(row=7, column=0, sticky="e", padx=5, pady=5)
        self.key_display = tk.Text(inner_config, height=3, width=35, wrap=tk.WORD, state=tk.DISABLED)
        self.key_display.grid(row=7, column=1, padx=5, pady=5)
        self.update_key_display()
        
        # Buttons frame
        buttons_frame = tk.Frame(self.connection_frame)
        buttons_frame.pack(pady=20)
        
        # Save current room button
        save_room_btn = tk.Button(buttons_frame, text="💾 Save Current Room", 
                                 command=self.save_current_room, bg="#2196F3", fg="white",
                                 font=("Arial", 10, "bold"))
        save_room_btn.pack(side=tk.LEFT, padx=5)
        
        # Connect button
        self.connect_btn = tk.Button(buttons_frame, text="🔗 Connect", command=self.connect_mqtt, 
                                   bg="green", fg="white", font=("Arial", 12, "bold"))
        self.connect_btn.pack(side=tk.LEFT, padx=5)
        
        # Clear fields button
        clear_btn = tk.Button(buttons_frame, text="🗑️ Clear Fields", command=self.clear_connection_fields,
                             bg="#FF9800", fg="white", font=("Arial", 10, "bold"))
        clear_btn.pack(side=tk.LEFT, padx=5)
        
        # Status label
        self.status_label = tk.Label(self.connection_frame, text="Not connected", fg="red",
                                   font=("Arial", 10, "bold"))
        self.status_label.pack(pady=10)
        
    def setup_chat_tab(self):
        """Setup the chat interface tab"""
        # Main chat frame
        main_frame = tk.Frame(self.chat_frame)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Chat display frame (left side)
        chat_display_frame = tk.Frame(main_frame)
        chat_display_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Chat header with room name
        self.chat_header = tk.Label(chat_display_frame, text="Chat Messages", 
                                   font=("Arial", 12, "bold"), bg="#E3F2FD", relief=tk.RAISED, pady=5)
        self.chat_header.pack(fill=tk.X, pady=(0, 5))
        
        # Chat messages area
        self.chat_display = scrolledtext.ScrolledText(chat_display_frame, state=tk.DISABLED, 
                                                     wrap=tk.WORD, height=20)
        self.chat_display.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # Message input frame
        input_frame = tk.Frame(chat_display_frame)
        input_frame.pack(fill=tk.X, pady=5)
        
        self.message_entry = tk.Entry(input_frame)
        self.message_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.message_entry.bind("<Return>", self.send_message)
        
        send_btn = tk.Button(input_frame, text="Send", command=self.send_message)
        send_btn.pack(side=tk.RIGHT, padx=(5, 0))
        
        # Users list frame (right side)
        users_frame = tk.Frame(main_frame, width=200)
        users_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        users_frame.pack_propagate(False)
        
        tk.Label(users_frame, text="Online Users", font=("Arial", 12, "bold")).pack()
        self.users_listbox = tk.Listbox(users_frame, width=25)
        self.users_listbox.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # Disconnect button
        disconnect_btn = tk.Button(users_frame, text="Disconnect", command=self.disconnect_mqtt,
                                 bg="red", fg="white")
        disconnect_btn.pack(fill=tk.X, pady=5)
        
        # Add debug button for cleaning users
        debug_btn = tk.Button(users_frame, text="🧹 Clean Users", command=self.force_clean_users,
                             bg="orange", fg="white", font=("Arial", 8))
        debug_btn.pack(fill=tk.X, pady=2)
        
    def setup_rooms_tab(self):
        """Setup the room management tab"""
        title_label = tk.Label(self.rooms_frame, text="Saved Chat Rooms", 
                              font=("Arial", 16, "bold"))
        title_label.pack(pady=20)
        
        # Main container
        main_container = tk.Frame(self.rooms_frame)
        main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Left side - Room list
        left_frame = tk.Frame(main_container)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        tk.Label(left_frame, text="Saved Rooms:", font=("Arial", 12, "bold")).pack(anchor="w")
        
        # Rooms listbox with scrollbar
        listbox_frame = tk.Frame(left_frame)
        listbox_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.rooms_listbox = tk.Listbox(listbox_frame, font=("Arial", 10))
        scrollbar = tk.Scrollbar(listbox_frame, orient=tk.VERTICAL, command=self.rooms_listbox.yview)
        self.rooms_listbox.config(yscrollcommand=scrollbar.set)
        
        self.rooms_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.rooms_listbox.bind('<<ListboxSelect>>', self.on_room_select)
        
        # Buttons frame
        buttons_frame = tk.Frame(left_frame)
        buttons_frame.pack(fill=tk.X, pady=10)
        
        edit_btn = tk.Button(buttons_frame, text="✏️ Edit", command=self.edit_room,
                           bg="#FF9800", fg="white")
        edit_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        delete_btn = tk.Button(buttons_frame, text="🗑️ Delete", command=self.delete_room,
                             bg="#F44336", fg="white")
        delete_btn.pack(side=tk.LEFT, padx=5)
        
        quick_connect_btn = tk.Button(buttons_frame, text="🚀 Quick Connect", 
                                    command=self.quick_connect_room,
                                    bg="#4CAF50", fg="white", font=("Arial", 10, "bold"))
        quick_connect_btn.pack(side=tk.RIGHT)
        
        # Right side - Room details
        right_frame = tk.LabelFrame(main_container, text="Room Details", 
                                   font=("Arial", 10, "bold"))
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(20, 0))
        
        # Room details display
        self.room_details = tk.Text(right_frame, height=15, width=40, wrap=tk.WORD, 
                                   state=tk.DISABLED, font=("Arial", 9))
        self.room_details.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Import/Export buttons
        import_export_frame = tk.Frame(right_frame)
        import_export_frame.pack(fill=tk.X, padx=10, pady=10)
        
        export_btn = tk.Button(import_export_frame, text="📤 Export All", 
                             command=self.export_rooms, bg="#9C27B0", fg="white")
        export_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        import_btn = tk.Button(import_export_frame, text="📥 Import", 
                             command=self.import_rooms, bg="#607D8B", fg="white")
        import_btn.pack(side=tk.LEFT)
        
    def get_config_cipher(self):
        """Get or create cipher for config file encryption"""
        if not self.config_cipher:
            # Use a fixed key for config encryption (in real app, use keyring/OS keystore)
            config_key = self.derive_key("mqtt_chat_config_key_v1")
            self.config_cipher = Fernet(config_key)
        return self.config_cipher
        
    def save_current_room(self):
        """Save current room configuration"""
        server = self.server_entry.get().strip()
        port = self.port_entry.get().strip()
        channel = self.channel_entry.get().strip()
        username = self.username_entry.get().strip()
        key = self.key_entry.get().strip()
        
        if not all([server, port, channel, username, key]):
            messagebox.showerror("Error", "Please fill in all fields before saving")
            return
            
        # Ask for room name
        room_name = simpledialog.askstring("Save Room", "Enter a name for this room:")
        if not room_name:
            return
            
        # Check if room name already exists
        if room_name in self.saved_rooms:
            if not messagebox.askyesno("Overwrite", f"Room '{room_name}' already exists. Overwrite?"):
                return
                
        # Save room config
        self.saved_rooms[room_name] = {
            "server": server,
            "port": port,
            "channel": channel,
            "username": username,
            "encryption_key": key,
            "mqtt_username": self.mqtt_username_entry.get().strip(),
            "mqtt_password": self.mqtt_password_entry.get().strip(),
            "saved_date": datetime.now().isoformat()
        }
        
        self.save_rooms_to_file()
        self.refresh_rooms_display()
        messagebox.showinfo("Saved", f"Room '{room_name}' saved successfully!")
        
    def load_room_config(self, event=None):
        """Load selected room configuration"""
        selected_room = self.rooms_var.get()
        if not selected_room or selected_room not in self.saved_rooms:
            return
            
        config = self.saved_rooms[selected_room]
        
        # Load into connection fields
        self.server_entry.delete(0, tk.END)
        self.server_entry.insert(0, config["server"])
        
        self.port_entry.delete(0, tk.END)
        self.port_entry.insert(0, config["port"])
        
        self.channel_entry.delete(0, tk.END)
        self.channel_entry.insert(0, config["channel"])
        
        self.username_entry.delete(0, tk.END)
        self.username_entry.insert(0, config["username"])
        
        self.key_entry.delete(0, tk.END)
        self.key_entry.insert(0, config["encryption_key"])
        
        # Load MQTT authentication if present
        self.mqtt_username_entry.delete(0, tk.END)
        self.mqtt_username_entry.insert(0, config.get("mqtt_username", ""))
        
        self.mqtt_password_entry.delete(0, tk.END)
        self.mqtt_password_entry.insert(0, config.get("mqtt_password", ""))
        
        self.update_key_display()
        messagebox.showinfo("Loaded", f"Room '{selected_room}' configuration loaded!")
        
    def quick_connect_room(self):
        """Quick connect to selected room from rooms tab"""
        selection = self.rooms_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a room first")
            return
            
        room_name = self.rooms_listbox.get(selection[0])
        
        # Load the room config
        self.rooms_var.set(room_name)
        self.load_room_config()
        
        # Switch to connection tab and connect
        notebook = self.root.children['!notebook']
        notebook.select(0)  # Switch to connection tab
        
        # Connect after a brief delay to allow tab switch
        self.root.after(100, self.connect_mqtt)
        
    def on_room_select(self, event):
        """Handle room selection in rooms list"""
        selection = self.rooms_listbox.curselection()
        if not selection:
            return
            
        room_name = self.rooms_listbox.get(selection[0])
        if room_name in self.saved_rooms:
            self.show_room_details(room_name, self.saved_rooms[room_name])
            
    def show_room_details(self, room_name, config):
        """Show room details in the details panel"""
        details = f"Room Name: {room_name}\n\n"
        details += f"Server: {config['server']}\n"
        details += f"Port: {config['port']}\n"
        details += f"Channel: {config['channel']}\n"
        details += f"Chat Username: {config['username']}\n"
        
        # Show MQTT auth status
        mqtt_user = config.get('mqtt_username', '')
        if mqtt_user:
            details += f"MQTT Username: {mqtt_user}\n"
            details += f"MQTT Password: {'*' * len(config.get('mqtt_password', ''))}\n"
        else:
            details += f"MQTT Auth: Anonymous\n"
            
        details += f"Encryption Key: {'*' * len(config['encryption_key'])}\n\n"
        details += f"Saved: {config.get('saved_date', 'Unknown')}\n"
        
        self.room_details.config(state=tk.NORMAL)
        self.room_details.delete(1.0, tk.END)
        self.room_details.insert(tk.END, details)
        self.room_details.config(state=tk.DISABLED)
        
    def edit_room(self):
        """Edit selected room"""
        selection = self.rooms_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a room to edit")
            return
            
        room_name = self.rooms_listbox.get(selection[0])
        config = self.saved_rooms[room_name]
        
        # Create edit dialog
        edit_window = tk.Toplevel(self.root)
        edit_window.title(f"Edit Room: {room_name}")
        edit_window.geometry("400x300")
        edit_window.transient(self.root)
        edit_window.grab_set()
        
        # Edit form
        tk.Label(edit_window, text="Server:").grid(row=0, column=0, sticky="e", padx=5, pady=5)
        server_entry = tk.Entry(edit_window, width=30)
        server_entry.grid(row=0, column=1, padx=5, pady=5)
        server_entry.insert(0, config["server"])
        
        tk.Label(edit_window, text="Port:").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        port_entry = tk.Entry(edit_window, width=30)
        port_entry.grid(row=1, column=1, padx=5, pady=5)
        port_entry.insert(0, config["port"])
        
        tk.Label(edit_window, text="Channel:").grid(row=2, column=0, sticky="e", padx=5, pady=5)
        channel_entry = tk.Entry(edit_window, width=30)
        channel_entry.grid(row=2, column=1, padx=5, pady=5)
        channel_entry.insert(0, config["channel"])
        
        tk.Label(edit_window, text="Chat Username:").grid(row=3, column=0, sticky="e", padx=5, pady=5)
        username_entry = tk.Entry(edit_window, width=30)
        username_entry.grid(row=3, column=1, padx=5, pady=5)
        username_entry.insert(0, config["username"])
        
        tk.Label(edit_window, text="MQTT Username:").grid(row=4, column=0, sticky="e", padx=5, pady=5)
        mqtt_user_entry = tk.Entry(edit_window, width=30)
        mqtt_user_entry.grid(row=4, column=1, padx=5, pady=5)
        mqtt_user_entry.insert(0, config.get("mqtt_username", ""))
        
        tk.Label(edit_window, text="MQTT Password:").grid(row=5, column=0, sticky="e", padx=5, pady=5)
        mqtt_pass_entry = tk.Entry(edit_window, width=30, show="*")
        mqtt_pass_entry.grid(row=5, column=1, padx=5, pady=5)
        mqtt_pass_entry.insert(0, config.get("mqtt_password", ""))
        
        tk.Label(edit_window, text="Encryption Key:").grid(row=6, column=0, sticky="e", padx=5, pady=5)
        key_entry = tk.Entry(edit_window, width=30)
        key_entry.grid(row=6, column=1, padx=5, pady=5)
        key_entry.insert(0, config["encryption_key"])
        
        def save_changes():
            new_config = {
                "server": server_entry.get().strip(),
                "port": port_entry.get().strip(),
                "channel": channel_entry.get().strip(),
                "username": username_entry.get().strip(),
                "encryption_key": key_entry.get().strip(),
                "mqtt_username": mqtt_user_entry.get().strip(),
                "mqtt_password": mqtt_pass_entry.get().strip(),
                "saved_date": config.get("saved_date", datetime.now().isoformat())
            }
            
            if not all([new_config["server"], new_config["port"], new_config["channel"], 
                       new_config["username"], new_config["encryption_key"]]):
                messagebox.showerror("Error", "Please fill in all fields")
                return
                
            self.saved_rooms[room_name] = new_config
            self.save_rooms_to_file()
            self.refresh_rooms_display()
            edit_window.destroy()
            messagebox.showinfo("Updated", f"Room '{room_name}' updated successfully!")
        
        # Buttons
        button_frame = tk.Frame(edit_window)
        button_frame.grid(row=7, column=0, columnspan=2, pady=20)
        
        tk.Button(button_frame, text="Save Changes", command=save_changes,
                 bg="#4CAF50", fg="white").pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Cancel", command=edit_window.destroy,
                 bg="#F44336", fg="white").pack(side=tk.LEFT, padx=5)
        
    def delete_room(self):
        """Delete selected room"""
        selection = self.rooms_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a room to delete")
            return
            
        room_name = self.rooms_listbox.get(selection[0])
        
        if messagebox.askyesno("Delete Room", f"Are you sure you want to delete room '{room_name}'?"):
            del self.saved_rooms[room_name]
            self.save_rooms_to_file()
            self.refresh_rooms_display()
            messagebox.showinfo("Deleted", f"Room '{room_name}' deleted successfully!")
            
    def export_rooms(self):
        """Export all rooms to a file"""
        if not self.saved_rooms:
            messagebox.showwarning("No Rooms", "No rooms to export")
            return
            
        from tkinter import filedialog
        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Export Rooms"
        )
        
        if filename:
            try:
                with open(filename, 'w') as f:
                    json.dump(self.saved_rooms, f, indent=2)
                messagebox.showinfo("Exported", f"Rooms exported to {filename}")
            except Exception as e:
                messagebox.showerror("Export Error", f"Failed to export: {str(e)}")
                
    def import_rooms(self):
        """Import rooms from a file"""
        from tkinter import filedialog
        filename = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Import Rooms"
        )
        
        if filename:
            try:
                with open(filename, 'r') as f:
                    imported_rooms = json.load(f)
                
                # Merge with existing rooms
                conflicts = []
                for room_name in imported_rooms:
                    if room_name in self.saved_rooms:
                        conflicts.append(room_name)
                
                if conflicts:
                    message = f"The following rooms already exist:\n{', '.join(conflicts)}\n\nOverwrite them?"
                    if not messagebox.askyesno("Import Conflicts", message):
                        return
                
                self.saved_rooms.update(imported_rooms)
                self.save_rooms_to_file()
                self.refresh_rooms_display()
                messagebox.showinfo("Imported", f"Successfully imported {len(imported_rooms)} room(s)")
                
            except Exception as e:
                messagebox.showerror("Import Error", f"Failed to import: {str(e)}")
                
    def save_rooms_to_file(self):
        """Save rooms to encrypted file"""
        try:
            cipher = self.get_config_cipher()
            data = json.dumps(self.saved_rooms).encode()
            encrypted_data = cipher.encrypt(data)
            
            with open(self.config_file, 'wb') as f:
                f.write(encrypted_data)
                
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save rooms: {str(e)}")
            
    def load_saved_rooms(self):
        """Load rooms from encrypted file"""
        if not os.path.exists(self.config_file):
            return
            
        try:
            cipher = self.get_config_cipher()
            
            with open(self.config_file, 'rb') as f:
                encrypted_data = f.read()
                
            decrypted_data = cipher.decrypt(encrypted_data)
            self.saved_rooms = json.loads(decrypted_data.decode())
            self.refresh_rooms_display()
            
        except Exception as e:
            print(f"Failed to load saved rooms: {e}")
            # If loading fails, start with empty rooms
            self.saved_rooms = {}
            
    def refresh_rooms_display(self):
        """Refresh the rooms display in both dropdown and listbox"""
        # Update dropdown
        room_names = list(self.saved_rooms.keys())
        self.rooms_dropdown['values'] = room_names
        
        # Update listbox
        self.rooms_listbox.delete(0, tk.END)
        for room_name in sorted(room_names):
            self.rooms_listbox.insert(tk.END, room_name)
            
        # Clear details if no rooms
        if not room_names:
            self.room_details.config(state=tk.NORMAL)
            self.room_details.delete(1.0, tk.END)
            self.room_details.insert(tk.END, "No saved rooms")
            self.room_details.config(state=tk.DISABLED)
        
    def generate_key(self):
        """Generate a new encryption key"""
        key = Fernet.generate_key()
        self.key_entry.delete(0, tk.END)
        self.key_entry.insert(0, key.decode())
        self.update_key_display()
        
    def copy_key(self):
        """Copy the encryption key to clipboard"""
        key = self.key_entry.get()
        self.root.clipboard_clear()
        self.root.clipboard_append(key)
        self.root.update()  # Required on some systems
        messagebox.showinfo("Copied", "Encryption key copied to clipboard!")
        
    def toggle_mqtt_password_visibility(self):
        """Toggle showing/hiding the MQTT password"""
        if self.show_mqtt_password_var.get():
            self.mqtt_password_entry.config(show="")
        else:
            self.mqtt_password_entry.config(show="*")
            
    def toggle_key_visibility(self):
        """Toggle showing/hiding the key in the entry field"""
        if self.show_key_var.get():
            self.key_entry.config(show="")
        else:
            self.key_entry.config(show="*")
            
    def update_key_display(self):
        """Update the key display area"""
        key = self.key_entry.get()
        self.key_display.config(state=tk.NORMAL)
        self.key_display.delete(1.0, tk.END)
        self.key_display.insert(tk.END, key)
        self.key_display.config(state=tk.DISABLED)
        
        # Bind key entry changes to update display
        self.key_entry.bind('<KeyRelease>', lambda e: self.update_key_display())
        
    def derive_key(self, password):
        """Derive a Fernet key from a password"""
        # Use SHA256 to create a 32-byte key, then base64 encode for Fernet
        hash_obj = hashlib.sha256(password.encode())
        key = base64.urlsafe_b64encode(hash_obj.digest())
        return key
        
    def connect_mqtt(self):
        """Connect to MQTT broker"""
        try:
            # Get connection details
            server = self.server_entry.get().strip()
            port = int(self.port_entry.get().strip())
            self.channel = self.channel_entry.get().strip()
            self.username = self.username_entry.get().strip()
            encryption_key = self.key_entry.get().strip()
            
            # Get MQTT authentication (optional)
            mqtt_username = self.mqtt_username_entry.get().strip()
            mqtt_password = self.mqtt_password_entry.get().strip()
            
            if not all([server, self.channel, self.username, encryption_key]):
                messagebox.showerror("Error", "Please fill in all required fields")
                return
                
            # Setup encryption
            key = self.derive_key(encryption_key)
            self.cipher = Fernet(key)
            
            # Setup topics
            self.messages_topic = f"chat/{self.channel}/messages"
            self.presence_topic = f"chat/{self.channel}/presence"
            self.userlist_topic = f"chat/{self.channel}/users"
            
            # Setup MQTT client (fix deprecation warning)
            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
            self.mqtt_client.on_connect = self.on_mqtt_connect
            self.mqtt_client.on_message = self.on_mqtt_message
            self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
            
            # Set MQTT authentication if provided
            if mqtt_username:
                self.mqtt_client.username_pw_set(mqtt_username, mqtt_password)
                self.add_system_message(f"Using MQTT authentication for user: {mqtt_username}")
            else:
                self.add_system_message("Connecting with anonymous MQTT access")
            
            # Set last will (sent when we disconnect unexpectedly)
            will_msg = json.dumps({"user": self.username, "status": "offline", "timestamp": time.time()})
            self.mqtt_client.will_set(f"{self.presence_topic}/{self.username}", will_msg, retain=True)
            
            # Connect
            self.status_label.config(text="Connecting...", fg="orange")
            self.mqtt_client.connect(server, port, 60)
            self.mqtt_client.loop_start()
            
        except Exception as e:
            messagebox.showerror("Connection Error", f"Failed to connect: {str(e)}")
            self.status_label.config(text="Connection failed", fg="red")
            
    def on_mqtt_connect(self, client, userdata, flags, rc):
        """Called when MQTT connects - ENHANCED VERSION"""
        if rc == 0:
            self.connected = True
            self.status_label.config(text="Connected", fg="green")
            
            # ENHANCED CLEANUP
            self.clear_my_presence()
            time.sleep(0.2)  # Give time for clearing
            
            # Clear our local user list
            self.online_users.clear()
            self.recent_joins.clear()  # Clear join tracking
            self.update_users_list()
            
            # Subscribe to topics
            client.subscribe(self.messages_topic)
            client.subscribe(f"{self.presence_topic}/+")
            
            # Announce our presence
            self.announce_presence("online")
            
            # Start heartbeat
            self.start_heartbeat()
            
            # Update chat header with room name
            self.chat_header.config(text=f"Chat Messages - #{self.channel}")
            
            # Add welcome message
            self.add_system_message("Connected to chat!")
            
        else:
            self.status_label.config(text=f"Connection failed (code {rc})", fg="red")
            
    def on_mqtt_message(self, client, userdata, msg):
        """Called when MQTT message received"""
        try:
            topic = msg.topic
            payload = msg.payload.decode()
            
            if topic == self.messages_topic:
                self.handle_chat_message(payload)
            elif topic.startswith(self.presence_topic):
                self.handle_presence_message(topic, payload)
                
        except Exception as e:
            print(f"Error handling message: {e}")
            
    def on_mqtt_disconnect(self, client, userdata, rc):
        """Called when MQTT disconnects"""
        self.connected = False
        self.status_label.config(text="Disconnected", fg="red")
        if self.heartbeat_timer:
            self.heartbeat_timer.cancel()
            
    def handle_chat_message(self, encrypted_payload):
        """Handle incoming chat message"""
        try:
            # Decrypt message
            encrypted_data = base64.b64decode(encrypted_payload.encode())
            decrypted_data = self.cipher.decrypt(encrypted_data)
            message_data = json.loads(decrypted_data.decode())
            
            username = message_data.get("user", "Unknown")
            message = message_data.get("message", "")
            timestamp = message_data.get("timestamp", time.time())
            
            # Don't show our own messages (we already displayed them)
            if username != self.username:
                self.add_chat_message(username, message, timestamp)
                
        except Exception as e:
            print(f"Error decrypting message: {e}")
            
    def handle_presence_message(self, topic, payload):
        """Handle user presence updates - ANTI-SPAM DUPLICATE PREVENTION"""
        try:
            # Extract username from topic path
            user_from_topic = topic.split('/')[-1]
            
            # Handle empty payload (user leaving/clearing presence)
            if not payload.strip():
                # Remove user from list if present
                if user_from_topic in self.online_users:
                    self.online_users.remove(user_from_topic)
                    if user_from_topic != self.username:
                        self.add_system_message(f"{user_from_topic} left the chat")
                    # Clear from recent joins when they leave
                    if user_from_topic in self.recent_joins:
                        del self.recent_joins[user_from_topic]
                self.update_users_list()
                return
            
            # Parse the JSON payload
            data = json.loads(payload)
            user = data.get("user", "")
            status = data.get("status", "")
            
            # Validate that topic user matches payload user
            if user != user_from_topic:
                print(f"Warning: User mismatch - topic: {user_from_topic}, payload: {user}")
                return
            
            # ANTI-SPAM DUPLICATE PREVENTION
            if status == "online":
                # Check if user is already in the list
                was_already_online = user in self.online_users
                
                # Add user to list (set automatically prevents duplicates)
                self.online_users.add(user)
                
                # Anti-spam: Only announce if it's a NEW join AND we haven't announced recently
                current_time = time.time()
                last_join_time = self.recent_joins.get(user, 0)
                
                # Only announce if: 1) Not already online, 2) Not ourselves, 3) Haven't announced in last 60 seconds
                if (not was_already_online and 
                    user != self.username and 
                    current_time - last_join_time > 60):
                    
                    self.add_system_message(f"{user} joined the chat")
                    self.recent_joins[user] = current_time
                    
            elif status == "offline":
                # Remove user if present
                if user in self.online_users:
                    self.online_users.remove(user)
                    if user != self.username:
                        self.add_system_message(f"{user} left the chat")
                    # Clear from recent joins when they leave
                    if user in self.recent_joins:
                        del self.recent_joins[user]
            
            # Update the display
            self.update_users_list()
            
        except json.JSONDecodeError:
            print(f"Invalid JSON in presence message: {payload}")
        except Exception as e:
            print(f"Error handling presence: {e}")
            
    def send_message(self, event=None):
        """Send a chat message"""
        if not self.connected:
            return
            
        message_text = self.message_entry.get().strip()
        if not message_text:
            return
            
        try:
            # Create message data
            message_data = {
                "user": self.username,
                "message": message_text,
                "timestamp": time.time()
            }
            
            # Encrypt message
            json_data = json.dumps(message_data)
            encrypted_data = self.cipher.encrypt(json_data.encode())
            encrypted_payload = base64.b64encode(encrypted_data).decode()
            
            # Publish to MQTT
            self.mqtt_client.publish(self.messages_topic, encrypted_payload)
            
            # Add to our own chat display
            self.add_chat_message(self.username, message_text, message_data["timestamp"])
            
            # Clear input
            self.message_entry.delete(0, tk.END)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to send message: {str(e)}")
            
    def announce_presence(self, status):
        """Announce our online/offline status"""
        if self.mqtt_client and self.connected:
            presence_data = {
                "user": self.username,
                "status": status,
                "timestamp": time.time()
            }
            self.mqtt_client.publish(f"{self.presence_topic}/{self.username}", 
                                   json.dumps(presence_data), retain=True)
            
    def start_heartbeat(self):
        """Start sending periodic heartbeat to show we're online"""
        if self.connected:
            self.announce_presence("online")
            # Schedule next heartbeat in 30 seconds
            self.heartbeat_timer = threading.Timer(30.0, self.start_heartbeat)
            self.heartbeat_timer.start()
            
    def disconnect_mqtt(self):
        """Disconnect from MQTT"""
        def _disconnect_worker():
            """Worker function to handle disconnect in background"""
            try:
                if self.connected and self.mqtt_client:
                    # Announce offline status
                    self.announce_presence("offline")
                    time.sleep(0.5)  # Give time for message to send
                    self.clear_my_presence()  # Clear our retained presence
                    
                    # Stop the MQTT loop and disconnect
                    self.mqtt_client.loop_stop()
                    self.mqtt_client.disconnect()
                    
                # Cancel heartbeat timer
                if self.heartbeat_timer:
                    self.heartbeat_timer.cancel()
                    self.heartbeat_timer = None
                    
            except Exception as e:
                print(f"Error during disconnect: {e}")
            finally:
                # Update GUI in main thread
                self.root.after(0, self._finish_disconnect)
        
        # Update status immediately
        self.status_label.config(text="Disconnecting...", fg="orange")
        self.connected = False
        
        # Run disconnect in background thread to avoid GUI freeze
        disconnect_thread = threading.Thread(target=_disconnect_worker, daemon=True)
        disconnect_thread.start()
        
    def _finish_disconnect(self):
        """Finish disconnect process in main GUI thread"""
        self.connected = False
        self.online_users.clear()
        self.recent_joins.clear()  # Clear join tracking
        self.update_users_list()
        self.add_system_message("Disconnected from chat")
        self.status_label.config(text="Disconnected", fg="red")
        
        # Reset chat header
        self.chat_header.config(text="Chat Messages")
        
    def add_chat_message(self, username, message, timestamp):
        """Add a chat message to the display"""
        time_str = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
        
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.insert(tk.END, f"[{time_str}] {username}: {message}\n")
        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)
        
    def add_system_message(self, message):
        """Add a system message to the display"""
        time_str = datetime.now().strftime("%H:%M:%S")
        
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.insert(tk.END, f"[{time_str}] *** {message} ***\n")
        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)
        
    def update_users_list(self):
        """Update the online users list"""
        self.users_listbox.delete(0, tk.END)
        for user in sorted(self.online_users):
            self.users_listbox.insert(tk.END, user)
            
    def on_closing(self):
        """Handle window closing"""
        def _cleanup_and_exit():
            """Cleanup function that runs in background"""
            try:
                if self.connected and self.mqtt_client:
                    self.announce_presence("offline")
                    time.sleep(0.5)  # Give time for message to send
                    self.clear_my_presence()  # Clear our retained presence
                    self.mqtt_client.loop_stop()
                    self.mqtt_client.disconnect()
                if self.heartbeat_timer:
                    self.heartbeat_timer.cancel()
            except:
                pass  # Ignore errors during cleanup
            finally:
                # Destroy window in main thread
                self.root.after(0, self.root.destroy)
        
        # Set connected to False immediately
        self.connected = False
        
        # Run cleanup in background thread
        cleanup_thread = threading.Thread(target=_cleanup_and_exit, daemon=True)
        cleanup_thread.start()
        
        # Give a short timeout for cleanup, then force close
        self.root.after(1000, self.root.destroy)
        
    def run(self):
        """Start the application"""
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()

if __name__ == "__main__":
    # Check for required packages
    try:
        import paho.mqtt.client as mqtt
        from cryptography.fernet import Fernet
    except ImportError as e:
        print(f"Missing required package: {e}")
        print("\nPlease install required packages:")
        print("pip install paho-mqtt cryptography")
        input("Press Enter to exit...")
        exit(1)
        
    app = SecureMQTTChat()
    app.run()