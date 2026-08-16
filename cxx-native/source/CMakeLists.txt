cmake_minimum_required(VERSION 3.16)
project(bili_native CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

option(BILI_DISABLE_BUNDLED_FFMPEG "Use system FFmpeg instead of bundled static libs" OFF)
set(BILI_FFMPEG_PREFIX "" CACHE PATH "Optional installed FFmpeg prefix (shared libs)")

find_package(CURL REQUIRED)
find_package(Threads REQUIRED)

add_library(bili_core
  src/config.cpp
  src/cookies.cpp
  src/net.cpp
  src/dns.cpp
  src/urlcodec.cpp
  src/wbi.cpp
  src/md5.cpp
  src/qr.cpp
  src/login.cpp
  src/state.cpp
  src/ai.cpp
  src/api.cpp
  src/monitor.cpp
  src/analysis.cpp
  src/agent.cpp
  src/proactive.cpp
  src/rag.cpp
  src/websearch.cpp
  src/verify.cpp
  src/psycho.cpp
  src/platform_adapter.cpp
  src/asr.cpp
  src/video_asr.cpp
  src/kb.cpp
  src/zipwriter.cpp
  src/export.cpp
  src/reminders.cpp
  src/version_history.cpp
  src/factory_reset.cpp
  src/frames.cpp
  src/logbuf.cpp
  src/web.cpp
  src/web_panel.cpp
  src/auth.cpp
  src/auth_refresh.cpp
  src/sha256.cpp
  third_party/qrcodegen.cpp
)
target_include_directories(bili_core PUBLIC src third_party)
target_link_libraries(bili_core PUBLIC CURL::libcurl Threads::Threads)

find_package(ZLIB QUIET)
if(ZLIB_FOUND AND NOT MINGW)
  target_link_libraries(bili_core PUBLIC ZLIB::ZLIB)
  target_compile_definitions(bili_core PUBLIC BILI_USE_ZLIB)
elseif(ANDROID)
  target_link_libraries(bili_core PUBLIC z)
  target_compile_definitions(bili_core PUBLIC BILI_USE_ZLIB)
endif()

set(FFMPEG_PREFIX "")
if(BILI_FFMPEG_PREFIX AND EXISTS ${BILI_FFMPEG_PREFIX}/include/libavformat/avformat.h)
  set(FFMPEG_PREFIX ${BILI_FFMPEG_PREFIX})
elseif(NOT BILI_DISABLE_BUNDLED_FFMPEG AND WIN32)
  if(EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/third_party/ffmpeg-win64/include/libavformat/avformat.h)
    set(FFMPEG_PREFIX ${CMAKE_CURRENT_SOURCE_DIR}/third_party/ffmpeg-win64)
  endif()
elseif(NOT BILI_DISABLE_BUNDLED_FFMPEG AND CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64|ARM64")
  if(EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/third_party/ffmpeg-termux-arm64/include/libavformat/avformat.h)
    set(FFMPEG_PREFIX ${CMAKE_CURRENT_SOURCE_DIR}/third_party/ffmpeg-termux-arm64)
  elseif(EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/third_party/ffmpeg-linux-arm64/include/libavformat/avformat.h)
    set(FFMPEG_PREFIX ${CMAKE_CURRENT_SOURCE_DIR}/third_party/ffmpeg-linux-arm64)
  endif()
elseif(NOT BILI_DISABLE_BUNDLED_FFMPEG)
  if(EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/third_party/ffmpeg-linux-x64/include/libavformat/avformat.h)
    set(FFMPEG_PREFIX ${CMAKE_CURRENT_SOURCE_DIR}/third_party/ffmpeg-linux-x64)
  endif()
endif()
if(EXISTS ${FFMPEG_PREFIX}/include/libavformat/avformat.h)
  target_compile_definitions(bili_core PUBLIC BILI_USE_FFMPEG)
  target_include_directories(bili_core PUBLIC ${FFMPEG_PREFIX}/include)
  if(WIN32)
    target_link_libraries(bili_core PUBLIC
      ${FFMPEG_PREFIX}/lib/libavformat.a
      ${FFMPEG_PREFIX}/lib/libavcodec.a
      ${FFMPEG_PREFIX}/lib/libswscale.a
      ${FFMPEG_PREFIX}/lib/libavutil.a
      ws2_32 bcrypt secur32 user32 ole32 uuid strmiids atomic)
  elseif(EXISTS ${FFMPEG_PREFIX}/lib/libavformat.a)
    target_link_libraries(bili_core PUBLIC
      ${FFMPEG_PREFIX}/lib/libavformat.a
      ${FFMPEG_PREFIX}/lib/libavcodec.a
      ${FFMPEG_PREFIX}/lib/libswscale.a
      ${FFMPEG_PREFIX}/lib/libavutil.a)
    find_package(OpenSSL REQUIRED)
    target_link_libraries(bili_core PUBLIC OpenSSL::SSL OpenSSL::Crypto dl pthread)
  else()
    target_link_directories(bili_core PUBLIC ${FFMPEG_PREFIX}/lib)
    target_link_libraries(bili_core PUBLIC avformat avcodec swscale avutil)
    if(ANDROID)
      target_link_libraries(bili_core PUBLIC z log)
    endif()
  endif()
endif()
if(NOT FFMPEG_PREFIX)
  find_package(PkgConfig QUIET)
  if(PKG_CONFIG_FOUND)
    pkg_check_modules(SYS_AVFORMAT IMPORTED_TARGET libavformat)
    pkg_check_modules(SYS_AVCODEC IMPORTED_TARGET libavcodec)
    pkg_check_modules(SYS_AVUTIL IMPORTED_TARGET libavutil)
    pkg_check_modules(SYS_SWSCALE IMPORTED_TARGET libswscale)
    if(TARGET PkgConfig::SYS_AVFORMAT AND TARGET PkgConfig::SYS_AVCODEC AND TARGET PkgConfig::SYS_AVUTIL AND TARGET PkgConfig::SYS_SWSCALE)
      target_compile_definitions(bili_core PUBLIC BILI_USE_FFMPEG)
      target_link_libraries(bili_core PUBLIC
        PkgConfig::SYS_AVFORMAT PkgConfig::SYS_AVCODEC
        PkgConfig::SYS_AVUTIL PkgConfig::SYS_SWSCALE)
    endif()
  endif()
endif()
if(WIN32)
  target_link_libraries(bili_core PUBLIC ws2_32)

endif()

add_executable(bili src/main.cpp)
target_link_libraries(bili PRIVATE bili_core)

enable_testing()
add_executable(bili_tests tests/test_main.cpp)
target_link_libraries(bili_tests PRIVATE bili_core)
add_test(NAME core_tests COMMAND bili_tests)

if(WIN32)
  target_link_libraries(bili_core PUBLIC ws2_32)
  if(MINGW)
    target_link_options(bili PRIVATE -static)
    target_link_options(bili_tests PRIVATE -static)
  endif()
endif()

option(BILI_BUILD_JNI "Build Android JNI library" OFF)
if(BILI_BUILD_JNI)
  add_library(bilibot SHARED src/jni.cpp)
  target_link_libraries(bilibot PRIVATE bili_core android log)
  set_target_properties(bilibot PROPERTIES OUTPUT_NAME bilibot)
endif()
