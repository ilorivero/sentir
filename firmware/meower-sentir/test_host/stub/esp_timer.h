#pragma once
#include <stdint.h>
extern int64_t g_fake_now;
inline int64_t esp_timer_get_time() { return g_fake_now; }
typedef void* esp_timer_handle_t;
typedef struct { void (*callback)(void*); void* arg; const char* name; int dispatch_method; bool skip_unhandled_events; } esp_timer_create_args_t;
inline int esp_timer_create(const esp_timer_create_args_t*, esp_timer_handle_t* h) { *h = (void*)1; return 0; }
inline int esp_timer_start_periodic(esp_timer_handle_t, uint64_t) { return 0; }
inline int esp_timer_stop(esp_timer_handle_t) { return 0; }
