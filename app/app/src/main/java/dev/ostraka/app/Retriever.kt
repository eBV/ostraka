package dev.ostraka.app

import android.database.sqlite.SQLiteDatabase

/**
 * BM25 retrieval over a pack's FTS5 index. Mirrors tools/pipeline/retriever.py.
 */
class Retriever(indexPath: String, chunksPath: String) {

    private val idx: SQLiteDatabase =
        SQLiteDatabase.openDatabase(indexPath, null, SQLiteDatabase.OPEN_READONLY)
    private val chunks: SQLiteDatabase =
        SQLiteDatabase.openDatabase(chunksPath, null, SQLiteDatabase.OPEN_READONLY)

    data class Hit(val chunkId: Long, val score: Double, val text: String)

    fun search(query: String, k: Int = 40): List<Hit> {
        val q = sanitize(query)
        if (q.isBlank()) return emptyList()
        val rows = idx.rawQuery(
            "SELECT chunk_id, bm25(idx) AS s FROM idx WHERE idx MATCH ? " +
                "ORDER BY s LIMIT ?",
            arrayOf(q, k.toString()),
        )
        val scored = mutableListOf<Pair<Long, Double>>()
        rows.use {
            while (it.moveToNext()) {
                scored += it.getLong(0) to it.getDouble(1)
            }
        }
        if (scored.isEmpty()) return emptyList()
        val ids = scored.map { it.first }
        val texts = mutableMapOf<Long, String>()
        chunks.rawQuery(
            "SELECT chunk_id, text_zstd FROM chunks WHERE chunk_id IN " +
                "(${ids.joinToString(",") { "?" }})",
            ids.map { it.toString() }.toTypedArray(),
        ).use {
            while (it.moveToNext()) {
                val blob = it.getBlob(1)
                texts[it.getLong(0)] = Zstd.decompressToString(blob)
            }
        }
        return scored.mapNotNull { (id, s) ->
            texts[id]?.let { Hit(id, s, it) }
        }
    }

    fun titleBoostSearch(query: String, k: Int = 40): List<Hit> {
        val qterms = sanitize(query).lowercase().split(" ")
            .filter { it != "or" }.toSet()
        return search(query, k * 2).map { h ->
            val title = h.text.substringBefore("\n").lowercase()
            val overlap = qterms.count { t ->
                Regex("\\b${Regex.escape(t)}\\b").containsMatchIn(title)
            }
            h.copy(score = h.score - 2.0 * overlap)
        }.sortedBy { it.score }.take(k)
    }

    fun close() {
        idx.close()
        chunks.close()
    }

    companion object {
        private val STOPWORDS = setOf(
            "who", "what", "when", "where", "why", "how", "which", "whom",
            "whose", "is", "are", "was", "were", "be", "been", "do", "does",
            "did", "the", "a", "an", "of", "in", "on", "at", "to", "for",
            "and", "or", "by", "with", "from", "as", "it", "its", "this",
            "that",
        )

        /** Build an FTS5 OR-query over content terms (implicit AND misses). */
        fun sanitize(q: String, maxTerms: Int = 12): String {
            val seen = linkedSetOf<String>()
            q.lowercase().split(Regex("[^\\p{L}\\p{N}]+"))
                .filter { it.length > 1 && it !in STOPWORDS }
                .forEach { if (seen.size < maxTerms) seen += it }
            // Quote terms so FTS5 treats them literally.
            return seen.joinToString(" OR ") { "\"$it\"" }
        }
    }
}
