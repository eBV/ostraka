package dev.ostraka.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * Answer pipeline: plan -> retrieve -> rerank -> synthesize -> verify.
 * Mirrors tools/pipeline/pipeline.py (the tested reference implementation).
 */
class Pipeline(
    private val packDir: java.io.File,
    private val modelFile: java.io.File,
    private val rerankerDir: java.io.File,
) {
    data class Result(
        val answer: String,
        val verified: List<String>,
        val unverified: List<String>,
        val metrics: String,
        val questionType: String,
    )

    interface Progress {
        fun onToken(piece: String)
    }

    suspend fun ask(question: String, progress: Progress): Result =
        withContext(Dispatchers.Default) {
            val retriever = Retriever(
                "${packDir.absolutePath}/index.db",
                "${packDir.absolutePath}/chunks.db",
            )
            val reranker = Reranker(rerankerDir)
            try {
                val engine = Engine.get(modelFile)

                // 1. Plan: classify + sub-queries (fast call on the same engine).
                val (qtype, subs) = plan(question, engine)

                // 2. Retrieve per sub-query, merge, de-dupe.
                val seen = linkedSetOf<Long>()
                val cands = mutableListOf<Retriever.Hit>()
                for (sq in subs) {
                    for (h in retriever.titleBoostSearch(sq, k = 40)) {
                        if (seen.add(h.chunkId)) cands += h
                    }
                }

                // 3. Rerank to top passages.
                val top = reranker.rerank(question, cands, topK = 8)
                if (top.isEmpty()) {
                    return@withContext Result(
                        answer = "I could not find this in the installed " +
                            "knowledge packs. Try rephrasing, or install a " +
                            "pack that covers the topic.",
                        verified = emptyList(),
                        unverified = emptyList(),
                        metrics = "{}",
                        questionType = qtype,
                    )
                }

                // 4. Synthesize with citations.
                val passages = top.mapIndexed { i, s -> "[${i + 1}] ${s.text}" }
                    .joinToString("\n\n")
                val draft = engine.generate(
                    systemPrompt() + "\n\nPassages:\n$passages\n\n" +
                        "Question: $question\n\nAnswer with inline [n] citations:",
                    maxTokens = 384,
                    object : Engine.TokenCallback {
                        override fun onToken(piece: String) {
                            progress.onToken(piece)
                        }
                    },
                )

                // 5. Verify claims against cited passages.
                val report = Verifier.verify(draft, top.map { it.text })
                Result(
                    answer = Verifier.mark(draft, report.unverified),
                    verified = report.verified,
                    unverified = report.unverified,
                    metrics = engine.metrics(),
                    questionType = qtype,
                )
            } finally {
                reranker.close()
                retriever.close()
            }
        }

    private fun plan(question: String, engine: Engine): Pair<String, List<String>> {
        return try {
            val raw = engine.generate(
                REWRITE_SYSTEM + "\n\nQuestion: $question",
                256,
                object : Engine.TokenCallback {
                    override fun onToken(piece: String) {}
                },
            )
            val json = JSONObject(
                raw.substring(raw.indexOf("{"), raw.lastIndexOf("}") + 1),
            )
            val subs = mutableListOf<String>()
            val arr = json.optJSONArray("subqueries")
            if (arr != null) {
                for (i in 0 until minOf(arr.length(), 3)) {
                    subs += arr.getString(i)
                }
            }
            if (subs.isEmpty()) throw IllegalArgumentException("no subqueries")
            json.optString("type", "factual") to subs
        } catch (_: Exception) {
            "factual" to listOf(question)
        }
    }

    companion object {
        // Prompts mirror tools/pipeline/prompts.py.
        const val REWRITE_SYSTEM = """You are the query planner for an offline research app. Given the user's question, output JSON only, no other text: {"type": "factual|explanation|comparison|synthesis|reasoning", "subqueries": ["...", "..."]}. Rules: 1-3 subqueries, each a 3-8 word search phrase naming the entities and facts needed. For comparison questions include one subquery per side. For reasoning questions, subqueries name the facts the math or logic needs. Never answer the question yourself."""

        private fun systemPrompt(): String =
            """You are an offline research assistant. Answer ONLY from the passages below. Every specific name, number, date, or quoted claim MUST carry an inline citation like [1], [2] referring to the passage it came from. If the passages do not contain the answer, say so plainly and stop; do not guess, do not use outside knowledge, do not hedge with invented specifics. Keep answers focused: 120-220 words unless the question needs more. Reasoning questions: show the arithmetic or logic steps, citing the input numbers you use."""
    }
}
