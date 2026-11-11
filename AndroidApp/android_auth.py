"""Android-only: ask the user to authenticate so the saved-rooms Keystore key opens.

unlock(on_done) shows the system prompt; on_done(result) runs on the Kivy
thread with result "ok", "cancelled", "failed" or "error".

API 30+: the framework android.hardware.biometrics.BiometricPrompt, allowing a
strong biometric or the screen-lock PIN/pattern/password. No CryptoObject: the
key is time-bound (room_store.AUTH_SECONDS), so any recent authentication opens
it, including unlocking the phone itself. The callback is an abstract class,
so it goes through src/org/seumas/mcutiechat/AuthCallback.java.

API 24-29: KeyguardManager's confirm-credential screen, with its result
delivered through on_activity_result (like android_qr's scanner).

On other platforms unlock() reports "ok" straight away (there is nothing to unlock).
"""
from kivy.clock import Clock
from kivy.utils import platform

IS_ANDROID = platform == "android"

if IS_ANDROID:
    from jnius import autoclass, cast, PythonJavaClass, java_method
    from android import activity as android_activity
    from android.runnable import run_on_ui_thread

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    SDK_INT = autoclass("android.os.Build$VERSION").SDK_INT

    CONFIRM_REQUEST_CODE = 0x5C5  # android_qr uses 0x5C4
    RESULT_OK = -1
    TITLE = "Unlock saved rooms"
    SUBTITLE = "Use your fingerprint or screen lock"

    _pending = None   # on_done of the prompt that is showing
    _bound = False
    _keep = []        # Java objects that must outlive the prompt (listener, callback, signal)

    def _finish(result):
        global _pending
        callback, _pending = _pending, None
        held = list(_keep)  # Java may still be inside the listener's call: hold refs a frame longer
        _keep.clear()

        def deliver(dt):
            held.clear()
            if callback is not None:
                callback(result)
        Clock.schedule_once(deliver)

    class _Listener(PythonJavaClass):
        __javainterfaces__ = ["org/seumas/mcutiechat/AuthListener"]
        __javacontext__ = "app"

        @java_method("(I)V")
        def onAuthResult(self, code):
            _finish({0: "ok", 1: "cancelled", 2: "failed"}.get(code, "error"))

    @run_on_ui_thread
    def _show_biometric_prompt():
        try:
            activity = PythonActivity.mActivity
            String = autoclass("java.lang.String")
            Builder = autoclass("android.hardware.biometrics.BiometricPrompt$Builder")
            Authenticators = autoclass("android.hardware.biometrics.BiometricManager$Authenticators")
            CancellationSignal = autoclass("android.os.CancellationSignal")
            AuthCallback = autoclass("org.seumas.mcutiechat.AuthCallback")

            builder = Builder(activity)
            builder.setTitle(String(TITLE))
            builder.setSubtitle(String(SUBTITLE))
            builder.setAllowedAuthenticators(Authenticators.BIOMETRIC_STRONG
                                             | Authenticators.DEVICE_CREDENTIAL)
            prompt = builder.build()
            listener = _Listener()
            callback = AuthCallback(listener)
            signal = CancellationSignal()
            _keep.extend([listener, callback, signal, prompt])
            prompt.authenticate(signal, activity.getMainExecutor(), callback)
        except Exception as e:
            # Errors here run on Android's UI thread and would otherwise vanish silently
            print(f"android_auth: prompt failed ({type(e).__name__})")
            _finish("error")

    def _on_activity_result(request_code, result_code, intent):
        if request_code == CONFIRM_REQUEST_CODE and _pending is not None:
            _finish("ok" if result_code == RESULT_OK else "cancelled")

    @run_on_ui_thread
    def _show_confirm_credential():
        try:
            String = autoclass("java.lang.String")
            Context = autoclass("android.content.Context")
            activity = PythonActivity.mActivity
            km = cast("android.app.KeyguardManager",
                      activity.getSystemService(Context.KEYGUARD_SERVICE))
            intent = km.createConfirmDeviceCredentialIntent(String(TITLE), String(SUBTITLE))
            if intent is None:  # no secure screen lock
                _finish("failed")
                return
            activity.startActivityForResult(intent, CONFIRM_REQUEST_CODE)
        except Exception as e:
            print(f"android_auth: confirm screen failed ({type(e).__name__})")
            _finish("error")

    def unlock(on_done):
        global _pending, _bound
        if _pending is not None:
            return  # a prompt is already showing; ignore the second tap
        _pending = on_done
        if SDK_INT >= 30:
            _show_biometric_prompt()
        else:
            if not _bound:
                android_activity.bind(on_activity_result=_on_activity_result)
                _bound = True
            _show_confirm_credential()

else:
    def unlock(on_done):
        Clock.schedule_once(lambda dt: on_done("ok"))
