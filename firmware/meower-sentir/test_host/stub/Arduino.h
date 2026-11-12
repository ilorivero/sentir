#pragma once
#include <stdint.h>
#include <math.h>
#define IRAM_ATTR
#define INPUT 1
#define INPUT_PULLUP 5
#define INPUT_PULLDOWN 9
#define LOW 0
#define HIGH 1
inline void pinMode(int, int) {}
inline int digitalRead(int) { return 0; }
