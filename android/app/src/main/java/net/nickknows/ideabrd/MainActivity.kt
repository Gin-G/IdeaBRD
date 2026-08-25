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
        // layer starts up without knowing these plugins exist.
        registerPlugin(BoardPlugin::class.java)
        registerPlugin(AuthPlugin::class.java)
        super.onCreate(savedInstanceState)
    }
}
