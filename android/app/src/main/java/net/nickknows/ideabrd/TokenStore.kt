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
}
