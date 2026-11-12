// Equivalente ao Oasis_SENTIR.ino para o ESP-IDF (o .ino nao e compilado pelo CMake).
#include <Arduino.h>
#include "oasis_sentir.h"
void setup() { oasis_setup(); }
void loop() { oasis_loop(); }
