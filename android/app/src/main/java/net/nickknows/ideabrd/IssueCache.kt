package net.nickknows.ideabrd

import java.io.File
import net.nickknows.ideabrd.core.IssueInfo
import org.json.JSONArray
import org.json.JSONObject

/**
 * The issues behind a repo's to-dos, kept on disk between refreshes.
 *
 * An issue-backed to-do's real state lives in GitHub, and the file only caches
 * it. On a phone that distinction matters more than it does on a server: the
 * app has to open a board on a train, so it needs *something* to show, and the
 * honest something is what GitHub last said rather than a blank.
 *
 * Kept outside the checkout deliberately. It is not part of the idea and must
 * never end up committed to somebody's repository.
 */
class IssueCache(private val root: File) {

    private fun fileFor(repo: String) = File(root, repo.replace("/", "__") + ".json")

    fun load(repo: String): Map<Int, IssueInfo> {
        val file = fileFor(repo)
        if (!file.isFile) return emptyMap()
        return try {
            val array = JSONArray(file.readText())
            (0 until array.length()).associate { i ->
                val item = array.getJSONObject(i)
                val labels = item.optJSONArray("labels") ?: JSONArray()
                item.getInt("number") to IssueInfo(
                    number = item.getInt("number"),
                    title = item.optString("title"),
                    state = item.optString("state", "open"),
                    htmlUrl = item.optString("htmlUrl"),
                    labels = (0 until labels.length()).map { labels.getString(it) },
                    assignee = item.optString("assignee").ifEmpty { null },
                    comments = item.optInt("comments"),
                )
            }
        } catch (_: Exception) {
            // A cache we can't read is a cache, not an error: drop it and the
            // next refresh writes a good one.
            emptyMap()
        }
    }

    fun save(repo: String, issues: Collection<IssueInfo>) {
        root.mkdirs()
        val array = JSONArray()
        issues.forEach { issue ->
            array.put(
                JSONObject()
                    .put("number", issue.number)
                    .put("title", issue.title)
                    .put("state", issue.state)
                    .put("htmlUrl", issue.htmlUrl)
                    .put("labels", JSONArray(issue.labels))
                    .put("assignee", issue.assignee)
                    .put("comments", issue.comments)
            )
        }
        fileFor(repo).writeText(array.toString())
    }
}
