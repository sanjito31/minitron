#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <string>
using String = std::string;
struct SerialStub {
    template <typename... Args> void printf(const char *, Args...) {}
    void println(const char *) {}
};
extern SerialStub Serial;
unsigned long millis();
void delay(unsigned long);
void *ps_malloc(size_t);
