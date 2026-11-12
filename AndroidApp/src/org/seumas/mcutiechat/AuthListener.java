package org.seumas.mcutiechat;

/** Implemented in Python (android_auth.py) with a pyjnius PythonJavaClass. */
public interface AuthListener {
    /** code is one of AuthCallback.OK, CANCELLED or FAILED. */
    void onAuthResult(int code);
}
