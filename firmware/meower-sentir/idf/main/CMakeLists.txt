set(SKETCH_DIR "${CMAKE_CURRENT_LIST_DIR}/../../Meower_SENTIR")
file(GLOB SKETCH_SRCS "${SKETCH_DIR}/*.cpp")
idf_component_register(SRCS ${SKETCH_SRCS}
                       INCLUDE_DIRS "${SKETCH_DIR}"
                       REQUIRES arduino-esp32 esp_timer esp_wifi)
# mesmas flags da build PlatformIO/Arduino IDE do Meower
target_compile_options(${COMPONENT_LIB} PRIVATE -O3 -fstrict-aliasing -Wno-deprecated-declarations
                       # o codigo original do Meower foi escrito para a Arduino IDE (sem -Werror)
                       -Wno-error=all -Wno-format-truncation -Wno-error=attributes)
target_compile_definitions(${COMPONENT_LIB} PRIVATE ESP32C3)
