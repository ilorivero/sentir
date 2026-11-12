# Bibliotecas Arduino do Monitor Oasis como um componente IDF.
# As pastas ficam em firmware/oasis-sentir/libraries (baixadas por fetch_libs.sh / fetch_libs.ps1,
# nas MESMAS versoes indicadas para a Arduino IDE).
set(LIBROOT "${CMAKE_CURRENT_LIST_DIR}/../../../libraries")
set(LIBS SparkFun_MAX3010x_Sensor_Library Adafruit-MLX90614-Library Adafruit_AHTX0
         Adafruit_BMP280_Library Adafruit_BusIO Adafruit_Sensor)
set(srcs)
set(incs)
foreach(lib ${LIBS})
  if(EXISTS "${LIBROOT}/${lib}/src")
    set(dir "${LIBROOT}/${lib}/src")
  else()
    set(dir "${LIBROOT}/${lib}")
  endif()
  if(NOT EXISTS "${dir}")
    message(FATAL_ERROR "Biblioteca ${lib} ausente em ${LIBROOT}. Rode firmware/oasis-sentir/fetch_libs.sh (ou .ps1).")
  endif()
  file(GLOB s "${dir}/*.cpp" "${dir}/*.c")
  list(APPEND srcs ${s})
  list(APPEND incs "${dir}")
endforeach()
idf_component_register(SRCS ${srcs} INCLUDE_DIRS ${incs} REQUIRES arduino-esp32 esp_timer esp_netif)
target_compile_options(${COMPONENT_LIB} PRIVATE -Wno-error=all -Wno-error=parentheses -Wno-parentheses -Wno-unused-variable -Wno-format-truncation)
