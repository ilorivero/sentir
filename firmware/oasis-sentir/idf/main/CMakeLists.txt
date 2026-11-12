set(SKETCH_DIR "${CMAKE_CURRENT_LIST_DIR}/../../Oasis_SENTIR")
idf_component_register(SRCS "${SKETCH_DIR}/oasis_sentir.cpp" "sketch_main.cpp"
                       INCLUDE_DIRS "${SKETCH_DIR}"
                       REQUIRES arduino-esp32 esp_timer esp_netif oasis_arduino_libs)
target_compile_options(${COMPONENT_LIB} PRIVATE -Wno-error=all -Wno-format-truncation)
