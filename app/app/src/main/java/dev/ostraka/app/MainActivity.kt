package dev.ostraka.app

import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.*

/**
 * Scaffold UI. The build phase wires this to:
 *  - PackManager (install/verify packs from Downloads)
 *  - Retriever (FTS5 -> cross-encoder rerank)
 *  - Engine (this file's JNI wrapper)
 *  - Verifier (claim checking against cited passages)
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { OstrakaApp() }
    }
}

@Composable
fun OstrakaApp() {
    val context = LocalContext.current
    var question by remember { mutableStateOf("") }
    var answer by remember { mutableStateOf("") }
    var metrics by remember { mutableStateOf("") }
    var running by remember { mutableStateOf(false) }
    var activePipeline by remember { mutableStateOf<Pipeline?>(null) }
    val scope = rememberCoroutineScope()

    MaterialTheme {
        Surface(Modifier.fillMaxSize()) {
            Column(Modifier.padding(16.dp).verticalScroll(rememberScrollState())) {
                Text("Ostraka", style = MaterialTheme.typography.headlineMedium)
                // TODO: airplane-mode banner (radios off => show "OFFLINE" chip).
                Text(
                    "Airplane mode: ?",
                    style = MaterialTheme.typography.labelMedium,
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = question,
                    onValueChange = { question = it },
                    label = { Text("Ask anything") },
                    modifier = Modifier.fillMaxWidth(),
                    maxLines = 4,
                )
                Spacer(Modifier.height(8.dp))
                Row {
                    Button(
                        onClick = {
                            // Full pipeline: plan -> retrieve -> rerank ->
                            // synthesize -> verify. Paths come from the
                            // setup screen (build phase); hard-coded here
                            // for the scaffold.
                            running = true
                            answer = ""
                            metrics = ""
                            scope.launch {
                                val pipeline = Pipeline(
                                    packDir = context.getDir("packs", Context.MODE_PRIVATE),
                                    modelFile = java.io.File(
                                        context.getDir("models", Context.MODE_PRIVATE),
                                        "model.gguf",
                                    ),
                                    rerankerDir = java.io.File(
                                        context.getDir("models", Context.MODE_PRIVATE),
                                        "reranker",
                                    ),
                                )
                                // Keep the handle so Stop can interrupt it.
                                activePipeline = pipeline
                                try {
                                    val res = pipeline.ask(
                                        question,
                                        object : Pipeline.Progress {
                                            override fun onToken(piece: String) {
                                                // Callbacks arrive on a
                                                // background thread; Compose
                                                // state writes need main.
                                                scope.launch(Dispatchers.Main) {
                                                    answer += piece
                                                }
                                            }
                                        },
                                    )
                                    metrics =
                                        "type: ${res.questionType} | " +
                                            "${res.metrics} | verified " +
                                            "${res.verified.size}, " +
                                            "flagged ${res.unverified.size}"
                                    answer = res.answer
                                } catch (e: Exception) {
                                    answer = "Error: ${e.message}"
                                } finally {
                                    activePipeline = null
                                    running = false
                                }
                            }
                        },
                        enabled = !running && question.isNotBlank(),
                    ) { Text("Ask") }
                    Spacer(Modifier.width(8.dp))
                    if (running) {
                        OutlinedButton(
                            onClick = {
                                activePipeline?.stop()
                                running = false
                            }
                        ) { Text("Stop") }
                    }
                }
                Spacer(Modifier.height(12.dp))
                if (metrics.isNotEmpty()) {
                    Text(metrics, style = MaterialTheme.typography.labelSmall)
                    Spacer(Modifier.height(4.dp))
                }
                Text(answer)
            }
        }
    }
}
