import os
import json
import secrets
import string
import io
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.spinner import Spinner
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.image import Image
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
# Note: kivy.clipboard not available on Android

ROOMS_DIR = "rooms"
os.makedirs(ROOMS_DIR, exist_ok=True)

class ConnectionScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.main_app = None
        
        # Create scrollable main layout for mobile
        scroll = ScrollView()
        
        # Main layout with proper mobile spacing
        layout = BoxLayout(
            orientation='vertical', 
            spacing=20,  # Increased from 15
            padding=[25, 50, 25, 25],  # More padding
            size_hint_y=None
        )
        layout.bind(minimum_height=layout.setter('height'))

        # App title with more space
        title = Label(
            text='MQTT Chat App', 
            font_size='28sp',  # Larger font
            size_hint_y=None, 
            height='80dp',  # Taller
            color=[1, 1, 1, 1]
        )
        layout.add_widget(title)

        # Username section with better spacing
        username_label = Label(
            text='Your Username:', 
            size_hint_y=None, 
            height='45dp',  # Taller labels
            font_size='18sp'  # Larger font
        )
        layout.add_widget(username_label)
        
        self.username_input = TextInput(
            text='User',
            size_hint_y=None, 
            height='55dp',  # Much taller inputs
            font_size='18sp',  # Larger font
            multiline=False,
            padding=[10, 15]  # Internal padding
        )
        layout.add_widget(self.username_input)

        # Spacer
        layout.add_widget(Label(size_hint_y=None, height='10dp'))

        # Server address section
        server_label = Label(
            text='Server Address:', 
            size_hint_y=None, 
            height='45dp',
            font_size='18sp'
        )
        layout.add_widget(server_label)
        
        self.server_input = TextInput(
            text='localhost',
            size_hint_y=None, 
            height='55dp',
            font_size='18sp',
            multiline=False,
            padding=[10, 15]
        )
        layout.add_widget(self.server_input)

        # Port section
        port_label = Label(
            text='Port:', 
            size_hint_y=None, 
            height='45dp',
            font_size='18sp'
        )
        layout.add_widget(port_label)
        
        self.port_input = TextInput(
            text='1883',
            size_hint_y=None, 
            height='55dp',
            font_size='18sp',
            multiline=False,
            input_filter='int',
            padding=[10, 15]
        )
        layout.add_widget(self.port_input)

        # Room name section
        room_label = Label(
            text='Chat Room Name:', 
            size_hint_y=None, 
            height='45dp',
            font_size='18sp'
        )
        layout.add_widget(room_label)
        
        self.room_input = TextInput(
            text='general',
            size_hint_y=None, 
            height='55dp',
            font_size='18sp',
            multiline=False,
            padding=[10, 15]
        )
        layout.add_widget(self.room_input)

        # Big spacer before MQTT auth
        layout.add_widget(Label(size_hint_y=None, height='25dp'))

        # MQTT Authentication section header
        mqtt_auth_header = Label(
            text='MQTT Authentication (Optional)',
            size_hint_y=None,
            height='40dp',
            font_size='16sp',
            italic=True,
            color=[0.8, 0.8, 0.8, 1]
        )
        layout.add_widget(mqtt_auth_header)

        # MQTT Username
        mqtt_user_label = Label(
            text='MQTT Username:', 
            size_hint_y=None, 
            height='40dp',
            font_size='16sp'
        )
        layout.add_widget(mqtt_user_label)
        
        self.mqtt_username_input = TextInput(
            size_hint_y=None, 
            height='50dp',
            font_size='16sp',
            multiline=False,
            padding=[10, 12]
        )
        layout.add_widget(self.mqtt_username_input)
        
        # MQTT Password
        mqtt_pass_label = Label(
            text='MQTT Password:', 
            size_hint_y=None, 
            height='40dp',
            font_size='16sp'
        )
        layout.add_widget(mqtt_pass_label)
        
        self.mqtt_password_input = TextInput(
            password=True,
            size_hint_y=None, 
            height='50dp',
            font_size='16sp',
            multiline=False,
            padding=[10, 12]
        )
        layout.add_widget(self.mqtt_password_input)
        
        # Show MQTT password toggle
        mqtt_toggle_layout = BoxLayout(
            orientation='horizontal', 
            size_hint_y=None, 
            height='50dp',
            spacing=15
        )
        mqtt_toggle_label = Label(
            text='Show MQTT Password:', 
            size_hint_x=0.7,
            font_size='16sp'
        )
        self.show_mqtt_password = CheckBox(size_hint_x=0.3, size_hint_y=None, height='40dp')
        self.show_mqtt_password.bind(active=self.toggle_mqtt_password_visibility)
        mqtt_toggle_layout.add_widget(mqtt_toggle_label)
        mqtt_toggle_layout.add_widget(self.show_mqtt_password)
        layout.add_widget(mqtt_toggle_layout)
        
        # Help text
        help_label = Label(
            text='Leave blank for anonymous connection',
            size_hint_y=None,
            height='35dp',
            font_size='14sp',
            color=[0.6, 0.6, 0.6, 1]
        )
        layout.add_widget(help_label)

        # Big spacer before encryption
        layout.add_widget(Label(size_hint_y=None, height='25dp'))

        # Encryption key section with generate button
        key_label = Label(
            text='Encryption Key:', 
            size_hint_y=None, 
            height='45dp',
            font_size='18sp'
        )
        layout.add_widget(key_label)
        
        # Key input and generate button in horizontal layout
        key_layout = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height='55dp',
            spacing=15
        )
        
        self.key_input = TextInput(
            password=True,
            size_hint_x=0.7,
            font_size='16sp',
            multiline=False,
            padding=[10, 15]
        )
        
        self.generate_key_button = Button(
            text='Generate',
            size_hint_x=0.3,
            font_size='16sp',
            size_hint_y=None,
            height='55dp'
        )
        self.generate_key_button.bind(on_release=self.generate_key)
        
        key_layout.add_widget(self.key_input)
        key_layout.add_widget(self.generate_key_button)
        layout.add_widget(key_layout)

        # Key controls - now with 3 buttons: Show/Copy/QR
        key_controls = BoxLayout(
            orientation='horizontal', 
            size_hint_y=None, 
            height='60dp',
            spacing=10
        )
        
        # Show key toggle (reduced width)
        show_layout = BoxLayout(
            orientation='horizontal',
            size_hint_x=0.4,  # Reduced from 0.6
            spacing=5
        )
        show_label = Label(
            text='Show:', 
            size_hint_x=0.6,
            font_size='15sp'  # Slightly smaller
        )
        self.show_key = CheckBox(size_hint_x=0.4, size_hint_y=None, height='40dp')
        self.show_key.bind(active=self.toggle_key_visibility)
        show_layout.add_widget(show_label)
        show_layout.add_widget(self.show_key)
        
        # Copy key button (reduced width)
        self.copy_key_button = Button(
            text='Copy',
            size_hint_x=0.3,  # Reduced from 0.4
            font_size='15sp',  # Slightly smaller
            size_hint_y=None,
            height='55dp'
        )
        self.copy_key_button.bind(on_release=self.copy_key)
        
        # New QR key button
        self.qr_key_button = Button(
            text='Key QR',
            size_hint_x=0.3,  # New button
            font_size='15sp',
            size_hint_y=None,
            height='55dp',
            background_color=[0.3, 0.6, 0.9, 1]  # Blue color to distinguish
        )
        self.qr_key_button.bind(on_release=self.show_key_qr)
        
        key_controls.add_widget(show_layout)
        key_controls.add_widget(self.copy_key_button)
        key_controls.add_widget(self.qr_key_button)
        layout.add_widget(key_controls)

        # Big spacer before saved rooms
        layout.add_widget(Label(size_hint_y=None, height='30dp'))

        # Saved rooms section
        saved_label = Label(
            text='Saved Rooms:', 
            size_hint_y=None, 
            height='45dp',
            font_size='18sp'
        )
        layout.add_widget(saved_label)
        
        self.room_spinner = Spinner(
            text='Load Room',
            values=self.get_saved_rooms(),
            size_hint_y=None, 
            height='55dp',
            font_size='16sp'
        )
        self.room_spinner.bind(text=self.load_room)
        layout.add_widget(self.room_spinner)

        # Spacer
        layout.add_widget(Label(size_hint_y=None, height='20dp'))

        # Save, copy, and delete room buttons (now 3 buttons instead of 2)
        room_buttons = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height='65dp',  # Slightly reduced height
            spacing=10  # Reduced spacing to fit 3 buttons
        )
        
        self.save_button = Button(
            text='Save Room',
            size_hint_x=0.33,  # Changed from 0.5 to 0.33 for 3 buttons
            font_size='15sp',  # Slightly smaller font
            size_hint_y=None,
            height='60dp'  # Slightly reduced height
        )
        self.save_button.bind(on_release=self.save_room)
        
        self.copy_room_button = Button(
            text='Copy Config',
            size_hint_x=0.33,  # Changed from 0.5 to 0.33 for 3 buttons
            font_size='15sp',  # Slightly smaller font
            size_hint_y=None,
            height='60dp'  # Slightly reduced height
        )
        self.copy_room_button.bind(on_release=self.copy_room_config)
        
        # New delete button
        self.delete_room_button = Button(
            text='Delete Room',
            size_hint_x=0.33,  # 1/3 width for 3 buttons
            font_size='15sp',  # Slightly smaller font
            size_hint_y=None,
            height='60dp',  # Slightly reduced height
            background_color=[0.8, 0.3, 0.3, 1]  # Reddish color to indicate destructive action
        )
        self.delete_room_button.bind(on_release=self.delete_room)
        
        room_buttons.add_widget(self.save_button)
        room_buttons.add_widget(self.copy_room_button)
        room_buttons.add_widget(self.delete_room_button)
        layout.add_widget(room_buttons)

        # Big spacer
        layout.add_widget(Label(size_hint_y=None, height='25dp'))

        # Connect button - make it prominent
        self.connect_button = Button(
            text='Connect to Chat Room',
            size_hint_y=None, 
            height='80dp',  # Extra tall for main action
            font_size='20sp'  # Larger font
        )
        self.connect_button.bind(on_release=self.connect)
        layout.add_widget(self.connect_button)

        # Bottom padding
        layout.add_widget(Label(size_hint_y=None, height='50dp'))

        scroll.add_widget(layout)
        self.add_widget(scroll)

    def set_main_app(self, app):
        """Set reference to main app"""
        self.main_app = app

    def toggle_mqtt_password_visibility(self, checkbox, value):
        """Toggle MQTT password visibility"""
        self.mqtt_password_input.password = not value

    def generate_key(self, instance):
        """Generate a new encryption key (like desktop version)"""
        try:
            from cryptography.fernet import Fernet
            key = Fernet.generate_key()
            self.key_input.text = key.decode()
            self.show_popup("New encryption key generated!")
        except ImportError:
            # Fallback to simple random key if cryptography not available
            key = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
            self.key_input.text = key
            self.show_popup("New encryption key generated! (Install 'cryptography' package for stronger keys)")

    def copy_key(self, instance):
        """Copy the encryption key to clipboard"""
        if not self.key_input.text:
            self.show_popup("No key to copy!")
            return
            
        try:
            # Try to use Kivy's clipboard
            from kivy.core.clipboard import Clipboard
            Clipboard.copy(self.key_input.text)
            self.show_popup("Encryption key copied to clipboard!")
        except ImportError:
            # Fallback: Show key in popup for manual copying
            self.show_popup(f"Clipboard not available.\n\nEncryption Key:\n{self.key_input.text}\n\n(Long press to select and copy manually)")
        except Exception as e:
            # Another fallback if clipboard fails for any reason
            print(f"Clipboard error: {e}")
            self.show_popup(f"Could not copy to clipboard.\n\nEncryption Key:\n{self.key_input.text}\n\n(Long press to select and copy manually)")

    def show_key_qr(self, instance):
        """Show QR code for the encryption key"""
        if not self.key_input.text.strip():
            self.show_popup("No encryption key to show QR code for!")
            return
            
        try:
            # Import QR code libraries
            import qrcode
            from PIL import Image as PILImage
            
            # Generate QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(self.key_input.text.strip())
            qr.make(fit=True)

            # Create QR code image
            qr_image = qr.make_image(fill_color="black", back_color="white")
            
            # Convert PIL image to bytes
            img_buffer = io.BytesIO()
            qr_image.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            
            # Create Kivy image from bytes
            kivy_image = CoreImage(img_buffer, ext='png')
            
            # Create popup content
            content_layout = BoxLayout(orientation='vertical', spacing=20, padding=20)
            
            # Instructions
            instructions = Label(
                text='Scan this QR code with any QR reader app\nto get the encryption key',
                font_size='16sp',
                halign='center',
                valign='middle',
                size_hint_y=None,
                height='60dp',
                text_size=(None, None)
            )
            content_layout.add_widget(instructions)
            
            # QR code image
            qr_widget = Image(
                texture=kivy_image.texture,
                size_hint=(1, 1)
            )
            content_layout.add_widget(qr_widget)
            
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
                title='Encryption Key QR Code',
                content=content_layout,
                size_hint=(0.9, 0.8),
                auto_dismiss=True
            )
            
            # Bind close button
            close_button.bind(on_release=popup.dismiss)
            
            # Update instructions text size after popup opens
            def update_instructions_size(dt):
                try:
                    instructions.text_size = (popup.width - 40, None)
                except:
                    pass
            Clock.schedule_once(update_instructions_size, 0.1)
            
            popup.open()
            
        except ImportError as e:
            self.show_popup(f"QR code libraries not available: {e}\nPlease check app installation.")
        except Exception as e:
            print(f"QR code generation error: {e}")
            self.show_popup(f"Error generating QR code: {e}")

    def copy_room_config(self, instance):
        """Copy room configuration as shareable text"""
        config_text = f"""MQTT Chat Room Config:
Server: {self.server_input.text}
Port: {self.port_input.text}
Room: {self.room_input.text}
Key: {self.key_input.text if self.key_input.text else 'None'}"""
        
        try:
            # Try to use Kivy's clipboard
            from kivy.core.clipboard import Clipboard
            Clipboard.copy(config_text)
            self.show_popup("Room configuration copied to clipboard!")
        except ImportError:
            # Fallback: Show config in popup for manual copying
            self.show_popup(f"Clipboard not available.\n\nRoom Configuration:\n\n{config_text}\n\n(Long press to select and copy manually)")
        except Exception as e:
            # Another fallback if clipboard fails for any reason
            print(f"Clipboard error: {e}")
            self.show_popup(f"Could not copy to clipboard.\n\nRoom Configuration:\n\n{config_text}\n\n(Long press to select and copy manually)")

    def toggle_key_visibility(self, checkbox, value):
        """Toggle password visibility for encryption key"""
        self.key_input.password = not value

    def get_saved_rooms(self):
        """Get list of saved room configurations"""
        try:
            return [f[:-5] for f in os.listdir(ROOMS_DIR) if f.endswith('.json')]
        except:
            return []

    def load_room(self, spinner, room_name):
        """Load a saved room configuration"""
        if room_name == 'Load Room':
            return
            
        file_path = os.path.join(ROOMS_DIR, f"{room_name}.json")
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    data = json.load(f)
                self.username_input.text = data.get("username", "User")
                self.server_input.text = data.get("server", "localhost")
                self.port_input.text = str(data.get("port", "1883"))
                self.room_input.text = data.get("room", "general")
                self.key_input.text = data.get("key", "")
                self.mqtt_username_input.text = data.get("mqtt_username", "")
                self.mqtt_password_input.text = data.get("mqtt_password", "")
        except Exception as e:
            self.show_popup(f"Error loading room: {e}")

    def save_room(self, instance):
        """Save current room configuration"""
        name = self.room_input.text.strip()
        if not name:
            self.show_popup("Room name is required!")
            return
            
        try:
            data = {
                "username": self.username_input.text.strip() or "User",
                "server": self.server_input.text.strip() or "localhost",
                "port": int(self.port_input.text.strip() or "1883"),
                "room": name,
                "key": self.key_input.text.strip(),
                "mqtt_username": self.mqtt_username_input.text.strip(),
                "mqtt_password": self.mqtt_password_input.text.strip()
            }
            
            file_path = os.path.join(ROOMS_DIR, f"{name}.json")
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)
                
            # Update spinner values
            self.room_spinner.values = self.get_saved_rooms()
            self.show_popup("Room configuration saved!")
            
        except Exception as e:
            self.show_popup(f"Error saving room: {e}")

    def delete_room(self, instance):
        """Delete a saved room configuration with confirmation"""
        if self.room_spinner.text == 'Load Room' or not self.room_spinner.text:
            self.show_popup("Please select a room to delete from the dropdown first!")
            return
        
        room_name = self.room_spinner.text
        
        # Create confirmation popup
        content_layout = BoxLayout(orientation='vertical', spacing=20, padding=20)
        
        warning_label = Label(
            text=f"Are you sure you want to delete the saved room:\n\n'{room_name}'\n\nThis action cannot be undone.",
            font_size='16sp',
            halign='center',
            valign='middle',
            text_size=(None, None)
        )
        content_layout.add_widget(warning_label)
        
        # Button layout for confirmation
        button_layout = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height='60dp',
            spacing=15
        )
        
        cancel_button = Button(
            text='Cancel',
            size_hint_x=0.5,
            font_size='16sp',
            background_color=[0.5, 0.5, 0.5, 1]  # Gray color
        )
        
        confirm_button = Button(
            text='Delete',
            size_hint_x=0.5,
            font_size='16sp',
            background_color=[0.8, 0.3, 0.3, 1]  # Red color
        )
        
        button_layout.add_widget(cancel_button)
        button_layout.add_widget(confirm_button)
        content_layout.add_widget(button_layout)
        
        # Create popup
        popup = Popup(
            title='Confirm Delete',
            content=content_layout,
            size_hint=(0.9, 0.6),
            auto_dismiss=False  # Prevent accidental dismissal
        )
        
        # Bind button actions
        def cancel_delete(instance):
            popup.dismiss()
        
        def confirm_delete(instance):
            popup.dismiss()
            self.perform_room_deletion(room_name)
        
        cancel_button.bind(on_release=cancel_delete)
        confirm_button.bind(on_release=confirm_delete)
        
        # Update label text size after popup opens
        def update_label_size(dt):
            try:
                warning_label.text_size = (popup.width - 40, None)
            except:
                pass  # Ignore if popup is already closed
        Clock.schedule_once(update_label_size, 0.1)
        
        popup.open()

    def perform_room_deletion(self, room_name):
        """Actually delete the room file and update UI"""
        try:
            file_path = os.path.join(ROOMS_DIR, f"{room_name}.json")
            print(f"Attempting to delete: {file_path}")  # Debug print
            
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"Successfully deleted: {file_path}")  # Debug print
                
                # Update spinner values and reset to default
                new_rooms = self.get_saved_rooms()
                print(f"Remaining rooms: {new_rooms}")  # Debug print
                
                self.room_spinner.values = new_rooms
                self.room_spinner.text = 'Load Room'
                
                self.show_popup(f"Room '{room_name}' has been deleted successfully!")
            else:
                print(f"File does not exist: {file_path}")  # Debug print
                self.show_popup(f"Room file not found: {room_name}")
                
        except Exception as e:
            print(f"Error deleting room: {e}")  # Debug print
            import traceback
            traceback.print_exc()  # Print full traceback for debugging
            self.show_popup(f"Error deleting room: {e}")

    def show_popup(self, message):
        """Show info popup with better mobile sizing"""
        popup_content = Label(
            text=message,
            text_size=(None, None),
            halign='center',
            valign='middle',
            font_size='16sp'
        )
        
        popup = Popup(
            title='Information',
            content=popup_content,
            size_hint=(0.9, 0.6),  # Larger on mobile
            auto_dismiss=True
        )
        popup.open()

    def connect(self, instance):
        """Connect to MQTT broker"""
        # Validate inputs
        username = self.username_input.text.strip()
        server = self.server_input.text.strip()
        port = self.port_input.text.strip()
        room = self.room_input.text.strip()
        key = self.key_input.text.strip()
        
        if not username:
            self.show_popup("Username is required!")
            return
        
        if not server:
            self.show_popup("Server address is required!")
            return
            
        if not port:
            port = "1883"
            
        try:
            port_int = int(port)
            if port_int <= 0 or port_int > 65535:
                raise ValueError("Invalid port range")
        except ValueError:
            self.show_popup("Port must be a valid number (1-65535)!")
            return
            
        if not room:
            self.show_popup("Room name is required!")
            return
        
        # Connect via main app (now with MQTT auth)
        if self.main_app:
            # Pass username and MQTT auth to main app
            self.main_app.username = username
            mqtt_user = self.mqtt_username_input.text.strip()
            mqtt_pass = self.mqtt_password_input.text.strip()
            self.main_app.connect_to_mqtt(server, port_int, room, key, mqtt_user, mqtt_pass)
        else:
            self.show_popup("App not properly initialized!")

# For testing the connection screen standalone
if __name__ == '__main__':
    from kivy.app import App
    from kivy.clock import Clock
    
    class TestApp(App):
        def build(self):
            return ConnectionScreen()
    
    TestApp().run()