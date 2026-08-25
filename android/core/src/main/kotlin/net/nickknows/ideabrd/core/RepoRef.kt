package net.nickknows.ideabrd.core

/**
 * Parsing for GitHub repo references — the port of `backend/app/repo_ref.py`.
 *
 * Stored values must be normalized to "owner/name": the UI interpolates them
 * straight into `https://github.com/{repo}` links, so a full clone URL doubles
 * up.
 */

private val REPO_RE = Regex("""^[\w.-]+/[\w.-]+$""")
private val URL_RE = Regex("""github\.com[/:]([\w.-]+/[\w.-]+?)(?:\.git)?/?$""")

class InvalidRepoRef(message: String) : IllegalArgumentException(message)

/** Accept "owner/name" or a full GitHub URL and return "owner/name". */
fun normalizeRepo(repo: String): String {
    var value = repo.trim()
    URL_RE.find(value)?.let { value = it.groupValues[1] }
    if (!REPO_RE.matches(value)) throw InvalidRepoRef("Invalid repo reference: $repo")
    return value
}

/** The same, for the parser, where an unusable value costs the field not the file. */
fun normalizeRepoOrNull(repo: String): String? =
    try {
        normalizeRepo(repo)
    } catch (_: InvalidRepoRef) {
        null
    }
