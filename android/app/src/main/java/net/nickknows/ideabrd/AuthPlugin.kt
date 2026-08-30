package net.nickknows.ideabrd

import android.content.ClipData
import android.content.Intent
import android.content.ClipboardManager
import android.content.Context
import android.util.Base64
import com.getcapacitor.JSArray
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.concurrent.Executors
import java.util.concurrent.Future

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
 * The device flow does need a registered OAuth app, though, and registering one
 * means somebody's GitHub account owns it — every person signing in then sees
 * that owner's name on the consent screen. So [signInWithToken] is the other
 * way in: paste an access token you made yourself. It needs nothing registered
 * anywhere, involves no third party at all, and lands in the same place — a
 * token in [TokenStore] that git and the API both accept.
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

    // A pool, not a single thread: waiting for a sign-in occupies a thread for
    // as long as the person takes, and the work that ends that wait — redeeming
    // the App Link, polling for the code — has to be able to run meanwhile. On
    // one thread the waiter blocks its own completion and the app spins forever.
    private val work = Executors.newCachedThreadPool()

    @Volatile private var polling = false

    // The poll in flight, so that starting or abandoning a sign-in can stop it
    // rather than leaving it to hold the single worker thread — and the guard
    // below — until the old code expires a quarter of an hour later.
    @Volatile private var pollTask: Future<*>? = null

    // Why the last App Link handoff failed, for the waiter to report.
    @Volatile private var handoff: String? = null

    @PluginMethod
    fun status(call: PluginCall) {
        val context = context ?: return call.reject("No context")
        val result = JSObject()
        result.put("authenticated", TokenStore.token(context) != null)
        result.put("login", TokenStore.login(context))
        result.put("clientIdConfigured", clientId(call).isNotEmpty())
        result.put("serverSignInConfigured", serverUrl(call).isNotEmpty())
        // A sign-in the person started before the app was reclaimed. Telling
        // the page about it is what lets it put the same code back on screen
        // and go on waiting, instead of starting over with a new one and
        // stranding whatever they already authorised.
        TokenStore.pending(context)?.let {
            result.put("pendingUserCode", it.userCode)
            result.put("pendingExpiresIn", ((it.expiresAt - System.currentTimeMillis()) / 1000).toInt())
        }
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
        val context = context ?: return call.reject("No context")
        // A new code abandons whatever was being waited on.
        pollTask?.cancel(true)
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
                TokenStore.savePending(
                    context,
                    TokenStore.Pending(
                        deviceCode = code.deviceCode,
                        userCode = code.userCode,
                        expiresAt = System.currentTimeMillis() + code.expiresInSeconds * 1000L,
                        interval = code.intervalSeconds,
                    ),
                )
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
     * Sign in with a token the person made themselves.
     *
     * A personal access token is the same kind of credential the device flow
     * ends up with, so everything downstream — git over HTTPS, the REST API —
     * is identical. What it avoids is the registration: no OAuth app, no client
     * id, nobody's account named on a consent screen. The cost is that the
     * person has to go and make the token, and choose its scope correctly,
     * which is why a classic token missing `repo` is rejected here rather than
     * left to fail later at clone time with a git error that explains nothing.
     */
    @PluginMethod
    fun signInWithToken(call: PluginCall) {
        val context = context ?: return call.reject("No context")
        val token = call.getString("token")?.trim().orEmpty()
        if (token.isEmpty()) return call.reject("Paste a token first")
        work.execute {
            try {
                val identity = GitHubApi.identify(token)
                if (identity == null) {
                    return@execute call.reject(
                        "GitHub did not accept that token. Check it was copied whole " +
                            "and has not expired.",
                    )
                }
                // Null scopes means a fine-grained token, which doesn't declare
                // them; only a classic token can be checked this cheaply.
                if (identity.scopes != null && "repo" !in identity.scopes) {
                    return@execute call.reject(
                        "That token has no `repo` scope, so it cannot read or write the " +
                            "board repository. Make one with `repo` ticked.",
                    )
                }
                TokenStore.save(context, token, identity.login)
                val out = JSObject()
                out.put("authenticated", true)
                out.put("login", identity.login)
                call.resolve(out)
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

        // Called with no device code, this resumes the sign-in already in
        // progress. That is the ordinary case after the app has been reclaimed:
        // the person is coming back from the browser, the grant may already be
        // waiting at GitHub, and asking for a fresh code here would abandon it.
        val stored = TokenStore.pending(context)
        val resuming = call.getString("deviceCode") == null
        val deviceCode = call.getString("deviceCode")
            ?: stored?.deviceCode
            ?: return call.reject("No sign-in is in progress")
        var interval = call.getInt("interval") ?: stored?.interval ?: 5
        val deadline = call.getInt("expiresIn")
            ?.let { System.currentTimeMillis() + it * 1000L }
            ?: stored?.expiresAt
            ?: (System.currentTimeMillis() + 900_000L)

        if (polling) return call.reject("Already waiting for a code")
        polling = true
        pollTask = work.submit {
            try {
                // Resuming polls at once: the whole point is to redeem a grant
                // that may already be sitting there. A fresh code waits first,
                // because nobody can have typed it yet.
                var immediate = resuming
                while (System.currentTimeMillis() < deadline) {
                    if (!immediate) Thread.sleep(interval * 1000L)
                    immediate = false
                    when (val result = GitHubApi.pollForToken(id, deviceCode, interval)) {
                        is GitHubApi.TokenResult.Granted -> {
                            val login = GitHubApi.login(result.token)
                            TokenStore.save(context, result.token, login)
                            TokenStore.clearPending(context)
                            val out = JSObject()
                            out.put("authenticated", true)
                            out.put("login", login)
                            return@submit call.resolve(out)
                        }
                        is GitHubApi.TokenResult.Pending -> interval = result.interval
                        is GitHubApi.TokenResult.Failed -> {
                            TokenStore.clearPending(context)
                            return@submit call.reject(result.error)
                        }
                    }
                }
                TokenStore.clearPending(context)
                call.reject("The code expired before it was authorised")
            } catch (e: InterruptedException) {
                // Superseded by a newer sign-in, or abandoned. The page that
                // started this one has already moved on, so this is reported
                // with a code it knows to ignore rather than as an error to
                // put in front of somebody.
                call.reject("Sign-in was replaced", "SUPERSEDED")
            } catch (e: Exception) {
                call.reject(e.message ?: "Sign-in failed", e)
            } finally {
                polling = false
            }
        }
    }


    // ---- One-tap sign-in, brokered by the IdeaBRD server ----
    //
    // The device flow exists because this app cannot hold a client secret. The
    // server can, so it runs the ordinary redirect flow instead and hands the
    // result back on an App Link. What crosses that link is a one-time code,
    // not the token: the app generates a secret, sends only its SHA-256 to the
    // server up front, and proves possession when it collects. That is PKCE,
    // and it means a link claimed by some other app is worth nothing.

    /** Make a sign-in and return the URL to open. Nothing is authorised yet. */
    @PluginMethod
    fun serverSignIn(call: PluginCall) {
        val context = context ?: return call.reject("No context")
        val server = serverUrl(call)
        if (server.isEmpty()) {
            return call.reject("No IdeaBRD server configured for one-tap sign-in")
        }
        val verifier = ByteArray(32).also { SecureRandom().nextBytes(it) }
            .let { Base64.encodeToString(it, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP) }
        val challenge = MessageDigest.getInstance("SHA-256").digest(verifier.toByteArray())
            .let { Base64.encodeToString(it, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP) }
        TokenStore.saveVerifier(context, verifier)
        handoff = null
        val result = JSObject()
        result.put("url", "$server/api/auth/android/start?challenge=$challenge")
        call.resolve(result)
    }

    /**
     * Wait for the App Link to come back and the token to be collected.
     *
     * Resolves as soon as the exchange has happened — including when it
     * happened before this was called, which is the case after the app was
     * reclaimed while the browser had the foreground.
     */
    @PluginMethod
    fun awaitServerSignIn(call: PluginCall) {
        val context = context ?: return call.reject("No context")
        val deadline = System.currentTimeMillis() + (call.getInt("timeout") ?: 600) * 1000L
        work.execute {
            try {
                while (System.currentTimeMillis() < deadline) {
                    TokenStore.token(context)?.let {
                        val out = JSObject()
                        out.put("authenticated", true)
                        out.put("login", TokenStore.login(context))
                        return@execute call.resolve(out)
                    }
                    handoff?.let { return@execute call.reject(it) }
                    Thread.sleep(500)
                }
                call.reject("Timed out waiting for GitHub")
            } catch (e: InterruptedException) {
                call.reject("Sign-in was replaced", "SUPERSEDED")
            }
        }
    }

    /** The App Link, arriving while the app is already running. */
    override fun handleOnNewIntent(intent: Intent) {
        super.handleOnNewIntent(intent)
        collect(intent)
    }

    /** The App Link that started the app from cold. */
    override fun handleOnStart() {
        super.handleOnStart()
        collect(activity?.intent)
    }

    private fun collect(intent: Intent?) {
        val data = intent?.data ?: return
        if (data.path != "/api/auth/android/return") return
        val code = data.getQueryParameter("code") ?: return
        // Consumed: a launch intent is handed back on every resume, and
        // redeeming twice would spend a code that is already gone.
        intent.data = null
        val context = context ?: return
        val server = serverUrl(null)
        work.execute {
            val verifier = TokenStore.verifier(context)
            if (verifier == null) {
                handoff = "This device did not start that sign-in"
                return@execute
            }
            val result = GitHubApi.redeemHandoff(server, code, verifier)
            if (result == null) {
                handoff = "The server would not complete that sign-in"
                return@execute
            }
            TokenStore.save(context, result.token, result.login ?: GitHubApi.login(result.token))
            TokenStore.clearVerifier(context)
        }
    }

    /** Give up on the code in progress, so the next attempt starts clean. */
    @PluginMethod
    fun cancelSignIn(call: PluginCall) {
        val context = context ?: return call.reject("No context")
        pollTask?.cancel(true)
        TokenStore.clearPending(context)
        call.resolve()
    }

    /**
     * Put the user code on the clipboard.
     *
     * Selecting eight characters out of a web page by long-press, on a phone,
     * to paste into a browser, is the worst part of this flow. Doing it here
     * rather than through the page's clipboard API means it works regardless
     * of what the WebView allows.
     */
    @PluginMethod
    fun copyToClipboard(call: PluginCall) {
        val context = context ?: return call.reject("No context")
        val text = call.getString("text") ?: return call.reject("text is required")
        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard.setPrimaryClip(ClipData.newPlainText("IdeaBRD sign-in code", text))
        call.resolve()
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

    private fun serverUrl(call: PluginCall?): String =
        call?.getString("serverUrl")?.takeIf { it.isNotEmpty() } ?: BuildConfig.SERVER_URL

    private fun clientId(call: PluginCall): String =
        call.getString("clientId")?.takeIf { it.isNotEmpty() } ?: BuildConfig.GITHUB_CLIENT_ID
}
