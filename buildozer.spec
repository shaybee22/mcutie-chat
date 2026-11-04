[app]

# (str) Title of your application
title = MQTT Chat

# (str) Package name
package.name = mqttchat

# (str) Package domain (needed for android/ios packaging)
package.domain = org.example

# (str) Source code where the main.py live
source.dir = .

# (str) Main script filename
source.main = main.py

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,png,jpg,kv,atlas,json

# (list) Directories to exclude from the APK
source.exclude_dirs = tools, bin, p4a-recipes

# (str) Application versioning (method 1)
version = 0.3

# (list) Application requirements
# comma separated e.g. requirements = sqlite3,kivy
# charset_normalizer (pulled in by kivy -> requests) is listed explicitly, with an underscore,
# so p4a's resolver doesn't add its Android binary wheel (which p4a then installs with the
# host pip, which rejects it). Build with PIP_NO_BINARY=charset-normalizer so the host pip
# builds it as pure Python instead of bundling its x86_64 wheel.
# paho_mqtt uses the underscore spelling for the same reason: with a hyphen, p4a's resolver
# ignores the pin and adds the latest paho-mqtt wheel, which conflicts with it.
requirements = python3,kivy==2.3.1,paho_mqtt==2.1.0,cryptography,qrcode,pillow,charset_normalizer

# (list) Supported orientations
# Valid options are: landscape, portrait, portrait-reversed or landscape-reversed
orientation = portrait

#
# Android specific
#

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (list) Permissions
android.permissions = INTERNET, ACCESS_NETWORK_STATE

# (list) The Android archs to build for, choices: armeabi-v7a, arm64-v8a, x86, x86_64
android.archs = arm64-v8a

# (bool) enables Android auto backup feature (Android API >=23)
android.allow_backup = True

# (str) Local p4a recipe overrides (cryptography: link the Rust extension against libpython)
p4a.local_recipes = ./p4a-recipes

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 1
