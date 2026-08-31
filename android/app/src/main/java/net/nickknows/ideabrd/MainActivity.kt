package net.nickknows.ideabrd

import android.os.Bundle
import android.view.View
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import com.getcapacitor.BridgeActivity

/**
 * The shell.
 *
 * The app is the same SvelteKit board that runs in a browser, loaded from
 * assets instead of over the network, plus two native plugins for the things a
 * web page cannot do: talk to git, and hold a token somewhere the operating
 * system protects.
 */
class MainActivity : BridgeActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        // Registration has to happen before the bridge is built, or the web
        // layer starts up without knowing these plugins exist. Both plugins
        // live in this module, so `assets/capacitor.plugins.json` — the list
        // Capacitor reads to find plugins shipped as npm packages — is empty
        // rather than absent: without the file it logs a PluginLoadException
        // on every launch, which reads like the cause of whatever you are
        // actually debugging.
        registerPlugin(BoardPlugin::class.java)
        registerPlugin(AuthPlugin::class.java)
        super.onCreate(savedInstanceState)
        keepContentOutFromUnderTheSystemBars()
    }

    /**
     * Pad the web layer in by whatever the status and navigation bars cover.
     *
     * From Android 15, an app targeting SDK 35 gets the whole screen whether it
     * asked for it or not: the system stops insetting the window and draws its
     * bars on top. For a page that puts controls in a header, that means the
     * clock and the battery sitting on the buttons.
     *
     * The board is not a photo viewer and gains nothing from drawing under
     * them, so the insets are simply turned into padding on the content view.
     * The window background shows through behind the bars, which is the same
     * dark the header already is. Reported rather than consumed, so anything
     * else that wants to know — the keyboard, in particular — still hears.
     */
    private fun keepContentOutFromUnderTheSystemBars() {
        val content = findViewById<View>(android.R.id.content)
        ViewCompat.setOnApplyWindowInsetsListener(content) { view, insets ->
            val bars = insets.getInsets(
                WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout(),
            )
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
        // Dark bars behind light content: tell the system to draw its icons
        // light, or the clock is near-black on near-black.
        WindowCompat.getInsetsController(window, content).isAppearanceLightStatusBars = false
    }
}
