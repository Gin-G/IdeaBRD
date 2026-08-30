package net.nickknows.ideabrd

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Where the GitHub token lives on the device.
 *
 * The token is the whole of the app's authority: it can read and write every
 * repository the person granted it. Storing it in ordinary preferences would
 * put it in a file that any backup, any rooted device and any adb pull can
 * read, so it is encrypted with a key held in the Android Keystore — hardware
 * backed where the device has it. The key never leaves that store; this file
 * only ever holds ciphertext.
 *
 * There is deliberately no way to read the token from the web layer. The board
 * page asks whether it is signed in and who as; the token itself stays on this
 * side of the bridge, where a bug in the page cannot leak it.
 */
object TokenStore {

    private const val FILE = "ideabrd-credentials"
    private const val KEY_TOKEN = "github_token"
    private const val KEY_LOGIN = "github_login"

    // A device-flow sign-in that has been started but not finished. It lives
    // here rather than in memory because finishing it means leaving the app —
    // that is the whole shape of the flow — and Android is free to reclaim a
    // backgrounded app while the person is in the browser authorising it. If
    // this were only in memory, coming back would find the app with no idea a
    // sign-in was ever in progress, while GitHub holds an authorised grant
    // nobody will ever collect.
    private const val KEY_DEVICE_CODE = "device_code"
    private const val KEY_USER_CODE = "user_code"
    private const val KEY_DEVICE_EXPIRES = "device_expires_at"
    private const val KEY_DEVICE_INTERVAL = "device_interval"

    private fun prefs(context: Context): SharedPreferences {
        val key = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        return EncryptedSharedPreferences.create(
            context,
            FILE,
            key,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    fun save(context: Context, token: String, login: String?) {
        prefs(context).edit().putString(KEY_TOKEN, token).putString(KEY_LOGIN, login).apply()
    }

    fun token(context: Context): String? = prefs(context).getString(KEY_TOKEN, null)

    fun login(context: Context): String? = prefs(context).getString(KEY_LOGIN, null)

    fun clear(context: Context) {
        prefs(context).edit().clear().apply()
    }

    /** A device-flow sign-in waiting on the person to type the code. */
    data class Pending(
        val deviceCode: String,
        val userCode: String,
        val expiresAt: Long,
        val interval: Int,
    )

    fun savePending(context: Context, pending: Pending) {
        prefs(context).edit()
            .putString(KEY_DEVICE_CODE, pending.deviceCode)
            .putString(KEY_USER_CODE, pending.userCode)
            .putLong(KEY_DEVICE_EXPIRES, pending.expiresAt)
            .putInt(KEY_DEVICE_INTERVAL, pending.interval)
            .apply()
    }

    /** The sign-in in progress, or null if there isn't one or it has expired. */
    fun pending(context: Context): Pending? {
        val prefs = prefs(context)
        val deviceCode = prefs.getString(KEY_DEVICE_CODE, null) ?: return null
        val expiresAt = prefs.getLong(KEY_DEVICE_EXPIRES, 0)
        if (expiresAt <= System.currentTimeMillis()) {
            clearPending(context)
            return null
        }
        return Pending(
            deviceCode = deviceCode,
            userCode = prefs.getString(KEY_USER_CODE, "").orEmpty(),
            expiresAt = expiresAt,
            interval = prefs.getInt(KEY_DEVICE_INTERVAL, 5),
        )
    }

    fun clearPending(context: Context) {
        prefs(context).edit()
            .remove(KEY_DEVICE_CODE)
            .remove(KEY_USER_CODE)
            .remove(KEY_DEVICE_EXPIRES)
            .remove(KEY_DEVICE_INTERVAL)
            .apply()
    }
}
