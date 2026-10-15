package dev.ostraka.app

/**
 * Claim-level citation verification. Mirrors tools/pipeline/verify.py:
 * every number, date, and named entity in the draft answer must be grounded
 * in one of the cited passages, or it gets flagged, never silently kept.
 */
object Verifier {

    private val NUMBER_RE = Regex(
        """\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b""" + "|" +
            """\b\d+\.\d+\b""" + "|" +
            """\b\d+\s?(?:%|percent)\b""" + "|" +
            """\b(?:1[0-9]\d\d|20[0-3]\d)\b""" + "|" +
            """\b\d+\s?(?:m|km|kg|g|cm|mm|mph|km/h|°C|°F|K)\b""" + "|" +
            """\b\d{2,}\b""",
        RegexOption.IGNORE_CASE,
    )
    private val ENTITY_RE = Regex("""\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b""")
    private val STOP = setOf(
        "The", "A", "An", "In", "On", "At", "Of", "And", "For", "To",
        "With", "From", "By", "As", "It", "Its", "This", "That", "These",
        "Those", "He", "She", "They", "We", "You", "His", "Her", "Their",
        "About", "Nearly", "Almost", "Over", "Under", "Between", "During",
        "According", "While", "After", "Before", "Such",
    )

    data class Report(
        val verified: List<String>,
        val unverified: List<String>,
    )

    private fun normalize(s: String): String =
        s.lowercase().replace(Regex("""[^\w\s]"""), " ")
            .replace(Regex("""\s+"""), " ").trim()

    fun extractClaims(answer: String): List<String> {
        val out = linkedSetOf<String>()
        NUMBER_RE.findAll(answer).forEach { out += it.value }
        ENTITY_RE.findAll(answer).forEach { m ->
            val ent = m.groupValues[1]
            if (ent.split(" ").first() !in STOP && ent.length >= 3) {
                out += ent
            }
        }
        return out.toList()
    }

    fun verify(answer: String, passages: List<String>): Report {
        val normed = passages.map { normalize(it) }
        val verified = mutableListOf<String>()
        val unverified = mutableListOf<String>()
        for (claim in extractClaims(answer)) {
            val n = normalize(claim)
            val hit = if (NUMBER_RE.matches(claim)) {
                val core = n.replace(Regex("""[^\w.]"""), "")
                    .replace("percent", "%")
                normed.any { core in it.replace(Regex("""[^\w.]"""), "") }
            } else {
                normed.any { n in it }
            }
            (if (hit) verified else unverified) += claim
        }
        return Report(verified, unverified)
    }

    fun mark(answer: String, unverified: List<String>): String {
        if (unverified.isEmpty()) return answer
        val names = unverified.take(5).joinToString(", ") { "\"$it\"" }
        val more = if (unverified.size > 5) " (+${unverified.size - 5} more)" else ""
        return answer.trimEnd() +
            "\n\n⚠ Could not verify against cited sources: $names$more"
    }
}
