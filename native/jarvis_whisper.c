/* Shim mínimo sobre a whisper.dll (whisper.cpp, MIT) para o Jarvis chamar por ctypes sem depender do layout das structs.
 * Compilar: native\build_shim.ps1  ->  bin\whispercpp-vulkan\jarvis_whisper.dll
 * API (todas as strings em UTF-8):
 *   void *jw_init(const char *model_path, int use_gpu, int gpu_device, const char *backend_dir);   NULL se falhar
 *   int    jw_transcribe(void *ctx, const float *pcm16k, int n, const char *lang, const char *prompt, int beam, int threads, char *out, int cap);
 *          devolve o tamanho do texto (>= 0) ou -1 em erro
 *   void   jw_free(void *ctx);
 */
#include <stdlib.h>
#include <string.h>
#include "whisper.h"
#include <windows.h>

#define JW_API __declspec(dllexport)

static void jw_quiet_log(enum ggml_log_level level, const char *text, void *user) { (void)level; (void)text; (void)user; }

typedef void (*load_all_from_path_fn)(const char *);

/* backend_dir: pasta com ggml-vulkan.dll / ggml-cpu.dll (o ggml só procura ao lado do executável, que aqui é o python.exe) */
JW_API void *jw_init(const char *model_path, int use_gpu, int gpu_device, const char *backend_dir) {
    whisper_log_set(jw_quiet_log, NULL);
    if (backend_dir && backend_dir[0]) {
        HMODULE base = GetModuleHandleA("ggml-base.dll");
        load_all_from_path_fn fn = base ? (load_all_from_path_fn)GetProcAddress(base, "ggml_backend_load_all_from_path") : NULL;
        if (fn) fn(backend_dir);
    }
    struct whisper_context_params cp = whisper_context_default_params();
    cp.use_gpu = use_gpu ? true : false;
    cp.gpu_device = gpu_device;
    cp.flash_attn = true;                  /* medido: 0,87 s com flash-attn contra 1,79 s sem */
    return (void *)whisper_init_from_file_with_params(model_path, cp);
}

JW_API int jw_transcribe(void *ctx, const float *pcm, int n, const char *lang, const char *prompt, int beam, int threads, char *out, int cap) {
    if (!ctx || !pcm || n <= 0 || !out || cap <= 1) return -1;
    struct whisper_full_params p = whisper_full_default_params(beam > 1 ? WHISPER_SAMPLING_BEAM_SEARCH : WHISPER_SAMPLING_GREEDY);
    p.n_threads = threads > 0 ? threads : 2;
    p.language = (lang && lang[0]) ? lang : "pt";
    p.initial_prompt = (prompt && prompt[0]) ? prompt : NULL;
    p.translate = false;
    p.no_context = true;
    p.no_timestamps = true;
    p.print_special = false;
    p.print_progress = false;
    p.print_realtime = false;
    p.print_timestamps = false;
    p.suppress_nst = true;
    p.vad = false;                       /* o VAD já foi feito na captura (Silero); o whisper não descarta fala */
    if (beam > 1) p.beam_search.beam_size = beam; else p.greedy.best_of = 1;
    if (whisper_full((struct whisper_context *)ctx, p, pcm, n) != 0) return -1;
    int total = 0;
    out[0] = 0;
    int segs = whisper_full_n_segments((struct whisper_context *)ctx);
    for (int i = 0; i < segs; i++) {
        const char *t = whisper_full_get_segment_text((struct whisper_context *)ctx, i);
        if (!t) continue;
        int l = (int)strlen(t);
        if (total + l >= cap - 1) l = cap - 1 - total;
        if (l <= 0) break;
        memcpy(out + total, t, (size_t)l);
        total += l;
        out[total] = 0;
    }
    return total;
}

JW_API void jw_free(void *ctx) {
    if (ctx) whisper_free((struct whisper_context *)ctx);
}
