# Top-level CMakeLists for the ESP-IDF h1_full demo.
#
# Build:
#   . $HOME/esp/esp-idf/export.sh      # or `get_idf`
#   cd sdk/esp32/h1_full
#   idf.py set-target esp32s3
#   idf.py -p /dev/cu.usbmodem2101 flash monitor
cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(h1_full)
