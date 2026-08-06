#include <jni.h>

#include <android/log.h>
#include <exception>
#include <string>
#include <thread>

#include "config.h"
#include "web.h"

namespace {

const char* kTag = "bilibot";

void run_server(std::string data_dir, int port, std::string html_path) {
  try {
    bili::App app = bili::load_app(data_dir);
    bili::Monitor monitor(app);
    bili::WebServer web(app, monitor, html_path);
    web.serve(port);
  } catch (const std::exception& e) {
    __android_log_print(ANDROID_LOG_ERROR, kTag, "server crashed: %s", e.what());
  } catch (...) {
    __android_log_print(ANDROID_LOG_ERROR, kTag, "server crashed: unknown");
  }
}

}  // namespace

extern "C" JNIEXPORT void JNICALL
Java_com_bilibot_MainActivity_startServer(JNIEnv* env, jobject,
                                          jstring data_dir, jint port,
                                          jstring html_path) {
  const char* d = env->GetStringUTFChars(data_dir, nullptr);
  const char* h = env->GetStringUTFChars(html_path, nullptr);
  std::string ds = d ? d : "";
  std::string hs = h ? h : "";
  if (d) env->ReleaseStringUTFChars(data_dir, d);
  if (h) env->ReleaseStringUTFChars(html_path, h);
  std::thread([ds, hs, port]() { run_server(ds, port, hs); }).detach();
  __android_log_print(ANDROID_LOG_INFO, kTag, "server thread started");
}
