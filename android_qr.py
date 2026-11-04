"""Android-only helpers for QR exchange: FLAG_SECURE and the ZXing scanner.

On other platforms set_secure() does nothing and scan() returns False.
The scanner is com.journeyapps:zxing-android-embedded (see buildozer.spec).
Its CaptureActivity is started with a plain Intent rather than through
IntentIntegrator/ScanContract: pyjnius' autoclass(IntentIntegrator) fails
(NoClassDefFoundError androidx.fragment.app.Fragment, which the library doesn't
bundle), and ScanContract needs an AndroidX ComponentActivity. The extra names
below are the library's Intents.Scan constants.
"""
from kivy.clock import Clock
from kivy.utils import platform

IS_ANDROID = platform == "android"

if IS_ANDROID:
    from jnius import autoclass
    from android import activity as android_activity
    from android.runnable import run_on_ui_thread

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    LayoutParams = autoclass("android.view.WindowManager$LayoutParams")

    SCAN_REQUEST_CODE = 0x5C4  # arbitrary, only needs to be unique within this app
    RESULT_OK = -1             # android.app.Activity.RESULT_OK

    _pending_callback = None
    _bound = False

    @run_on_ui_thread
    def set_secure(enabled):
        """Block screenshots/screen recording of the app window while enabled."""
        window = PythonActivity.mActivity.getWindow()
        if enabled:
            window.addFlags(LayoutParams.FLAG_SECURE)
        else:
            window.clearFlags(LayoutParams.FLAG_SECURE)

    def _on_activity_result(request_code, result_code, intent):
        global _pending_callback
        if request_code != SCAN_REQUEST_CODE or _pending_callback is None:
            return
        contents = None
        if result_code == RESULT_OK and intent is not None:
            contents = intent.getStringExtra("SCAN_RESULT")
        callback, _pending_callback = _pending_callback, None
        Clock.schedule_once(lambda dt: callback(contents))

    @run_on_ui_thread
    def _start_scan(on_error):
        global _pending_callback
        try:
            Intent = autoclass("android.content.Intent")
            activity = PythonActivity.mActivity
            intent = Intent("com.google.zxing.client.android.SCAN")
            # (String, String) overload: pyjnius can't pick (Context, String) for the activity
            intent.setClassName(activity.getPackageName(),
                                "com.journeyapps.barcodescanner.CaptureActivity")
            intent.putExtra("SCAN_FORMATS", "QR_CODE")
            intent.putExtra("PROMPT_MESSAGE", "Scan a MQTT Chat QR code")
            intent.putExtra("BEEP_ENABLED", False)
            activity.startActivityForResult(intent, SCAN_REQUEST_CODE)
        except Exception as e:
            # Errors here run on Android's UI thread and would otherwise vanish silently
            print(f"QR scanner launch failed: {e}")
            _pending_callback = None
            Clock.schedule_once(lambda dt: on_error(f"Could not start the QR scanner: {e}"))

    def scan(callback, on_error):
        """Open the camera scanner; callback(text) runs on the Kivy thread, text is None if cancelled.
        on_error(message) runs on the Kivy thread if the scanner can't be started."""
        global _pending_callback, _bound
        if not _bound:
            android_activity.bind(on_activity_result=_on_activity_result)
            _bound = True
        _pending_callback = callback
        _start_scan(on_error)
        return True

else:
    def set_secure(enabled):
        pass

    def scan(callback, on_error):
        return False
