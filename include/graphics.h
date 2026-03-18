#pragma once

#include <freertos/semphr.h>

struct graphic_state {
        void *_buf;
        size_t _len;
        SemaphoreHandle_t _mutex;
        int _counter;
};

int init_graphics(const void *webp, size_t len);

int update_graphics(const void *webp, size_t len);

int draw_webp_graphic(uint8_t *buf, size_t len);

void loop_graphics(void *arg);
