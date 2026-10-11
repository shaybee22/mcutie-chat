import paho.mqtt.client as mqtt
import time
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.popup import Popup
from kivy.clock import Clock
from kivy.app import App
from kivy.core.window import Window
from datetime import datetime

# Set keyboard behavior for Android - MUST be early
Window.keyboard_anim_args = {"d": .2, "t": "linear"}
Window.softinput_mode = "below_target"

class MQTTChatScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mqtt_client = None
        self.topic = None
        self.username = "User"  # Default username
        self.main_app = None  # Reference to main app
        self.online_users = []  # List of online users

        # Main layout
        layout = BoxLayout(orientation='vertical', padding=[10, 10, 10, 10], spacing=10)

        # Top bar with room name and user controls
        top_bar = BoxLayout(
            orientation='horizontal', 
            size_hint_y=None, 
            height='60dp',
            spacing=10
        )
        
        self.room_label = Label(
            text='Room: Not Connected', 
            size_hint_x=0.45,
            font_size='16sp',
            halign='left',
            valign='middle',
            text_size=(None, None)  # Will be set dynamically
        )
        self.room_label.bind(size=self._update_room_label_text_size)
        
        # Users button (shows count and opens user list)
        self.users_button = Button(
            text='Users: 0',
            size_hint_x=0.25,
            font_size='14sp',
            size_hint_y=None,
            height='50dp'
        )
        self.users_button.bind(on_release=self.show_users_popup)
        
        self.disconnect_button = Button(
            text='Disconnect', 
            size_hint_x=0.3,
            font_size='12sp',
            size_hint_y=None,
            height='50dp'
        )
        self.disconnect_button.bind(on_release=self.disconnect)
        
        top_bar.add_widget(self.room_label)
        top_bar.add_widget(self.users_button)
        top_bar.add_widget(self.disconnect_button)
        layout.add_widget(top_bar)

        # Message display area with proper scrolling
        self.scrollview = ScrollView()
        
        self.message_log = Label(
            size_hint_y=None, 
            text_size=(None, None), 
            halign='left', 
            valign='top',
            markup=True,
            font_size='14sp',
            padding=[10, 10]
        )
        self.message_log.bind(texture_size=self.update_log_height)
        self.scrollview.add_widget(self.message_log)
        layout.add_widget(self.scrollview)

        # Message input area
        self.input_area = BoxLayout(
            size_hint_y=None, 
            height='60dp', 
            spacing=10,
            padding=[0, 10, 0, 0]
        )
        
        self.message_input = TextInput(
            hint_text="Type your message here...", 
            multiline=False,
            size_hint_x=0.75,
            font_size='16sp'
        )
        self.message_input.bind(on_text_validate=self.send_message)
        
        self.send_button = Button(
            text='Send',
            size_hint_x=0.25,
            font_size='16sp'
        )
        self.send_button.bind(on_release=self.send_message)
        
        self.input_area.add_widget(self.message_input)
        self.input_area.add_widget(self.send_button)
        layout.add_widget(self.input_area)

        self.add_widget(layout)
        
        # Store main layout reference
        self.main_layout = layout
        
        # Initialize with welcome message
        self.clear_messages()

    def _update_room_label_text_size(self, instance, size):
        """Update room label text size for proper wrapping"""
        # Set text_size to enable proper text wrapping
        self.room_label.text_size = (size[0], None)

    def update_log_height(self, instance, value):
        """Update the height of the message log and scroll to bottom"""
        # Set minimum height to fill the scroll area
        min_height = self.scrollview.height if self.scrollview.height > 0 else 400
        self.message_log.height = max(value[1], min_height)
        
        # Set text_size for proper word wrapping
        available_width = self.scrollview.width - 20 if self.scrollview.width > 0 else 300
        self.message_log.text_size = (available_width, None)
        
        # Scroll to bottom after a short delay
        Clock.schedule_once(lambda dt: setattr(self.scrollview, 'scroll_y', 0), 0.1)

    def show_users_popup(self, instance):
        """Show popup with list of online users"""
        if not self.online_users:
            users_text = "No users online"
        else:
            users_text = "\n".join([f"• {user}" for user in sorted(self.online_users)])
        
        # Create scrollable content for many users
        content_layout = BoxLayout(orientation='vertical', spacing=10, padding=20)
        
        users_label = Label(
            text=users_text,
            font_size='16sp',
            halign='left',
            valign='top',
            text_size=(None, None)
        )
        
        # Create scrollview for long user lists
        scroll = ScrollView()
        scroll.add_widget(users_label)
        content_layout.add_widget(scroll)
        
        # Close button
        close_button = Button(
            text='Close',
            size_hint_y=None,
            height='50dp',
            font_size='16sp'
        )
        content_layout.add_widget(close_button)
        
        # Create popup
        popup = Popup(
            title=f'Online Users ({len(self.online_users)})',
            content=content_layout,
            size_hint=(0.8, 0.7),
            auto_dismiss=True
        )
        
        # Bind close button
        close_button.bind(on_release=popup.dismiss)
        
        # Update label text size after popup opens
        def update_label_size(dt):
            users_label.text_size = (scroll.width - 20, None)
        Clock.schedule_once(update_label_size, 0.1)
        
        popup.open()

    def setup(self, mqtt_client, topic, username="User", main_app=None):
        """Set up the chat screen with MQTT client and topic"""
        self.mqtt_client = mqtt_client
        self.topic = topic
        self.username = username  # Set the username from connection screen
        self.main_app = main_app  # Reference to main app for sending messages
        self.room_label.text = f"Room: {topic}"
        
        # Clear previous messages and show connection message
        self.clear_messages()
        self.add_system_message(f"Connected to room: {topic}")

    def clear_messages(self):
        """Clear all messages from the chat"""
        self.message_log.text = ""

    def add_chat_message(self, username, message_text, timestamp):
        """Add a chat message to the log (called from main app)"""
        time_str = datetime.fromtimestamp(timestamp).strftime("%I:%M %p")
        
        # Format message with better mobile-friendly styling
        # Use different colors for different users
        username_color = "4488ff" if username != self.username else "44aa44"
        formatted_message = f"[color=888888][size=12sp]{time_str}[/size][/color]\n[color={username_color}][size=14sp][b]{username}:[/b][/color] [size=14sp]{message_text}[/size]"
        
        if self.message_log.text:
            self.message_log.text += "\n\n" + formatted_message
        else:
            self.message_log.text = formatted_message

    def add_system_message(self, message_text):
        """Add a system message to the chat log"""
        timestamp = time.time()
        time_str = datetime.fromtimestamp(timestamp).strftime("%I:%M %p")
        
        # System messages with distinct styling
        formatted_message = f"[color=888888][size=12sp]{time_str}[/size][/color]\n[color=00aa00][size=13sp][i]* {message_text}[/i][/size][/color]"
        
        if self.message_log.text:
            self.message_log.text += "\n\n" + formatted_message
        else:
            self.message_log.text = formatted_message

    def update_users_list(self, users_list):
        """Update the online users list (called from main app)"""
        self.online_users = users_list
        user_count = len(users_list)
        self.users_button.text = f"Users: {user_count}"

    def send_message(self, instance):
        """Send a message via the main app (which handles encryption)"""
        text = self.message_input.text.strip()
        if not text:
            return
            
        if not self.main_app:
            self.add_system_message("Error: App not properly initialized")
            return
        
        # Send via main app which handles encryption
        success = self.main_app.send_message(text)
        if success:
            # Clear input
            self.message_input.text = ''
        else:
            self.add_system_message("Failed to send message")

    def disconnect(self, instance):
        """Disconnect from the chat room"""
        try:
            if self.main_app:
                self.main_app.switch_to_connection()
            else:
                # Fallback - just switch screens
                if self.manager:
                    self.manager.current = 'connection'
                
        except Exception as e:
            print(f"Disconnect error: {e}")
            # Still try to switch screens
            if self.manager:
                self.manager.current = 'connection'

    def on_enter(self):
        """Called when entering this screen"""
        # Focus on message input after a short delay
        Clock.schedule_once(lambda dt: setattr(self.message_input, 'focus', True), 0.3)

    def on_leave(self):
        """Called when leaving this screen"""
        # Clear focus
        self.message_input.focus = False