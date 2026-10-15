package dev.ostraka.app

import java.io.File

/** Thin wrapper over the native engine (ostraka_jni). One instance per process. */
class Engine private constructor(private val handle: Long) {

    interface TokenCallback {
        fun onToken(piece: String)
    }

    fun generate(prompt: String, maxTokens: Int, cb: TokenCallback): String =
        nativeGenerate(handle, prompt, maxTokens, cb)

    fun stop() = nativeStop(handle)

    fun close() = nativeFree(handle)

    /** JSON metrics from the last generate(): prompt/gen tokens and tok/s. */
    fun metrics(): String = nativeMetrics(handle)

    private external fun nativeGenerate(
        handle: Long, prompt: String, maxTokens: Int, cb: TokenCallback,
    ): String
    private external fun nativeStop(handle: Long)
    private external fun nativeFree(handle: Long)
    private external fun nativeMetrics(handle: Long): String

    companion object {
        init {
            System.loadLibrary("ostraka_jni")
        }

        @Volatile private var instance: Engine? = null

        /** Loads [modelFile] if it fits current free RAM, else throws. */
        @Synchronized
        fun get(modelFile: File): Engine {
            instance?.let { return it }
            val h = nativeInit(modelFile.absolutePath)
            require(h != 0L) { "nativeInit failed for ${modelFile.name}" }
            return Engine(h).also { instance = it }
        }

        fun bench(modelFile: File): String = nativeBench(modelFile.absolutePath)

        private external fun nativeInit(path: String): Long
        private external fun nativeBench(path: String): String
    }
}
