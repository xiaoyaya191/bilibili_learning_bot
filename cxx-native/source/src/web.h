#pragma once

#include <atomic>
#include <chrono>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "auth.h"
#include "config.h"
#include "monitor.h"
#include <nlohmann/json.hpp>

namespace httplib {
struct Request;
struct Response;
class Server;
}  // namespace httplib

namespace bili {

// C++ 后端 Web 面板：复用原版 web_panel.html，后端全部由 C++ 实现。
class WebServer {
 public:
  WebServer(App& app, Monitor& monitor, std::string html_path = "");

  bool serve(int port);

 private:
  void monitor_loop();
  void register_routes(httplib::Server& svr);
  bool require_auth(const httplib::Request& req, httplib::Response& res);
  std::string auth_token(const httplib::Request& req) const;
  std::string read_html();
  std::string dashboard_html() const;
  nlohmann::json status_json() const;

  void register_extra_routes(httplib::Server& svr);
  void qr_worker(const std::string& session_id);
  void bot_loop();
  void standby_loop();
  void pm_loop();
  void reminder_loop();
  void proactive_loop();
  void check_private_messages();
  void append_bot_log(const std::string& line);

  App& app_;
  Monitor& monitor_;
  std::string html_path_;
  std::string html_content_;
  Auth auth_;
  std::thread monitor_thread_;
  std::atomic<bool> monitor_running_{false};
  std::chrono::steady_clock::time_point started_at_{};
  std::mutex state_mu_;  // qr_state_ + factory reset token
  nlohmann::json qr_state_ = {{"active", false}, {"status", "idle"}, {"message", ""},
                              {"uid", ""}, {"img_b64", ""}, {"session_id", ""}};
  std::string qr_session_;
  std::thread qr_thread_;
  std::atomic<bool> bot_running_{false};
  std::thread bot_thread_;
  std::atomic<bool> standby_running_{false};
  std::thread standby_thread_;
  std::atomic<bool> pm_running_{false};
  std::thread pm_thread_;
  std::atomic<bool> reminder_running_{false};
  std::thread reminder_thread_;
  std::atomic<bool> proactive_running_{false};
  std::thread proactive_thread_;
  std::mutex bot_log_mu_;
  std::vector<std::string> bot_log_;
  std::string factory_token_;
  long long factory_token_at_ = 0;
  std::vector<std::string> factory_groups_;
};

}  // namespace bili
