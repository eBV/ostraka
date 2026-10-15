cmake_minimum_required(VERSION 3.22.1)
project(ostraka_jni)

# llama.cpp lives at third_party/llama.cpp (git submodule, pinned in README).
# We build it in-tree so the JNI bridge links the exact same sources.
set(LLAMA_CPP_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../third_party/llama.cpp")

if(NOT EXISTS "${LLAMA_CPP_DIR}/CMakeLists.txt")
    message(FATAL_ERROR
        "llama.cpp submodule missing at ${LLAMA_CPP_DIR}. "
        "Run: git submodule update --init --recursive")
endif()

# Keep the JNI surface minimal: no tools, no server, no curl.
set(LLAMA_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_SERVER OFF CACHE BOOL "" FORCE)
set(LLAMA_CURL OFF CACHE BOOL "" FORCE)

add_subdirectory(${LLAMA_CPP_DIR} llama.cpp-build)

add_library(ostraka_jni SHARED ostraka_jni.cpp)

target_include_directories(ostraka_jni PRIVATE
    ${LLAMA_CPP_DIR}/include
    ${LLAMA_CPP_DIR}/common
    ${LLAMA_CPP_DIR}/ggml/include
)

target_link_libraries(ostraka_jni PRIVATE
    llama
    common
    ggml
    android
    log
)
