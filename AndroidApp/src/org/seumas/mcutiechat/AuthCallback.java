package org.seumas.mcutiechat;

import android.annotation.TargetApi;
import android.hardware.biometrics.BiometricPrompt;

/**
 * BiometricPrompt.AuthenticationCallback is an abstract class, which pyjnius
 * can't subclass (it only implements interfaces), so this forwards the result
 * to an AuthListener implemented in Python. Used on API 30+ only.
 */
@TargetApi(30)
public class AuthCallback extends BiometricPrompt.AuthenticationCallback {
    public static final int OK = 0;
    public static final int CANCELLED = 1;
    public static final int FAILED = 2;

    private final AuthListener listener;

    public AuthCallback(AuthListener listener) {
        this.listener = listener;
    }

    @Override
    public void onAuthenticationSucceeded(BiometricPrompt.AuthenticationResult result) {
        listener.onAuthResult(OK);
    }

    @Override
    public void onAuthenticationError(int errorCode, CharSequence errString) {
        // No negative button: with DEVICE_CREDENTIAL allowed, the prompt offers the PIN instead
        boolean cancelled = errorCode == BiometricPrompt.BIOMETRIC_ERROR_USER_CANCELED
                || errorCode == BiometricPrompt.BIOMETRIC_ERROR_CANCELED;
        listener.onAuthResult(cancelled ? CANCELLED : FAILED);
    }

    // onAuthenticationFailed (one unrecognised finger) is not final: the prompt stays open.
}
