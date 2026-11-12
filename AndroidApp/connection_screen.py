import os
import json
import io
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.spinner import Spinner
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.image import Image
from kivy.clock import Clock
from kivy.app import App
from kivy.core.image import Image as CoreImage
from kivy.utils import escape_markup
import chat_crypto
import qr_exchange
import tls_config
import android_qr
import android_auth
import room_store
# Note: kivy.clipboard not available on Android

QR_TIMEOUT = 60  # seconds a key/room QR stays on screen
QR_MAX_VERSION = 25  # larger QR codes may not scan reliably off a phone screen
LOCKED_TEXT = 'Locked - tap to unlock'  # saved-rooms spinner text until the user unlocks

class ConnectionScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.main_app = None

        # Saved rooms live in the app's data folder, which app updates leave alone
        running = App.get_running_app()
        room_store.init(running.user_data_dir if running else '.')
        self._rooms_unlocked = not room_store.encrypted()
        
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
            text='Mcutie Chat', 
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

        # TLS toggle (switches the default port 1883 <-> 8883)
        tls_layout = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height='50dp',
            spacing=15
        )
        tls_label = Label(
            text='Use TLS:',
            size_hint_x=0.7,
            font_size='16sp'
        )
        self.tls_checkbox = CheckBox(size_hint_x=0.3, size_hint_y=None, height='40dp')
        self.tls_checkbox.bind(active=self.toggle_tls)
        tls_layout.add_widget(tls_label)
        tls_layout.add_widget(self.tls_checkbox)
        layout.add_widget(tls_layout)

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

        # Broker CA certificate (TLS only): pinned if set, else publicly trusted CAs
        ca_label = Label(
            text='Broker CA certificate (optional, PEM):',
            size_hint_y=None,
            height='40dp',
            font_size='16sp'
        )
        layout.add_widget(ca_label)
        self.ca_input = TextInput(
            hint_text='Leave empty for publicly trusted brokers (Let\'s Encrypt)',
            size_hint_y=None,
            height='100dp',
            font_size='12sp',
            multiline=True
        )
        self.ca_input.bind(text=self.update_ca_status)
        layout.add_widget(self.ca_input)
        self.ca_status_label = Label(
            text='',
            size_hint_y=None,
            height='35dp',
            font_size='13sp',
            color=[0.6, 0.6, 0.6, 1]
        )
        self.ca_status_label.bind(size=lambda inst, size: setattr(inst, 'text_size', (size[0], None)))
        layout.add_widget(self.ca_status_label)
        if not android_qr.IS_ANDROID:
            # Desktop: load the CA from a file (stored as PEM text like a pasted one)
            ca_file_layout = BoxLayout(
                orientation='horizontal',
                size_hint_y=None,
                height='50dp',
                spacing=10
            )
            self.ca_path_input = TextInput(
                hint_text='CA file path (.pem / .crt)',
                size_hint_x=0.7,
                font_size='14sp',
                multiline=False
            )
            ca_load_button = Button(
                text='Load CA',
                size_hint_x=0.3,
                font_size='15sp'
            )
            ca_load_button.bind(on_release=self.load_ca_file)
            ca_file_layout.add_widget(self.ca_path_input)
            ca_file_layout.add_widget(ca_load_button)
            layout.add_widget(ca_file_layout)

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

        # QR exchange: full-room QR for new users, and import by camera scan
        qr_row = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height='60dp',
            spacing=10
        )
        self.room_qr_button = Button(
            text='Room QR',
            size_hint_x=0.5,
            font_size='15sp',
            size_hint_y=None,
            height='55dp',
            background_color=[0.3, 0.6, 0.9, 1]
        )
        self.room_qr_button.bind(on_release=self.show_room_qr)
        self.scan_qr_button = Button(
            text='Scan QR',
            size_hint_x=0.5,
            font_size='15sp',
            size_hint_y=None,
            height='55dp'
        )
        self.scan_qr_button.bind(on_release=self.scan_qr)
        qr_row.add_widget(self.room_qr_button)
        qr_row.add_widget(self.scan_qr_button)
        layout.add_widget(qr_row)

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
        
        # Encrypted (Android): nothing is listed until the user taps and unlocks
        self.room_spinner = Spinner(
            text=LOCKED_TEXT if room_store.encrypted() else 'Load Room',
            values=[] if room_store.encrypted() else self.get_saved_rooms(),
            size_hint_y=None, 
            height='55dp',
            font_size='16sp'
        )
        self.room_spinner.bind(text=self.load_room)
        self.room_spinner.bind(on_release=self._on_spinner_tap)
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

    def toggle_tls(self, checkbox, value):
        """Switch the default port when TLS is toggled; leave custom ports alone"""
        port = self.port_input.text.strip()
        if value and port in ('', '1883'):
            self.port_input.text = '8883'
        elif not value and port == '8883':
            self.port_input.text = '1883'

    def update_ca_status(self, instance, text):
        """Describe the pasted CA, or say what's wrong with it"""
        if not text.strip():
            self.ca_status_label.text = ''
            return
        try:
            self.ca_status_label.text = tls_config.describe_ca(tls_config.validate_ca_pem(text))
        except Exception as e:
            self.ca_status_label.text = f'Invalid CA: {e}'

    def load_ca_file(self, instance):
        """Desktop: read a CA certificate file into the PEM box"""
        path = os.path.expanduser(self.ca_path_input.text.strip())
        if not path:
            self.show_popup("Enter the CA file path first!")
            return
        try:
            with open(path, 'r') as f:
                self.ca_input.text = tls_config.validate_ca_pem(f.read())
        except Exception as e:
            self.show_popup(f"Couldn't load CA certificate: {e}")

    def _tls_settings(self):
        """(tls, ca_pem) from the form, or None after showing an error popup"""
        tls = self.tls_checkbox.active
        ca = self.ca_input.text.strip()
        if ca and not tls:
            self.show_popup("Turn on TLS to use a CA certificate.")
            return None
        if ca:
            try:
                ca = tls_config.validate_ca_pem(ca)
            except ValueError as e:
                self.show_popup(f"Invalid CA certificate: {e}")
                return None
        return tls, ca

    def toggle_mqtt_password_visibility(self, checkbox, value):
        """Toggle MQTT password visibility"""
        self.mqtt_password_input.password = not value

    def generate_key(self, instance):
        """Generate a new random 256-bit encryption key (base64url)"""
        self.key_input.text = chat_crypto.generate_key()
        self.show_popup("New encryption key generated!")

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
        """Show the key-only QR (room + key) for people already on the broker"""
        room = self.room_input.text.strip()
        key = self.key_input.text.strip()
        if not key:
            self.show_popup("No encryption key to show QR code for!")
            return
        if not room:
            self.show_popup("Room name is required!")
            return
        fingerprint = self._fingerprint(key, room)
        if fingerprint:
            self._show_qr_popup('Room Key QR Code',
                                'Scan with Mcutie Chat (Scan QR)\nto import this room key',
                                qr_exchange.build_key(room, key), fingerprint)

    def show_room_qr(self, instance):
        """Show the full-room QR (broker, login, room, key) so a new user can join with one scan"""
        server = self.server_input.text.strip()
        room = self.room_input.text.strip()
        key = self.key_input.text.strip()
        try:
            port = int(self.port_input.text.strip() or "1883")
            if port <= 0 or port > 65535:
                raise ValueError("Invalid port range")
        except ValueError:
            self.show_popup("Port must be a valid number (1-65535)!")
            return
        if not server or not room or not key:
            self.show_popup("Server, room and encryption key are required for a Room QR!")
            return
        fingerprint = self._fingerprint(key, room)
        if not fingerprint:
            return
        tls_settings = self._tls_settings()
        if tls_settings is None:
            return
        tls, ca = tls_settings
        payload = qr_exchange.build_room(server, port, room, key,
                                         self.mqtt_username_input.text.strip(),
                                         self.mqtt_password_input.text.strip(),
                                         tls=tls, ca=ca)
        version = self._qr_version(payload)
        if version is None:
            self.show_popup("This room's settings are too large for a QR code.\n\n"
                            "An EC P-256 CA certificate is much smaller than an RSA one.")
            return
        size_warning = ''
        if version > QR_MAX_VERSION:
            size_warning = (f"\n\n[b]This QR is large (version {version}) and may not scan "
                            "reliably from a screen.[/b] An EC P-256 CA keeps it small.")
        self._confirm(
            'Show Room QR?',
            "This QR contains the broker password and the room key.\n\n"
            "Show it only to people you'd give both to." + size_warning,
            'Show QR',
            lambda: self._show_qr_popup('Room QR Code',
                                        'Scan with Mcutie Chat (Scan QR)\nto join this room',
                                        payload, fingerprint))

    def _qr_version(self, payload):
        """QR version the payload needs at our error-correction level, or None if it can't fit"""
        import qrcode
        from qrcode.exceptions import DataOverflowError
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L)
        qr.add_data(payload)
        try:
            qr.make(fit=True)
        except DataOverflowError:
            return None
        return qr.version

    def _fingerprint(self, key, room):
        """Fingerprint of the key as derived for this room, or None (with a popup) on error"""
        if not chat_crypto.AVAILABLE:
            self.show_popup("Cryptography package not available!")
            return None
        return chat_crypto.fingerprint(chat_crypto.key_from_input(key, room))

    def _show_qr_popup(self, title, instructions_text, payload, fingerprint):
        """Show a QR in memory only, with FLAG_SECURE, a fingerprint and a countdown"""
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
            qr.add_data(payload)
            qr.make(fit=True)

            # Create QR code image
            qr_image = qr.make_image(fill_color="black", back_color="white")
            
            # Convert PIL image to bytes
            img_buffer = io.BytesIO()
            qr_image.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            
            # Create Kivy image from bytes (nocache: keep the key out of Kivy's image cache)
            kivy_image = CoreImage(img_buffer, ext='png', nocache=True)
            # Keep modules crisp when scaled (linear filtering blurs them into an unscannable mush)
            kivy_image.texture.mag_filter = 'nearest'
            kivy_image.texture.min_filter = 'nearest'
            
            # Create popup content
            # Tight layout: the QR gets whatever height the fixed rows leave, so keep them small
            content_layout = BoxLayout(orientation='vertical', spacing=6, padding=10)
            
            # Instructions
            instructions = Label(
                text=instructions_text,
                font_size='14sp',
                halign='center',
                valign='middle',
                size_hint_y=None,
                height='40dp',
                text_size=(None, None)
            )
            content_layout.add_widget(instructions)
            
            # QR code image, drawn at a whole number of pixels per module and on whole-pixel
            # coordinates: fractional scaling or half-pixel offsets make modules uneven
            # (e.g. 2, 3 or 4 px wide), which scanners fail to read
            n_modules = qr.modules_count + 2 * qr.border
            qr_box = Widget()
            qr_widget = Image(
                texture=kivy_image.texture,
                size_hint=(None, None),
                fit_mode='fill'
            )
            def fit_qr(box, *args):
                px = max(1, int(min(box.size) // n_modules))
                side = px * n_modules
                qr_widget.size = (side, side)
                qr_widget.pos = (int(box.x + (box.width - side) / 2),
                                 int(box.y + (box.height - side) / 2))
            qr_box.bind(pos=fit_qr, size=fit_qr)
            qr_box.add_widget(qr_widget)
            content_layout.add_widget(qr_box)

            # Fingerprint for both people to read aloud, and the auto-close countdown
            fingerprint_label = Label(
                text=f'Fingerprint: [b]{fingerprint}[/b]',
                markup=True,
                font_size='20sp',
                size_hint_y=None,
                height='32dp'
            )
            content_layout.add_widget(fingerprint_label)
            countdown_label = Label(
                text=f'Closes in {QR_TIMEOUT} s',
                font_size='14sp',
                size_hint_y=None,
                height='22dp',
                color=[0.7, 0.7, 0.7, 1]
            )
            content_layout.add_widget(countdown_label)
            
            # Close button
            close_button = Button(
                text='Close',
                size_hint_y=None,
                height='44dp',
                font_size='16sp'
            )
            content_layout.add_widget(close_button)
            
            # Create popup
            popup = Popup(
                title=title,
                content=content_layout,
                size_hint=(0.96, 0.96),
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

            # Auto-close after QR_TIMEOUT seconds
            remaining = [QR_TIMEOUT]
            def tick(dt):
                remaining[0] -= 1
                countdown_label.text = f'Closes in {remaining[0]} s'
                if remaining[0] <= 0:
                    popup.dismiss()
                    return False
            ticker = Clock.schedule_interval(tick, 1)

            # However the popup closes: stop the timer, allow screenshots again, drop the QR texture
            def on_dismiss(*args):
                ticker.cancel()
                android_qr.set_secure(False)
                qr_widget.texture = None
            popup.bind(on_dismiss=on_dismiss)

            android_qr.set_secure(True)
            popup.open()
            
        except ImportError as e:
            self.show_popup(f"QR code libraries not available: {e}\nPlease check app installation.")
        except Exception as e:
            print(f"QR code generation error: {e}")
            self.show_popup(f"Error generating QR code: {e}")

    def scan_qr(self, instance):
        """Scan a room or key QR with the camera (Android only)"""
        if not android_qr.scan(self._on_qr_scanned, self.show_popup):
            self.show_popup("Scanning is only available on Android.")

    def _on_qr_scanned(self, text):
        """Validate a scanned payload and ask the user to confirm the import"""
        if text is None:
            return  # scan cancelled
        try:
            data = qr_exchange.parse(text)
        except ValueError as e:
            self.show_popup(str(e))
            return
        fingerprint = self._fingerprint(data["key"], data["room"])
        if not fingerprint:
            return
        # Scanned text is untrusted: escape it for the markup label
        room = escape_markup(data['room'])
        if data["type"] == qr_exchange.TYPE_ROOM:
            if not data["tls"]:
                tls_text = "off"
            elif data["ca"]:
                tls_text = f"on, CA: {escape_markup(tls_config.describe_ca(data['ca']))}"
            else:
                tls_text = "on, publicly trusted CAs"
            details = (f"Room: {room}\nServer: {escape_markup(data['host'])}:{data['port']}\n"
                       f"MQTT user: {escape_markup(data['mqtt_user']) or '(anonymous)'}\n"
                       f"TLS: {tls_text}")
        else:
            details = f"Room key for: {room}"
        self._confirm(
            'Import from QR?',
            f"{details}\n\nFingerprint: [b]{fingerprint}[/b]\n\n"
            "Check it matches the other person's screen.",
            'Import',
            lambda: self._import_qr(data))

    def _import_qr(self, data):
        """Fill the form from a confirmed QR payload"""
        room = data["room"]
        self.room_input.text = room
        self.key_input.text = data["key"]
        if data["type"] == qr_exchange.TYPE_ROOM:
            self.server_input.text = data["host"]
            self.port_input.text = str(data["port"])
            self.mqtt_username_input.text = data["mqtt_user"]
            self.mqtt_password_input.text = data["mqtt_pass"]
            self.tls_checkbox.active = data["tls"]
            self.port_input.text = str(data["port"])  # toggle_tls may have changed it
            self.ca_input.text = data["ca"]
            # The QR never carries a chat name: the receiver picks their own
            self.username_input.text = ''
            self.show_popup("Room imported.\n\nEnter your name, then tap Connect.")
            return
        # Key-only: also update the saved room of that name, if there is one
        key = data["key"]
        def update_saved():
            if room not in room_store.list_rooms():
                return False
            saved = room_store.load(room)
            saved["key"] = key
            room_store.save(room, saved)
            return True
        def done(updated):
            if updated:
                self._set_room_list()
                self.show_popup(f"Key imported and saved room '{room}' updated.")
            else:
                self.show_popup(f"Key imported for room '{room}'.")
        self._with_store(update_saved, done, on_locked=lambda: self.show_popup(
            f"Key imported for room '{room}'.\n\nSaved room not updated (locked)."))

    def _confirm(self, title, message, ok_text, on_ok):
        """Two-button confirmation popup; calls on_ok() if confirmed"""
        content_layout = BoxLayout(orientation='vertical', spacing=20, padding=20)
        message_label = Label(
            text=message,
            markup=True,
            font_size='16sp',
            halign='center',
            valign='middle',
            text_size=(None, None)
        )
        content_layout.add_widget(message_label)
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
            background_color=[0.5, 0.5, 0.5, 1]
        )
        ok_button = Button(
            text=ok_text,
            size_hint_x=0.5,
            font_size='16sp'
        )
        button_layout.add_widget(cancel_button)
        button_layout.add_widget(ok_button)
        content_layout.add_widget(button_layout)
        popup = Popup(
            title=title,
            content=content_layout,
            size_hint=(0.9, 0.6),
            auto_dismiss=False
        )
        cancel_button.bind(on_release=popup.dismiss)
        def confirmed(instance):
            popup.dismiss()
            on_ok()
        ok_button.bind(on_release=confirmed)
        def update_label_size(dt):
            message_label.text_size = (popup.width - 40, None)
        Clock.schedule_once(update_label_size, 0.1)
        popup.open()

    def copy_room_config(self, instance):
        """Copy room configuration as shareable text"""
        config_text = f"""Mcutie Chat Room Config:
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
        """Saved room names (desktop; on Android the list needs an unlock first)"""
        try:
            return room_store.list_rooms()
        except room_store.RoomStoreError:
            return []

    def _with_store(self, action, on_ok=None, on_locked=None, _retry=True):
        """Run a saved-rooms action. If saved rooms are locked, prompt once and
        retry. Never lets a storage error escape."""
        try:
            result = action()
        except room_store.LockedError:
            if not _retry:
                self.show_popup("Could not unlock saved rooms.")
                if on_locked:
                    on_locked()
                return
            self._unlock(lambda: self._with_store(action, on_ok, on_locked, _retry=False),
                         on_locked)
            return
        except room_store.InvalidatedError:
            self._show_locked()
            self._confirm(
                "Saved rooms locked",
                "Saved rooms can't be decrypted: the phone's screen lock was removed, "
                "so Android deleted the key that protected them.\n\n"
                "Clear them, then re-scan your Room QRs.",
                "Clear saved rooms", self._clear_saved_rooms)
            return
        except room_store.RoomStoreError as e:
            self.show_popup(str(e))  # fixed, non-secret messages only
            return
        except Exception as e:
            print(f"Saved rooms error: {type(e).__name__}")  # never the message: it may hold data
            self.show_popup("Saved rooms: unexpected error.")
            return
        if on_ok:
            on_ok(result)

    def _unlock(self, then, on_locked=None):
        """One fingerprint/PIN prompt unwraps the saved-rooms data key for this
        app session (the Keystore key needs a fresh prompt for every use)"""
        def prompt():
            cipher = room_store.begin_unlock()
            def done(outcome):
                if outcome == "ok":
                    self._with_store(lambda: room_store.finish_unlock(cipher),
                                     lambda _: then(), on_locked, _retry=False)
                    return
                if outcome == "error":
                    self.show_popup("Could not show the unlock prompt.")
                if on_locked:
                    on_locked()
            android_auth.authenticate(cipher, done)
        self._with_store(prompt, None, on_locked, _retry=False)

    def _set_room_list(self, rooms=None):
        """Show saved rooms in the spinner (after an unlock or a change)"""
        if rooms is None:
            try:
                rooms = room_store.list_rooms()  # in-memory once unlocked
            except room_store.RoomStoreError:
                return
        self._rooms_unlocked = True
        self.room_spinner.values = rooms
        if self.room_spinner.text == LOCKED_TEXT:
            self.room_spinner.text = 'Load Room'

    def _show_locked(self):
        """No rooms shown until the user unlocks"""
        self._rooms_unlocked = False
        self.room_spinner.values = []
        self.room_spinner.text = LOCKED_TEXT

    def _on_spinner_tap(self, spinner):
        """While locked, a tap asks to unlock instead of opening the (empty) list"""
        if self._rooms_unlocked:
            return False
        def unlocked(rooms):
            self._set_room_list(rooms)
            notes = room_store.notes()
            if notes:
                self.show_popup("\n".join(notes))
            elif rooms:
                Clock.schedule_once(lambda dt: setattr(spinner, 'is_open', True))
        self._with_store(room_store.list_rooms, unlocked, on_locked=self._show_locked)
        return True  # handlers bound later run first: this stops the Spinner's own toggle

    def _clear_saved_rooms(self):
        """After the key was invalidated: delete the undecryptable rooms and the key"""
        try:
            room_store.clear_all()
        except Exception as e:
            print(f"Clearing saved rooms failed: {type(e).__name__}")
        self._set_room_list([])
        self.room_spinner.text = 'Load Room'
        self.show_popup("Saved rooms cleared.\n\nRe-scan your Room QRs to add them again.")

    def load_room(self, spinner, room_name):
        """Load a saved room configuration"""
        if room_name in ('Load Room', LOCKED_TEXT):
            return

        def fill(data):
            self.username_input.text = data.get("username", "User")
            self.server_input.text = data.get("server", "localhost")
            self.port_input.text = str(data.get("port", "1883"))
            self.room_input.text = data.get("room", "general")
            self.key_input.text = data.get("key", "")
            self.mqtt_username_input.text = data.get("mqtt_username", "")
            self.mqtt_password_input.text = data.get("mqtt_password", "")
            self.tls_checkbox.active = bool(data.get("tls", False))
            self.port_input.text = str(data.get("port", "1883"))  # toggle_tls may have changed it
            self.ca_input.text = data.get("ca", "")
        self._with_store(lambda: room_store.load(room_name), fill, on_locked=self._show_locked)

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
                "mqtt_password": self.mqtt_password_input.text.strip(),
                "tls": self.tls_checkbox.active,
                "ca": self.ca_input.text.strip()
            }
            
        except ValueError:
            self.show_popup("Port must be a valid number (1-65535)!")
            return

        def saved(_):
            self._set_room_list()
            self.show_popup("Room configuration saved!")
        self._with_store(lambda: room_store.save(name, data), saved, on_locked=lambda: self.show_popup(
            "Room not saved: saved rooms are locked."))

    def delete_room(self, instance):
        """Delete a saved room configuration with confirmation"""
        if self.room_spinner.text in ('Load Room', LOCKED_TEXT) or not self.room_spinner.text:
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
        def deleted(_):
            self._set_room_list()
            self.room_spinner.text = 'Load Room'
            self.show_popup(f"Room '{room_name}' has been deleted successfully!")
        self._with_store(lambda: room_store.delete(room_name), deleted, on_locked=self._show_locked)

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
            tls_settings = self._tls_settings()
            if tls_settings is None:
                return
            tls, ca = tls_settings
            self.main_app.connect_to_mqtt(server, port_int, room, key, mqtt_user, mqtt_pass,
                                          tls=tls, ca_pem=ca)
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