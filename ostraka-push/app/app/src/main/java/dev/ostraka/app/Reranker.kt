package dev.ostraka.app

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import com.knuddels.jtokkit.api.EncodingType
import java.io.File
import java.nio.LongBuffer

/**
 * Cross-encoder rerank (ms-marco-MiniLM-L-6-v2, int8 ONNX).
 * Mirrors tools/pipeline/rerank.py. The model file (~23 MB) ships as a
 * setup-time download, same flow as model/pack assets.
 */
class Reranker(modelDir: File) : AutoCloseable {

    private val env: OrtEnvironment = OrtEnvironment.getEnvironment()
    private val session: OrtSession = env.createSession(
        File(modelDir, "model_quantized.onnx").absolutePath,
        OrtSession.SessionOptions(),
    )
    private val inputNames: List<String> =
        session.inputNames.toList()

    data class Scored(val chunkId: Long, val score: Float, val text: String)

    /**
     * Rescore [candidates] against [query], return top [topK].
     * Tokenization here is a placeholder: the build phase wires a
     * WordPiece tokenizer matching tokenizer.json (or bundles the
     * HF tokenizer via the `tokenizers` JNI port).
     */
    fun rerank(
        query: String,
        candidates: List<Retriever.Hit>,
        topK: Int = 8,
    ): List<Scored> {
        if (candidates.isEmpty()) return emptyList()
        // TODO: real WordPiece encode of (query, passage) pairs to MAX_LEN=256.
        TODO("tokenizer wiring")
    }

    override fun close() {
        session.close()
        env.close()
    }

    companion object {
        const val MAX_LEN = 256
    }
}
