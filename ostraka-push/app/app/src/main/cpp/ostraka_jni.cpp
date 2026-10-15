// Ostraka JNI bridge over llama.cpp.
//
// Design notes:
// - The model file is opened with mmap (llama.cpp default). On Android the OS
//   demand-pages it: MoE expert tensors that a token never routes to stay on
//   storage. This is the "100B-class params on disk" mechanism; no special
//   fork is required for correctness, only for tuning.
// - One engine per process. init() is idempotent; free() releases everything.
// - Generation streams tokens back through a Java callback so the UI can
//   render incrementally and the user can stop mid-answer.

#include <jni.h>
#include <string>
#include <vector>
#include <chrono>
#include <android/log.h>

#include "llama.h"
#include "common.h"

#define LOG_TAG "ostraka_jni"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

struct Engine {
    llama_model * model = nullptr;
    llama_context * ctx = nullptr;
    llama_sampler * sampler = nullptr;
    const llama_vocab * vocab = nullptr;
    int n_threads = 0;
    volatile bool stop_flag = false;
    std::string last_metrics = "{}";
};

static Engine * as_engine(jlong h) { return reinterpret_cast<Engine *>(h); }

static int cpu_count() {
    // TODO: read /sys/devices/system/cpu + big/little topology; start with
    // min(8, online) and let :bench tune it per device.
    return 4;
}

extern "C" {

JNIEXPORT jlong JNICALL
Java_dev_ostraka_app_Engine_nativeInit(JNIEnv * env, jobject /*thiz*/, jstring jpath) {
    const char * path = env->GetStringUTFChars(jpath, nullptr);

    // Refuse to load a model that cannot fit the RAM free right now.
    // TODO: stat the file, read MemAvailable, apply the policy from
    // ARCHITECTURE.md (deep tier needs ~7 GB free incl. page-cache headroom).
    (void) path;

    common_params params;
    params.model.path = path;
    params.n_ctx = 4096;
    params.n_threads = cpu_count();
    // mmap stays ON: demand-paged experts are the whole point.
    params.use_mmap = true;
    params.use_mlock = false;

    common_init_result init = common_init_from_params(params);
    env->ReleaseStringUTFChars(jpath, path);

    if (!init.model || !init.context) {
        LOGE("common_init_from_params failed");
        return 0;
    }

    auto * e = new Engine();
    e->model = init.model;
    e->ctx = init.context;
    e->vocab = llama_model_get_vocab(e->model);
    e->n_threads = params.n_threads;

    e->sampler = llama_sampler_chain_init(llama_sampler_chain_default_params());
    llama_sampler_chain_add(e->sampler,
        llama_sampler_init_temp(0.7f));
    llama_sampler_chain_add(e->sampler,
        llama_sampler_init_top_p(0.9f, 1));
    llama_sampler_chain_add(e->sampler,
        llama_sampler_init_dist(LLAMA_DEFAULT_SEED));

    LOGI("engine ready: n_ctx=%d threads=%d", llama_n_ctx(e->ctx), e->n_threads);
    return reinterpret_cast<jlong>(e);
}

JNIEXPORT void JNICALL
Java_dev_ostraka_app_Engine_nativeFree(JNIEnv * /*env*/, jobject /*thiz*/, jlong h) {
    Engine * e = as_engine(h);
    if (!e) return;
    llama_sampler_free(e->sampler);
    llama_free(e->ctx);
    llama_model_free(e->model);
    delete e;
}

JNIEXPORT void JNICALL
Java_dev_ostraka_app_Engine_nativeStop(JNIEnv * /*env*/, jobject /*thiz*/, jlong h) {
    if (as_engine(h)) as_engine(h)->stop_flag = true;
}

// prompt: full prompt incl. system + retrieved passages + question.
// cb: void onToken(String piece) — called per decoded piece on this thread.
JNIEXPORT jstring JNICALL
Java_dev_ostraka_app_Engine_nativeGenerate(
        JNIEnv * env, jobject /*thiz*/, jlong h,
        jstring jprompt, jint max_tokens, jobject cb) {
    Engine * e = as_engine(h);
    if (!e) return env->NewStringUTF("");

    const char * prompt = env->GetStringUTFChars(jprompt, nullptr);
    std::string prompt_s(prompt);
    env->ReleaseStringUTFChars(jprompt, prompt);
    e->stop_flag = false;

    jclass cb_cls = env->GetObjectClass(cb);
    jmethodID on_token = env->GetMethodID(cb_cls, "onToken", "(Ljava/lang/String;)V");

    const bool add_bos = llama_vocab_get_add_bos(e->vocab);
    std::vector<llama_token> tokens = common_tokenize(e->ctx, prompt_s, add_bos);

    const int n_ctx = llama_n_ctx(e->ctx);
    if ((int) tokens.size() > n_ctx - 256) {
        // Truncate from the front of the passages, keeping the question tail.
        // (The Kotlin side sizes prompts to fit; this is the backstop.)
        tokens = std::vector<llama_token>(
            tokens.end() - (n_ctx - 256), tokens.end());
        LOGI("prompt truncated to %d tokens", (int) tokens.size());
    }
    llama_memory_clear(llama_get_memory(e->ctx), true);

    std::string out;
    auto t_pp0 = std::chrono::steady_clock::now();
    int n_past = 0;

    const int n_batch = 512;
    llama_batch batch = llama_batch_init(n_batch, 0, 1);

    // Prefill in chunks.
    for (size_t i = 0; i < tokens.size() && !e->stop_flag; i += n_batch) {
        int n = (int) std::min<size_t>(n_batch, tokens.size() - i);
        common_batch_clear(batch);
        for (int j = 0; j < n; j++) {
            common_batch_add(batch, tokens[i + j], n_past + j, {0}, j == n - 1);
        }
        if (llama_decode(e->ctx, batch) != 0) {
            LOGE("prefill decode failed at token %zu", i);
            break;
        }
        n_past += n;
    }
    auto t_pp1 = std::chrono::steady_clock::now();

    // Decode one token at a time.
    int n_generated = 0;
    auto t_tg0 = std::chrono::steady_clock::now();
    while (n_generated < max_tokens && !e->stop_flag) {
        llama_token tok = llama_sampler_sample(e->sampler, e->ctx, -1);
        if (llama_vocab_is_eog(e->vocab, tok)) break;

        char buf[256];
        int n = llama_token_to_piece(e->vocab, tok, buf, sizeof(buf), 0, true);
        if (n > 0) {
            std::string piece(buf, n);
            out += piece;
            jstring jpiece = env->NewStringUTF(piece.c_str());
            env->CallVoidMethod(cb, on_token, jpiece);
            env->DeleteLocalRef(jpiece);
            if (env->ExceptionCheck()) { env->ExceptionClear(); break; }
        }

        common_batch_clear(batch);
        common_batch_add(batch, tok, n_past++, {0}, true);
        if (llama_decode(e->ctx, batch) != 0) {
            LOGE("decode failed at generated token %d", n_generated);
            break;
        }
        n_generated++;
    }
    auto t_tg1 = std::chrono::steady_clock::now();
    llama_batch_free(batch);

    double pp_s = std::chrono::duration<double>(t_pp1 - t_pp0).count();
    double tg_s = std::chrono::duration<double>(t_tg1 - t_tg0).count();
    double prompt_tps = tokens.size() / std::max(pp_s, 1e-6);
    double gen_tps = n_generated / std::max(tg_s, 1e-6);
    LOGI("generate done: %d prompt tok (%.1f t/s), %d gen tok (%.1f t/s)",
         (int) tokens.size(), prompt_tps, n_generated, gen_tps);

    // Stash metrics for nativeMetrics().
    char mbuf[256];
    snprintf(mbuf, sizeof(mbuf),
             "{\"prompt_tokens\":%d,\"prompt_tps\":%.1f,"
             "\"gen_tokens\":%d,\"gen_tps\":%.1f,\"threads\":%d}",
             (int) tokens.size(), prompt_tps, n_generated, gen_tps,
             e->n_threads);
    e->last_metrics = mbuf;

    return env->NewStringUTF(out.c_str());
}

JNIEXPORT jstring JNICALL
Java_dev_ostraka_app_Engine_nativeMetrics(
        JNIEnv * env, jobject /*thiz*/, jlong h) {
    Engine * e = as_engine(h);
    if (!e) return env->NewStringUTF("{}");
    return env->NewStringUTF(e->last_metrics.c_str());
}

// Runs a short fixed prompt and returns JSON:
// {"prompt_tps": x, "gen_tps": y, "threads": n, "model": path}
JNIEXPORT jstring JNICALL
Java_dev_ostraka_app_Engine_nativeBench(
        JNIEnv * env, jobject /*thiz*/, jstring jpath) {
    // TODO: load, run pp128/tg128, sweep thread counts, return JSON.
    (void) jpath;
    return env->NewStringUTF("{\"status\":\"todo\"}");
}

} // extern "C"
