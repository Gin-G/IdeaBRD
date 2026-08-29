package net.nickknows.ideabrd

import android.os.Bundle
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
    }
}
