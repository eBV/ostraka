package dev.ostraka.app

/** zstd decompression helper (zstd-jni on the JVM side of the app). */
object Zstd {
    fun decompressToString(blob: ByteArray): String {
        // Implementation via com.github.luben:zstd-jni; wired in build phase.
        TODO("zstd-jni decompression")
    }
}
