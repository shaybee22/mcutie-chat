"""Android-only: the prompt that authorizes one use of the saved-rooms Keystore key.

authenticate(cipher, on_done) shows the framework BiometricPrompt with a
CryptoObject around `cipher` (from room_store.begin_unlock()), allowing a
strong biometric or the screen-lock PIN/pattern/password. The key needs a
prompt for every use (timeout 0), so only a success here lets that exact
cipher run; unlocking the phone doesn't. on_done(result) runs on the Kivy
thread with result "ok", "cancelled", "failed" or "error".

Needs Android 11 (API 30) for BIOMETRIC_STRONG | DEVICE_CREDENTIAL with a
CryptoObject; buildozer.spec sets android.minapi = 30. The callback is an
abstract class, which pyjnius can't subclass, so it goes through
src/org/seumas/mcutiechat/AuthCallback.java.

On other platforms authenticate() reports "error" (there is no Keystore there).
"""
from kivy.clock import Clock
from kivy.utils import platform

IS_ANDROID = platform == "android"

if IS_ANDROID:
    from jnius import autoclass, cast, PythonJavaClass, java_method
    from android.runnable import run_on_ui_thread

    PythonActivity = autoclass("org.kivy.android.PythonActivity")

    TITLE = "Unlock saved rooms"
    SUBTITLE = "Use your fingerprint or screen lock"

    _pending = None   # on_done of the prompt that is showing
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
    def _show_prompt(cipher):
        try:
            activity = PythonActivity.mActivity
            String = autoclass("java.lang.String")
            Builder = autoclass("android.hardware.biometrics.BiometricPrompt$Builder")
            CryptoObject = autoclass("android.hardware.biometrics.BiometricPrompt$CryptoObject")
            Authenticators = autoclass("android.hardware.biometrics.BiometricManager$Authenticators")
            CancellationSignal = autoclass("android.os.CancellationSignal")
            AuthCallback = autoclass("org.seumas.mcutiechat.AuthCallback")

            builder = Builder(activity)
            builder.setTitle(String(TITLE))
            builder.setSubtitle(String(SUBTITLE))
            builder.setAllowedAuthenticators(Authenticators.BIOMETRIC_STRONG
                                             | Authenticators.DEVICE_CREDENTIAL)
            prompt = builder.build()
            # cast: pyjnius scores every object argument alike unless the type matches exactly
            crypto = CryptoObject(cast("javax.crypto.Cipher", cipher))
            listener = _Listener()
            callback = AuthCallback(listener)
            signal = CancellationSignal()
            _keep.extend([listener, callback, signal, prompt, crypto])
            prompt.authenticate(crypto, signal, activity.getMainExecutor(), callback)
        except Exception as e:
            # Errors here run on Android's UI thread and would otherwise vanish silently
            print(f"android_auth: prompt failed ({type(e).__name__})")
            _finish("error")

    def authenticate(cipher, on_done):
        global _pending
        if _pending is not None:
            return  # a prompt is already showing; ignore the second tap
        _pending = on_done
        _show_prompt(cipher)

else:
    def authenticate(cipher, on_done):
        Clock.schedule_once(lambda dt: on_done("error"))
