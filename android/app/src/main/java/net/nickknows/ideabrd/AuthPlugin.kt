package net.nickknows.ideabrd

import com.getcapacitor.JSArray
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import java.util.concurrent.Executors

/**
 * Signing in to GitHub from the device, with the device flow.
 *
 * The web app signs in by redirecting to GitHub and back through the server,
 * which works because the server can hold a client secret. An app distributed
 * to people cannot: whatever is in the APK is in everybody's APK, so an
 * authorization-code flow here would ship a secret to every install.
 *
 * The device flow is GitHub's answer to exactly that. The app asks for a code,
 * shows the person a short string to type at github.com/login/device on
 * whatever device is convenient, and polls until they have. Nothing secret is
 * ever in the app, and the token that comes back is stored by [TokenStore],
 * encrypted under a Keystore key.
 *
 * The token never crosses back over the bridge. The board page can ask whether
 * it is signed in and as whom, and that is all it needs to know.
 */
@CapacitorPlugin(name = "Auth")
class AuthPlugin : Plugin() {

    // The scopes a git-only board actually needs: repo access to read and write
    // the board repo and the idea repos linked from it, and the user's own
    // identity to show who is signed in.
    private val scope = "repo read:user user:email read:org"

    private val work = Executors.newSingleThreadExecutor()

    @Volatile private var polling = false

    @PluginMethod
    fun status(call: PluginCall) {
        val context = context ?: return call.reject("No context")
        val result = JSObject()
        result.put("authenticated", TokenStore.token(context) != null)
        result.put("login", TokenStore.login(context))
        result.put("clientIdConfigured", clientId(call).isNotEmpty())
        call.resolve(result)
    }

    /**
     * Ask GitHub for a code and hand it to the page to display.
     *
     * Nothing is authorised yet at this point — the person has to go and type
     * the code. [poll] is what waits for that.
     */
    @PluginMethod
    fun start(call: PluginCall) {
        val id = clientId(call)
        if (id.isEmpty()) {
            return call.reject(
                "No GitHub client id. Build with IDEABRD_GITHUB_CLIENT_ID set, " +
                    "or pass clientId from the server's provider settings."
            )
        }
        work.execute {
            try {
                val code = GitHubApi.requestDeviceCode(id, scope)
                val result = JSObject()
                result.put("deviceCode", code.deviceCode)
                result.put("userCode", code.userCode)
                result.put("verificationUri", code.verificationUri)
                result.put("interval", code.intervalSeconds)
                result.put("expiresIn", code.expiresInSeconds)
                call.resolve(result)
            } catch (e: Exception) {
                call.reject(e.message ?: "Could not reach GitHub", e)
            }
        }
    }

    /**
     * Wait for the person to authorise the code, then keep the token.
     *
     * Polling happens here rather than in the page so that GitHub's rules about
     * it — the minimum interval, and the slow_down that revokes the code if
     * ignored — are enforced in one place by the code that knows them.
     */
    @PluginMethod
    fun poll(call: PluginCall) {
        val context = context ?: return call.reject("No context")
        val id = clientId(call)
        val deviceCode = call.getString("deviceCode")
            ?: return call.reject("deviceCode is required")
        var interval = call.getInt("interval") ?: 5
        val deadline = System.currentTimeMillis() + (call.getInt("expiresIn") ?: 900) * 1000L

        if (polling) return call.reject("Already waiting for a code")
        polling = true
        work.execute {
            try {
                while (System.currentTimeMillis() < deadline) {
                    Thread.sleep(interval * 1000L)
                    when (val result = GitHubApi.pollForToken(id, deviceCode, interval)) {
                        is GitHubApi.TokenResult.Granted -> {
                            val login = GitHubApi.login(result.token)
                            TokenStore.save(context, result.token, login)
                            val out = JSObject()
                            out.put("authenticated", true)
                            out.put("login", login)
                            return@execute call.resolve(out)
                        }
                        is GitHubApi.TokenResult.Pending -> interval = result.interval
                        is GitHubApi.TokenResult.Failed ->
                            return@execute call.reject(result.error)
                    }
                }
                call.reject("The code expired before it was authorised")
            } catch (e: InterruptedException) {
                call.reject("Sign-in was interrupted")
            } catch (e: Exception) {
                call.reject(e.message ?: "Sign-in failed", e)
            } finally {
                polling = false
            }
        }
    }

    /**
     * Where a new repository could be created: the signed-in account, plus any
     * organisation the token can see.
     *
     * The organisation list is empty without the `read:org` scope, which a
     * token minted before the app asked for it will not have — so the account
     * is always first and always present, and a shorter list means "reconnect",
     * not "you have no organisations".
     */
    @PluginMethod
    fun owners(call: PluginCall) {
        val context = context ?: return call.reject("No context")
        val token = TokenStore.token(context) ?: return call.reject("Sign in to GitHub first")
        work.execute {
            try {
                val login = TokenStore.login(context) ?: GitHubApi.login(token)
                val owners = JSArray()
                if (login != null) {
                    owners.put(JSObject().put("login", login).put("kind", "user"))
                }
                GitHubApi.orgs(token).forEach {
                    owners.put(JSObject().put("login", it).put("kind", "org"))
                }
                call.resolve(JSObject().put("owners", owners))
            } catch (e: Exception) {
                call.reject(e.message ?: "Could not reach GitHub", e)
            }
        }
    }

    @PluginMethod
    fun signOut(call: PluginCall) {
        val context = context ?: return call.reject("No context")
        TokenStore.clear(context)
        call.resolve()
    }

    private fun clientId(call: PluginCall): String =
        call.getString("clientId")?.takeIf { it.isNotEmpty() } ?: BuildConfig.GITHUB_CLIENT_ID
}
