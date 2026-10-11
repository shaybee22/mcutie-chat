import paho.mqtt.client as mqtt
import json
import base64
import hashlib
import time
import threading
from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.clock import Clock
from connection_screen import ConnectionScreen
from chat_screen import MQTTChatScreen
from datetime import datetime

# Import cryptography for proper encryption
try:
    from cryptography.fernet import Fernet
    ENCRYPTION_AVAILABLE = True
except ImportError:
    print("Warning: cryptography package not available. Install with: pip install cryptography")
    ENCRYPTION_AVAILABLE = False
    Fernet = None

class MQTTChatApp(App):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.mqtt_client = None
        self.username = "User"  # Chat display name
        self.cipher = None  # Encryption cipher
        self.connected = False
        self.channel = ""
        self.heartbeat_timer = None
        self.online_users = set()
        self.user_cleanup_timer = None  # New: Timer for cleaning stale users
        
        # MQTT topics
        self.messages_topic = ""
        self.presence_topic = ""
        self.userlist_topic = ""
        
    def build(self):
        # Create screen manager
        self.screen_manager = ScreenManager()
        
        # Create connection screen
        self.connection_screen = ConnectionScreen(name='connection')
        self.connection_screen.set_main_app(self)
        
        # Create chat screen
        self.chat_screen = MQTTChatScreen(name='chat')
        
        # Add screens to manager
        self.screen_manager.add_widget(self.connection_screen)
        self.screen_manager.add_widget(self.chat_screen)
        
        return self.screen_manager
    
    def derive_key(self, password):
        """Derive a Fernet key from a password (same as desktop version)"""
        if not ENCRYPTION_AVAILABLE:
            return None
        # Use SHA256 to create a 32-byte key, then base64 encode for Fernet
        hash_obj = hashlib.sha256(password.encode())
        key = base64.urlsafe_b64encode(hash_obj.digest())
        return key
    
    def connect_to_mqtt(self, server, port, room, encryption_key, mqtt_username=None, mqtt_password=None):
        """Connect to MQTT broker with full encryption and authentication"""
        try:
            self.channel = room
            
            # Validate encryption
            if not ENCRYPTION_AVAILABLE:
                Clock.schedule_once(lambda dt: self.show_error("Cryptography package not installed! Please install: pip install cryptography"))
                return
                
            if not encryption_key:
                Clock.schedule_once(lambda dt: self.show_error("Encryption key is required!"))
                return
            
            # Setup encryption (same method as desktop)
            key = self.derive_key(encryption_key)
            self.cipher = Fernet(key)
            
            # Setup topics (same as desktop)
            self.messages_topic = f"chat/{self.channel}/messages"
            self.presence_topic = f"chat/{self.channel}/presence"
            self.userlist_topic = f"chat/{self.channel}/users"
            
            # Create MQTT client (fix deprecation warning like desktop)
            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
            self.mqtt_client.on_connect = self.on_mqtt_connect
            self.mqtt_client.on_message = self.on_mqtt_message
            self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
            
            # Set MQTT authentication if provided (like desktop)
            if mqtt_username and mqtt_username.strip():
                self.mqtt_client.username_pw_set(mqtt_username.strip(), mqtt_password.strip() if mqtt_password else "")
                print(f"Using MQTT authentication for user: {mqtt_username}")
            else:
                print("Connecting with anonymous MQTT access")
            
            # Set last will (sent when we disconnect unexpectedly) - like desktop
            will_msg = json.dumps({"user": self.username, "status": "offline", "timestamp": time.time()})
            self.mqtt_client.will_set(f"{self.presence_topic}/{self.username}", will_msg, retain=True)
            
            # Connect
            print(f"Connecting to {server}:{port}")
            self.mqtt_client.connect(server, port, 60)
            self.mqtt_client.loop_start()
            
        except Exception as e:
            error_msg = f"Connection failed: {str(e)}"
            print(error_msg)
            Clock.schedule_once(lambda dt: self.show_error(error_msg))
    
    def on_mqtt_connect(self, client, userdata, flags, rc):
        """Called when MQTT connects (same logic as desktop)"""
        if rc == 0:
            self.connected = True
            print("Connected to MQTT broker")
            
            # Clear our presence first (in case of reconnection)
            self.clear_my_presence()
            
            # Subscribe to topics
            client.subscribe(self.messages_topic)
            client.subscribe(f"{self.presence_topic}/+")
            
            # Announce our presence
            self.announce_presence("online")
            
            # Start heartbeat and user cleanup
            self.start_heartbeat()
            self.start_user_cleanup()
            
            # Switch to chat screen and set it up
            Clock.schedule_once(lambda dt: self.setup_chat_screen())
        else:
            error_msg = f"MQTT connection failed with code {rc}"
            print(error_msg)
            Clock.schedule_once(lambda dt: self.show_error(error_msg))
    
    def clear_my_presence(self):
        """Clear our own presence message to prevent duplicates"""
        if self.mqtt_client and self.username:
            # Send empty retained message to clear our presence
            self.mqtt_client.publish(f"{self.presence_topic}/{self.username}", "", retain=True)
    
    def start_user_cleanup(self):
        """Start periodic cleanup of stale users"""
        if self.connected:
            self.cleanup_stale_users()
            # Schedule next cleanup in 60 seconds
            self.user_cleanup_timer = threading.Timer(60.0, self.start_user_cleanup)
            self.user_cleanup_timer.start()
    
    def cleanup_stale_users(self):
        """Remove users who haven't sent heartbeat recently"""
        # For now, we'll rely on retained messages and proper disconnect handling
        # This can be enhanced later with timestamp tracking
        pass
    
    def on_mqtt_message(self, client, userdata, msg):
        """Called when MQTT message received (same logic as desktop)"""
        try:
            topic = msg.topic
            payload = msg.payload.decode()
            
            if topic == self.messages_topic:
                self.handle_chat_message(payload)
            elif topic.startswith(self.presence_topic):
                self.handle_presence_message(topic, payload)
                
        except Exception as e:
            print(f"Error handling message: {e}")
    
    def handle_chat_message(self, encrypted_payload):
        """Handle incoming chat message (same decryption as desktop)"""
        try:
            # Decrypt message (same as desktop)
            encrypted_data = base64.b64decode(encrypted_payload.encode())
            decrypted_data = self.cipher.decrypt(encrypted_data)
            message_data = json.loads(decrypted_data.decode())
            
            username = message_data.get("user", "Unknown")
            message = message_data.get("message", "")
            timestamp = message_data.get("timestamp", time.time())
            
            # Don't show our own messages (we already displayed them)
            if username != self.username:
                Clock.schedule_once(lambda dt: self.chat_screen.add_chat_message(username, message, timestamp))
                
        except Exception as e:
            print(f"Error decrypting message: {e}")
    
    def handle_presence_message(self, topic, payload):
        """Handle user presence updates (improved logic)"""
        try:
            # Extract username from topic
            user_from_topic = topic.split('/')[-1]
            
            # Handle empty payload (user leaving)
            if not payload.strip():
                if user_from_topic in self.online_users:
                    self.online_users.remove(user_from_topic)
                    if user_from_topic != self.username:
                        Clock.schedule_once(lambda dt: self.chat_screen.add_system_message(f"{user_from_topic} left the chat"))
                Clock.schedule_once(lambda dt: self.chat_screen.update_users_list(list(self.online_users)))
                return
            
            data = json.loads(payload)
            user = data.get("user", "")
            status = data.get("status", "")
            
            # Ensure user from topic matches user in payload
            if user != user_from_topic:
                print(f"Warning: User mismatch in presence message: {user} vs {user_from_topic}")
                return
            
            if status == "online":
                if user not in self.online_users:
                    self.online_users.add(user)
                    if user != self.username:  # Don't announce ourselves
                        Clock.schedule_once(lambda dt: self.chat_screen.add_system_message(f"{user} joined the chat"))
            elif status == "offline":
                if user in self.online_users:
                    self.online_users.remove(user)
                    if user != self.username:
                        Clock.schedule_once(lambda dt: self.chat_screen.add_system_message(f"{user} left the chat"))
                        
            # Update users list on chat screen
            Clock.schedule_once(lambda dt: self.chat_screen.update_users_list(list(self.online_users)))
            
        except Exception as e:
            print(f"Error handling presence: {e}")
    
    def announce_presence(self, status):
        """Announce our online/offline status (same as desktop)"""
        if self.mqtt_client and self.connected:
            presence_data = {
                "user": self.username,
                "status": status,
                "timestamp": time.time()
            }
            self.mqtt_client.publish(f"{self.presence_topic}/{self.username}", 
                                   json.dumps(presence_data), retain=True)
    
    def start_heartbeat(self):
        """Start sending periodic heartbeat to show we're online (same as desktop)"""
        if self.connected:
            self.announce_presence("online")
            # Schedule next heartbeat in 30 seconds
            self.heartbeat_timer = threading.Timer(30.0, self.start_heartbeat)
            self.heartbeat_timer.start()
    
    def send_message(self, message_text):
        """Send an encrypted message (same encryption as desktop)"""
        if not self.connected or not message_text.strip():
            return False
            
        try:
            # Create message data (same format as desktop)
            message_data = {
                "user": self.username,
                "message": message_text.strip(),
                "timestamp": time.time()
            }
            
            # Encrypt message (same method as desktop)
            json_data = json.dumps(message_data)
            encrypted_data = self.cipher.encrypt(json_data.encode())
            encrypted_payload = base64.b64encode(encrypted_data).decode()
            
            # Publish to MQTT
            self.mqtt_client.publish(self.messages_topic, encrypted_payload)
            
            # Add to our own chat display
            Clock.schedule_once(lambda dt: self.chat_screen.add_chat_message(
                self.username, message_text.strip(), message_data["timestamp"]))
            
            return True
            
        except Exception as e:
            print(f"Failed to send message: {str(e)}")
            return False
    
    def on_mqtt_disconnect(self, client, userdata, rc):
        """Called when MQTT disconnects (same as desktop)"""
        self.connected = False
        if self.heartbeat_timer:
            self.heartbeat_timer.cancel()
            self.heartbeat_timer = None
        if self.user_cleanup_timer:
            self.user_cleanup_timer.cancel()
            self.user_cleanup_timer = None
        print("Disconnected from MQTT broker")
    
    def setup_chat_screen(self):
        """Set up the chat screen with MQTT client and room"""
        self.chat_screen.setup(self.mqtt_client, self.channel, self.username, self)
        self.screen_manager.current = 'chat'
    
    def switch_to_connection(self):
        """Switch back to connection screen and disconnect"""
        def _disconnect_worker():
            """Worker function to handle disconnect in background"""
            try:
                if self.connected and self.mqtt_client:
                    # Announce offline status and clear our presence
                    self.announce_presence("offline")
                    time.sleep(0.5)  # Give time for message to send
                    self.clear_my_presence()
                    
                    # Stop the MQTT loop and disconnect
                    self.mqtt_client.loop_stop()
                    self.mqtt_client.disconnect()
                    
                # Cancel timers
                if self.heartbeat_timer:
                    self.heartbeat_timer.cancel()
                    self.heartbeat_timer = None
                if self.user_cleanup_timer:
                    self.user_cleanup_timer.cancel()
                    self.user_cleanup_timer = None
                    
            except Exception as e:
                print(f"Error during disconnect: {e}")
            finally:
                # Update GUI in main thread
                Clock.schedule_once(lambda dt: self._finish_disconnect())
        
        # Update status immediately
        self.connected = False
        
        # Run disconnect in background thread to avoid GUI freeze
        disconnect_thread = threading.Thread(target=_disconnect_worker, daemon=True)
        disconnect_thread.start()
    
    def _finish_disconnect(self):
        """Finish disconnect process in main GUI thread"""
        self.connected = False
        self.online_users.clear()
        self.screen_manager.current = 'connection'
        if self.mqtt_client:
            self.mqtt_client = None
    
    def show_error(self, message):
        """Show error message (can be implemented as popup or system message)"""
        print(f"Error: {message}")
        # For now, just print. Could be enhanced with popup later.

if __name__ == '__main__':
    MQTTChatApp().run()