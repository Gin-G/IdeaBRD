package net.nickknows.ideabrd

import java.net.HttpURLConnection
import java.net.URL
import net.nickknows.ideabrd.core.IssueInfo
import org.json.JSONArray
import org.json.JSONObject

/**
 * The little of GitHub's HTTP API the phone needs.
 *
 * Deliberately tiny and dependency-free: the device flow, and enough of /user
 * to know who signed in. Everything else the app does with GitHub it does over
 * git itself, which is a much better protocol for the job — the board *is* the
 * repository, so listing ideas is reading a directory, not paging an API.
 */
object GitHubApi {

    private const val DEVICE_CODE_URL = "https://github.com/login/device/code"
    private const val TOKEN_URL = "https://github.com/login/oauth/access_token"
    private const val USER_URL = "https://api.github.com/user"
    private const val API = "https://api.github.com"

    // A page is the API's maximum; the cap bounds what one refresh can ask for,
    // so a repo with thousands of issues costs a predictable number of requests
    // rather than an unbounded walk. Matches the server's own limits.
    private const val ISSUE_PAGE_SIZE = 100
    private const val ISSUE_MAX_PAGES = 10

    /** What a person needs in front of them to authorise the device. */
    data class DeviceCode(
        val deviceCode: String,
        val userCode: String,
        val verificationUri: String,
        val intervalSeconds: Int,
        val expiresInSeconds: Int,
    )

    /** One poll of the token endpoint: a token, "keep waiting", or a real error. */
    sealed interface TokenResult {
        data class Granted(val token: String) : TokenResult
        /** Not yet authorised. [interval] is GitHub's revised polling floor. */
        data class Pending(val interval: Int) : TokenResult
        data class Failed(val error: String) : TokenResult
    }

    fun requestDeviceCode(clientId: String, scope: String): DeviceCode {
        val body = form("client_id" to clientId, "scope" to scope)
        val json = post(DEVICE_CODE_URL, body)
        if (json.has("error")) error(json.optString("error_description", json.getString("error")))
        return DeviceCode(
            deviceCode = json.getString("device_code"),
            userCode = json.getString("user_code"),
            verificationUri = json.optString("verification_uri", "https://github.com/login/device"),
            intervalSeconds = json.optInt("interval", 5),
            expiresInSeconds = json.optInt("expires_in", 900),
        )
    }

    fun pollForToken(clientId: String, deviceCode: String, interval: Int): TokenResult {
        val json = post(
            TOKEN_URL,
            form(
                "client_id" to clientId,
                "device_code" to deviceCode,
                "grant_type" to "urn:ietf:params:oauth:grant-type:device_code",
            ),
        )
        json.optString("access_token").takeIf { it.isNotEmpty() }?.let {
            return TokenResult.Granted(it)
        }
        return when (val error = json.optString("error")) {
            // The two answers that mean "ask again": nobody has typed the code
            // yet, and we asked too soon. GitHub revokes the device code
            // outright if slow_down is ignored, so its new interval is used.
            "authorization_pending" -> TokenResult.Pending(interval)
            "slow_down" -> TokenResult.Pending(json.optInt("interval", interval + 5))
            "" -> TokenResult.Failed("GitHub returned no token and no error")
            else -> TokenResult.Failed(json.optString("error_description", error))
        }
    }

    /** The login the token belongs to, or null if it is no longer any good. */
    /**
     * Who a token belongs to, and — for a classic token — what it may do.
     *
     * [scopes] is null for a fine-grained personal access token and for a
     * GitHub App token: neither advertises `X-OAuth-Scopes`, because neither
     * has scopes. Their permissions are set per repository and can only be
     * discovered by trying, so a null here means "no opinion", not "none".
     */
    data class Identity(val login: String, val scopes: List<String>?)

    /** A GitHub token the server obtained on this device's behalf. */
    data class Handoff(val token: String, val login: String?)

    /**
     * Redeem a server handoff: the one-time code that arrived on the App Link,
     * plus the secret this device generated, for the token the server got from
     * GitHub.
     *
     * The code travelled in a URL and is worth nothing on its own — the server
     * has only the SHA-256 of the verifier until this call, and spends the code
     * whether or not the verifier matches.
     */
    fun redeemHandoff(serverUrl: String, code: String, verifier: String): Handoff? {
        val body = JSONObject().put("code", code).put("verifier", verifier).toString()
        val connection =
            URL("$serverUrl/api/auth/android/exchange").openConnection() as HttpURLConnection
        return try {
            connection.requestMethod = "POST"
            connection.setRequestProperty("Content-Type", "application/json")
            connection.setRequestProperty("User-Agent", "IdeaBRD-Android")
            connection.doOutput = true
            connection.outputStream.use { it.write(body.toByteArray()) }
            if (connection.responseCode !in 200..299) return null
            val json = JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
            val token = json.optString("token").takeIf { it.isNotEmpty() } ?: return null
            Handoff(token, json.optString("login").takeIf { it.isNotEmpty() })
        } catch (_: Exception) {
            null
        } finally {
            connection.disconnect()
        }
    }

    /** Check a token and find out whose it is. Null if GitHub rejected it. */
    fun identify(token: String): Identity? {
        val connection = URL(USER_URL).openConnection() as HttpURLConnection
        return try {
            connection.setRequestProperty("Authorization", "Bearer $token")
            connection.setRequestProperty("Accept", "application/vnd.github+json")
            connection.setRequestProperty("User-Agent", "IdeaBRD-Android")
            if (connection.responseCode != 200) return null
            val scopes = connection.getHeaderField("X-OAuth-Scopes")
                ?.split(",")
                ?.map { it.trim() }
                ?.filter { it.isNotEmpty() }
            val login = JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
                .optString("login")
                .takeIf { it.isNotEmpty() }
                ?: return null
            Identity(login, scopes)
        } catch (_: Exception) {
            null
        } finally {
            connection.disconnect()
        }
    }

    fun login(token: String): String? {
        val connection = URL(USER_URL).openConnection() as HttpURLConnection
        return try {
            connection.setRequestProperty("Authorization", "Bearer $token")
            connection.setRequestProperty("Accept", "application/vnd.github+json")
            connection.setRequestProperty("User-Agent", "IdeaBRD-Android")
            if (connection.responseCode != 200) return null
            JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
                .optString("login")
                .takeIf { it.isNotEmpty() }
        } catch (_: Exception) {
            null
        } finally {
            connection.disconnect()
        }
    }

    /**
     * Every issue in a repo, newest first, as a map by number.
     *
     * Pull requests are filtered out: this endpoint returns them alongside
     * issues, and a PR sharing a number with a to-do would otherwise drive its
     * state. Paging stops early on a short page, so the ordinary repo costs
     * exactly one request.
     */
    fun listIssues(repo: String, token: String): Map<Int, IssueInfo> {
        val issues = mutableMapOf<Int, IssueInfo>()
        for (page in 1..ISSUE_MAX_PAGES) {
            val url = "$API/repos/$repo/issues?state=all&per_page=$ISSUE_PAGE_SIZE&page=$page"
            val body = get(url, token) ?: break
            val array = JSONArray(body)
            for (i in 0 until array.length()) {
                val item = array.getJSONObject(i)
                if (item.has("pull_request")) continue
                val labels = item.optJSONArray("labels") ?: JSONArray()
                val assignee = item.optJSONObject("assignee")
                issues[item.getInt("number")] = IssueInfo(
                    number = item.getInt("number"),
                    title = item.optString("title"),
                    state = item.optString("state", "open"),
                    htmlUrl = item.optString("html_url"),
                    labels = (0 until labels.length()).map {
                        labels.getJSONObject(it).optString("name")
                    },
                    assignee = assignee?.optString("login"),
                    comments = item.optInt("comments"),
                )
            }
            if (array.length() < ISSUE_PAGE_SIZE) break
        }
        return issues
    }

    /**
     * Mirror a to-do's text and state onto its issue.
     *
     * Best-effort on purpose: a failure here leaves the board ahead of GitHub,
     * which the next refresh corrects in GitHub's favour, because the issue
     * always wins in the end.
     */
    fun updateIssue(repo: String, number: Int, title: String, closed: Boolean, token: String): Boolean {
        val body = JSONObject()
            .put("title", title)
            .put("state", if (closed) "closed" else "open")
            .toString()
        // Android's HttpURLConnection is OkHttp underneath and accepts PATCH,
        // unlike the JDK's, which validates against a fixed list of methods.
        return send("$API/repos/$repo/issues/$number", "PATCH", body, token) != null
    }

    /**
     * Open an issue and return it, or null if GitHub refused.
     *
     * The click is the opt-in: nothing reaches the repository until someone
     * asks for it here, so unlike the idea file there is no separate gate.
     */
    fun createIssue(repo: String, title: String, body: String, token: String): IssueInfo? {
        val response = send(
            "$API/repos/$repo/issues",
            "POST",
            JSONObject().put("title", title).put("body", body).toString(),
            token,
        ) ?: return null
        val item = JSONObject(response)
        return IssueInfo(
            number = item.getInt("number"),
            title = item.optString("title"),
            state = item.optString("state", "open"),
            htmlUrl = item.optString("html_url"),
            comments = item.optInt("comments"),
        )
    }

    /**
     * Create a repository for an idea. Returns "owner/name".
     *
     * Initialised on creation, because GitHub rejects every git data write to a
     * repo with no commits at all — and a clone of an empty repository has no
     * branch to commit onto. Letting GitHub make the first commit is what the
     * web UI does, and it leaves the idea's own first commit on top of it.
     */
    fun createRepo(
        name: String,
        org: String?,
        private: Boolean,
        description: String,
        token: String,
    ): String? {
        val path = if (org.isNullOrEmpty()) "$API/user/repos" else "$API/orgs/$org/repos"
        val body = JSONObject()
            .put("name", name)
            .put("private", private)
            .put("auto_init", true)
            .put("description", description)
            .toString()
        val response = send(path, "POST", body, token) ?: return null
        return JSONObject(response).optString("full_name").ifEmpty { null }
    }

    /** Organisations the token can see. Empty without the read:org scope. */
    fun orgs(token: String): List<String> {
        val body = get("$API/user/orgs?per_page=100", token) ?: return emptyList()
        val array = JSONArray(body)
        return (0 until array.length()).map { array.getJSONObject(it).optString("login") }
            .filter { it.isNotEmpty() }
    }

    /** A write with a JSON body. Returns the response, or null if it failed. */
    private fun send(url: String, method: String, body: String, token: String): String? {
        val connection = URL(url).openConnection() as HttpURLConnection
        return try {
            connection.requestMethod = method
            connection.setRequestProperty("Content-Type", "application/json")
            connection.setRequestProperty("Accept", "application/vnd.github+json")
            connection.setRequestProperty("Authorization", "Bearer $token")
            connection.setRequestProperty("User-Agent", "IdeaBRD-Android")
            connection.doOutput = true
            connection.outputStream.use { it.write(body.toByteArray()) }
            if (connection.responseCode !in 200..299) return null
            connection.inputStream.bufferedReader().use { it.readText() }
        } catch (_: Exception) {
            null
        } finally {
            connection.disconnect()
        }
    }

    /** A plain authenticated GET, or null if it failed. */
    private fun get(url: String, token: String): String? {
        val connection = URL(url).openConnection() as HttpURLConnection
        return try {
            connection.setRequestProperty("Authorization", "Bearer $token")
            connection.setRequestProperty("Accept", "application/vnd.github+json")
            connection.setRequestProperty("User-Agent", "IdeaBRD-Android")
            if (connection.responseCode !in 200..299) return null
            connection.inputStream.bufferedReader().use { it.readText() }
        } catch (_: Exception) {
            null
        } finally {
            connection.disconnect()
        }
    }

    private fun form(vararg pairs: Pair<String, String>): String =
        pairs.joinToString("&") { (k, v) ->
            "$k=" + java.net.URLEncoder.encode(v, "UTF-8")
        }

    private fun post(url: String, body: String): JSONObject {
        val connection = URL(url).openConnection() as HttpURLConnection
        try {
            connection.requestMethod = "POST"
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
            // Without this GitHub answers the device endpoints in form encoding.
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("User-Agent", "IdeaBRD-Android")
            connection.outputStream.use { it.write(body.toByteArray()) }
            val stream =
                if (connection.responseCode in 200..299) connection.inputStream
                else connection.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            return if (text.isEmpty()) JSONObject() else JSONObject(text)
        } finally {
            connection.disconnect()
        }
    }
}
