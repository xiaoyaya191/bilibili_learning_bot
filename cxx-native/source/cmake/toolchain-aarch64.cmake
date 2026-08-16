set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)

set(CMAKE_C_COMPILER aarch64-linux-gnu-gcc)
set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)

set(CMAKE_EXE_LINKER_FLAGS "-static -static-libgcc -static-libstdc++")

set(BILI_ARM_PREFIX "$ENV{BILI_ARM_PREFIX}")
if(NOT BILI_ARM_PREFIX)
  set(BILI_ARM_PREFIX "/mnt/c/Users/12063/Documents/Codex/2026-08-04/https-github-com-xiaoyaya191-bilibili-learning/work/arm64-build/prefix")
endif()

set(CMAKE_FIND_ROOT_PATH ${BILI_ARM_PREFIX})
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)

set(CURL_ROOT ${BILI_ARM_PREFIX})
set(OPENSSL_ROOT_DIR ${BILI_ARM_PREFIX})
