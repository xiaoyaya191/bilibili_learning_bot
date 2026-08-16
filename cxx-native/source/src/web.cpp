#include "web.h"

#include <chrono>
#include <filesystem>
#include "fscompat.h"
#include <fstream>
#include <sstream>
#include <thread>
#include <cmath>
#include <ctime>
#include <cstdio>
#include <exception>

#include "analysis.h"
#include "cookies.h"
#include "export.h"
#include "httplib.h"
#include "kb.h"
#include "logbuf.h"
#include "platform.h"
#include "net.h"

namespace fs = std::filesystem;

namespace bili {
namespace {

std::string read_file(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) return "";
  std::ostringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

bool write_file(const std::string& path, const std::string& content) {
  fs::create_directories(fs::path(path).parent_path());
  std::ofstream out(path, std::ios::binary);
  if (!out) return false;
  out << content;
  return out.good();
}

std::string utf8_safe(const std::string& s) {
  std::string out;
  out.reserve(s.size());
  size_t i = 0;
  auto hex = [&out](unsigned char c) {
    char b[8];
    std::snprintf(b, sizeof(b), "\\x%02x", c);
    out += b;
  };
  while (i < s.size()) {
    unsigned char c = (unsigned char)s[i];
    if (c < 0x80) {
      if (c >= 0x20 || c == '\t' || c == '\n' || c == '\r') {
        out += (char)c;
      } else {
        hex(c);
      }
      i++;
      continue;
    }
    int len = 0;
    if ((c & 0xE0) == 0xC0) len = 2;
    else if ((c & 0xF0) == 0xE0) len = 3;
    else if ((c & 0xF8) == 0xF0) len = 4;
    if (len == 0 || i + len > s.size()) {
      hex(c);
      i++;
      continue;
    }
    bool ok = true;
    for (int k = 1; k < len; k++) {
      if (((unsigned char)s[i + k] & 0xC0) != 0x80) {
        ok = false;
        break;
      }
    }
    if (!ok) {
      hex(c);
      i++;
      continue;
    }
    out.append(s, i, len);
    i += len;
  }
  return out;
}

using json = nlohmann::json;
std::string json_str(const json& j) { return j.dump(); }

std::string ts_suffix() {
  std::time_t t = std::time(nullptr);
  std::tm tm{};
  localtime_r(&t, &tm);
  char buf[40];
  std::strftime(buf, sizeof(buf), "%Y%m%d_%H%M%S", &tm);
  return buf;
}

std::vector<std::string> tail_file(const std::string& path, size_t n) {
  std::string raw = read_file(path);
  std::vector<std::string> lines;
  size_t pos = 0;
  while (pos <= raw.size()) {
    size_t nl = raw.find('\n', pos);
    std::string line = raw.substr(pos, nl == std::string::npos ? std::string::npos : nl - pos);
    if (!line.empty() && line.back() == '\r') line.pop_back();
    line = utf8_safe(line);
    if (!line.empty()) lines.push_back(line);
    if (nl == std::string::npos) break;
    pos = nl + 1;
  }
  if (lines.size() > n) lines.erase(lines.begin(), lines.end() - n);
  return lines;
}

std::string join_lines(const std::vector<std::string>& lines) {
  std::string out;
  for (const auto& l : lines) {
    if (!out.empty()) out += "\n";
    out += l;
  }
  return out;
}

void mask_keys(nlohmann::json& cfg) {
  for (const char* key : {"unified_api_key", "vision_api_key"}) {
    if (cfg.contains("api") && cfg["api"].contains(key) && cfg["api"][key].is_string()) {
      std::string v = cfg["api"][key].get<std::string>();
      if (v.size() > 8) cfg["api"][key] = v.substr(0, 4) + "****" + v.substr(v.size() - 4);
    }
  }
}

std::string bearer_token(const httplib::Request& req) {
  std::string h = req.get_header_value("Authorization");
  if (h.rfind("Bearer ", 0) == 0) return h.substr(7);
  return "";
}

std::string login_page_html() {
  return R"HTML(<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Panel Login</title><style>body{margin:0;font-family:system-ui,'Microsoft YaHei',sans-serif;background:#f4f5f7;display:flex;align-items:center;justify-content:center;min-height:100vh}.card{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:36px;width:92%;max-width:380px;box-shadow:0 10px 30px rgba(0,0,0,.08)}h1{font-size:20px;margin:0 0 6px}p{color:#6b7280;font-size:13px;margin:0 0 24px}label{display:block;font-size:12px;color:#6b7280;margin:0 0 6px}input{width:100%;box-sizing:border-box;padding:11px 13px;border:1px solid #d1d5db;border-radius:6px;font-size:15px;margin-bottom:16px}button{width:100%;padding:11px;background:#d97757;border:0;border-radius:6px;color:#fff;font-size:14px;cursor:pointer}.msg{font-size:13px;margin-top:12px;min-height:18px}.err{color:#b42318}.ok{color:#267a45}.link{display:block;text-align:center;margin-top:14px;font-size:12px;color:#6b7280;text-decoration:none}</style></head><body><div class="card"><h1>Panel Login</h1><p>Login to open the management panel</p><label>Username</label><input id="u" autocomplete="username"><label>Password</label><input id="p" type="password" autocomplete="current-password"><button onclick="doLogin()">Login</button><div class="msg" id="msg"></div><a class="link" href="/forgot-password">Forgot password?</a></div><script>async function doLogin(){var u=document.getElementById('u').value.trim(),p=document.getElementById('p').value,m=document.getElementById('msg');if(!u||!p){m.textContent='Enter username and password';m.className='msg err';return}try{var r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});var d=await r.json();if(d.ok){m.textContent='Login ok, redirecting...';m.className='msg ok';setTimeout(function(){location.href='/'},400)}else{m.textContent=d.message||'Login failed';m.className='msg err'}}catch(e){m.textContent='Request failed';m.className='msg err'}}document.addEventListener('keydown',function(e){if(e.key==='Enter')doLogin()})</script></body></html>)HTML";
}

std::string setup_page_html() {
  return R"HTML(<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>First Time Setup</title><style>body{margin:0;font-family:system-ui,'Microsoft YaHei',sans-serif;background:#f4f5f7;display:flex;align-items:center;justify-content:center;min-height:100vh}.card{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:36px;width:92%;max-width:380px;box-shadow:0 10px 30px rgba(0,0,0,.08)}h1{font-size:20px;margin:0 0 6px}p{color:#6b7280;font-size:13px;margin:0 0 24px}label{display:block;font-size:12px;color:#6b7280;margin:0 0 6px}input{width:100%;box-sizing:border-box;padding:11px 13px;border:1px solid #d1d5db;border-radius:6px;font-size:15px;margin-bottom:16px}button{width:100%;padding:11px;background:#d97757;border:0;border-radius:6px;color:#fff;font-size:14px;cursor:pointer}.msg{font-size:13px;margin-top:12px;min-height:18px}.err{color:#b42318}.ok{color:#267a45}</style></head><body><div class="card"><h1>First Time Setup</h1><p>Create the panel username and password</p><label>Username (at least 2 chars)</label><input id="u" autocomplete="username"><label>Password (at least 4 chars)</label><input id="p" type="password" autocomplete="new-password"><button onclick="doSetup()">Create Account</button><div class="msg" id="msg"></div></div><script>async function doSetup(){var u=document.getElementById('u').value.trim(),p=document.getElementById('p').value,m=document.getElementById('msg');if(!u||!p){m.textContent='Enter username and password';m.className='msg err';return}try{var r=await fetch('/api/auth/setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});var d=await r.json();if(d.ok){m.textContent='Account created, redirecting...';m.className='msg ok';setTimeout(function(){location.href='/login'},400)}else{m.textContent=d.message||'Setup failed';m.className='msg err'}}catch(e){m.textContent='Request failed';m.className='msg err'}}document.addEventListener('keydown',function(e){if(e.key==='Enter')doSetup()})</script></body></html>)HTML";
}

std::string simple_page_html(const char* title, const char* body) {
  std::string html = R"HTML(<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>)HTML";
  html += title;
  html += R"HTML(</title><style>body{margin:0;font-family:system-ui,'Microsoft YaHei',sans-serif;background:#f4f5f7;display:flex;align-items:center;justify-content:center;min-height:100vh}.card{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:36px;width:92%;max-width:400px;box-shadow:0 10px 30px rgba(0,0,0,.08)}h1{font-size:20px;margin:0 0 14px}p{color:#374151;font-size:14px;line-height:1.7;margin:0 0 18px}a{color:#d97757;text-decoration:none;font-size:14px}</style></head><body><div class="card"><h1>)HTML";
  html += title;
  html += R"HTML(</h1>)HTML";
  html += body;
  html += R"HTML(</div></body></html>)HTML";
  return html;
}

}  // namespace

WebServer::WebServer(App& app, Monitor& monitor, std::string html_path)
    : app_(app), monitor_(monitor), html_path_(std::move(html_path)), auth_(app) {
  started_at_ = std::chrono::steady_clock::now();
  html_content_ = read_html();
}

std::string WebServer::read_html() {
  std::vector<std::string> candidates;
  if (!html_path_.empty()) candidates.push_back(html_path_);
  candidates.push_back("web_panel.html");
  candidates.push_back("../web_panel.html");
  candidates.push_back("../../web_panel.html");
  for (const auto& p : candidates) {
    std::string content = read_file(p);
    if (!content.empty()) return content;
  }
  return dashboard_html();
}

std::string WebServer::dashboard_html() const {
  return R"(<!doctype html><html><head><meta charset="utf-8"><title>bili_native</title>
<style>body{font-family:system-ui;background:#f4f5f7;color:#111;padding:24px}h1{font-size:20px}pre{background:#0f172a;color:#d1d5db;padding:12px;border-radius:8px}</style></head>
<body><h1>bili_native (web_panel.html 未找到)</h1><pre id="s"></pre>
<script>fetch('/api/info').then(r=>r.json()).then(j=>document.getElementById('s').textContent=JSON.stringify(j,null,2));</script></body></html>)";
}

void WebServer::monitor_loop() {
  while (monitor_running_.load()) {
    monitor_.check_once();
    for (int i = 0; i < 50 && monitor_running_.load(); i++) {
      std::this_thread::sleep_for(std::chrono::milliseconds(200));
    }
  }
}

nlohmann::json WebServer::status_json() const {
  nlohmann::json out;
  bool logged_in = !cookie_value(app_, "SESSDATA").empty();
  out = {
      {"uid", app_.uid},
      {"logged_in", logged_in},
      {"bili_logged_in", logged_in},
      {"data_dir", app_.paths.data_dir},
      {"user_data_dir", app_.paths.user_data_dir},
      {"cookie_file", app_.paths.cookie_file},
      {"config_file", app_.paths.config_file},
      {"monitor_running", monitor_running_.load()},
      {"monitor_config", app_.monitor},
      {"bot_running", bot_running_.load()},
      {"version", "1.0.0-cxx"},
      {"platform", "cpp"},
      {"cwd", app_.paths.user_data_dir},
      {"model_brain", get_str(app_, "api", "model_brain")},
      {"api_configured", !get_str(app_, "api", "unified_api_key").empty() &&
                        !get_str(app_, "api", "unified_base_url").empty()},
      {"comment_mode", app_.config.value("behavior", nlohmann::json::object()).value("comment_mode", "real")},
      {"ai_marker", app_.config.value("behavior", nlohmann::json::object()).value("ai_marker", "")},
      {"safety_enabled", app_.config.value("reply_safety", nlohmann::json::object()).value("enabled", false)},
      {"agent_enabled", app_.config.value("agent", nlohmann::json::object()).value("enabled", false)},
      {"pm_enabled", app_.config.value("private_message", nlohmann::json::object()).value("enabled", false)},
      {"notification_mode", app_.config.value("standby", nlohmann::json::object()).value("notification_mode", true)},
      {"asr_enabled", app_.config.value("asr", nlohmann::json::object()).value("enabled", false)},
      {"asr_backend", app_.config.value("asr", nlohmann::json::object()).value("backend", "none")},
      {"diary_enabled", false},
      {"evolution_enabled", false},
      {"standby_running", false},
      {"standby_stats", nlohmann::json::object()},
      {"cost_total", 0},
      {"config_sections", app_.config.size()},
      {"data_files", 0},
  };
  nlohmann::json profile = nlohmann::json::object();
  if (logged_in) {
    NetClient net(app_);
    NetResponse resp = net.get("https://api.bilibili.com/x/web-interface/nav");
    try {
      nlohmann::json j = nlohmann::json::parse(resp.body);
      if (j.value("code", -1) == 0) {
        const auto& d = j["data"];
        profile = {{"uid", std::to_string((long long)d.value("mid", 0LL))},
                   {"name", d.value("uname", "")},
                   {"face", d.value("face", "")}};
      }
    } catch (...) {
    }
  }
  out["bili_profile"] = profile;
  if (profile.empty() && app_.uid != 0) {
    profile = {{"uid", std::to_string(app_.uid)}, {"name", ""}, {"face", ""}};
    out["bili_profile"] = profile;
  }
  nlohmann::json mood = nlohmann::json::object();
  {
    std::ifstream in(app_.paths.data_dir + "/mood_state.json");
    if (in) {
      try { mood = nlohmann::json::parse(in); } catch (...) {}
    }
  }
  out["mood"] = mood.empty() ? nlohmann::json()
                             : nlohmann::json({{"mood", mood.value("mood", "calm")},
                                               {"energy", mood.value("energy", 100)}});
  std::string persona_active =
      app_.config.value("persona", nlohmann::json::object()).value("active_persona", "");
  out["persona"] = persona_active.empty()
                       ? nlohmann::json()
                       : nlohmann::json({{"active", persona_active}});
  long long uptime = std::chrono::duration_cast<std::chrono::seconds>(
                         std::chrono::steady_clock::now() - started_at_)
                         .count();
  out["uptime_seconds"] = std::max<long long>(0, uptime);
  char up[64];
  std::snprintf(up, sizeof(up), "%lldh%lldm%llds", uptime / 3600, (uptime % 3600) / 60,
                uptime % 60);
  out["uptime"] = up;
  KnowledgeBase kb(app_.paths.knowledge_metadata_file, app_.paths.knowledge_base_dir);
  kb.load();
  out["knowledge_notes"] = kb.note_count();
  out["exports"] = nlohmann::json::array();
  out["files"] = nlohmann::json::object();
  return out;
}

std::string WebServer::auth_token(const httplib::Request& req) const {
  std::string t = req.get_header_value("Cookie");
  size_t p = t.find("bili_token=");
  if (p != std::string::npos) {
    size_t start = p + 11;
    size_t end = t.find(';', start);
    if (end == std::string::npos) end = t.size();
    return t.substr(start, end - start);
  }
  return bearer_token(req);
}

bool WebServer::require_auth(const httplib::Request& req, httplib::Response& res) {
  if (auth_.valid(auth_token(req))) return true;
  res.status = 401;
  res.set_content("{\"ok\":false,\"message\":\"unauthorized\"}", "application/json");
  return false;
}

void WebServer::register_routes(httplib::Server& svr) {
  auto html = [this](const httplib::Request&, httplib::Response& res) {
    res.set_content(html_content_, "text/html; charset=utf-8");
  };
  svr.Get("/", [this](const httplib::Request& req, httplib::Response& res) {
    if (!auth_.configured()) {
      res.status = 302;
      res.set_header("Location", "/setup");
      return;
    }
    if (!auth_.valid(auth_token(req))) {
      res.status = 302;
      res.set_header("Location", "/login");
      return;
    }
    res.set_content(html_content_, "text/html; charset=utf-8");
  });
  svr.Get("/login", [this](const httplib::Request&, httplib::Response& res) {
    res.set_content(login_page_html(), "text/html; charset=utf-8");
  });
  svr.Get("/setup", [this](const httplib::Request&, httplib::Response& res) {
    res.set_content(setup_page_html(), "text/html; charset=utf-8");
  });
  svr.Get("/disclaimer", [this](const httplib::Request&, httplib::Response& res) {
    res.set_content(simple_page_html("Disclaimer",
        "<p>This project is for learning purposes only. Use at your own risk.</p><a href=\"/login\">Back to login</a>"),
        "text/html; charset=utf-8");
  });
  svr.Get("/forgot-password", [this](const httplib::Request&, httplib::Response& res) {
    res.set_content(simple_page_html("Forgot Password",
        "<p>Contact the panel owner to reset the password.</p><a href=\"/login\">Back to login</a>"),
        "text/html; charset=utf-8");
  });
  svr.Get("/account-security", [this](const httplib::Request&, httplib::Response& res) {
    res.set_content(simple_page_html("Account Security",
        "<p>Security questions are managed by the panel owner.</p><a href=\"/login\">Back to login</a>"),
        "text/html; charset=utf-8");
  });
  svr.Get("/like-review", html);
  svr.Get("/ppt", html);
  svr.Get("/research", html);

  svr.Get("/api/health", [](const httplib::Request&, httplib::Response& res) {
    res.set_content("{\"ok\":true}", "application/json");
  });
  svr.Post("/api/disclaimer/confirm", [](const httplib::Request&, httplib::Response& res) {
    res.set_content("{\"ok\":true}", "application/json");
  });

  svr.Get("/api/auth/status", [this](const httplib::Request& req, httplib::Response& res) {
    nlohmann::json out = {{"configured", auth_.configured()},
                          {"authed", auth_.valid(auth_token(req))}};
    res.set_content(json_str(out), "application/json");
  });
  svr.Post("/api/auth/setup", [this](const httplib::Request& req, httplib::Response& res) {
    try {
      auto j = nlohmann::json::parse(req.body);
      std::string user = j.value("username", "");
      std::string pass = j.value("password", "");
      if (!auth_.setup(user, pass)) {
        res.set_content("{\"ok\":false,\"message\":\"username>=2, password>=4\"}", "application/json");
        return;
      }
      res.set_content("{\"ok\":true}", "application/json");
    } catch (...) {
      res.set_content("{\"ok\":false,\"message\":\"bad json\"}", "application/json");
    }
  });
  svr.Post("/api/auth/login", [this](const httplib::Request& req, httplib::Response& res) {
    try {
      auto j = nlohmann::json::parse(req.body);
      std::string token = auth_.login(j.value("username", ""), j.value("password", ""));
      if (token.empty()) {
        res.set_content("{\"ok\":false,\"message\":\"login failed\"}", "application/json");
        return;
      }
      res.set_header("Set-Cookie", "bili_token=" + token + "; Path=/; HttpOnly");
      res.set_content("{\"ok\":true}", "application/json");
    } catch (...) {
      res.set_content("{\"ok\":false,\"message\":\"bad json\"}", "application/json");
    }
  });
  svr.Post("/api/auth/logout", [this](const httplib::Request& req, httplib::Response& res) {
    auth_.logout(auth_token(req));
    res.set_content("{\"ok\":true}", "application/json");
  });

  svr.Get("/api/info", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    res.set_content(json_str(status_json()), "application/json");
  });
  svr.Get("/api/status", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    res.set_content(json_str(status_json()), "application/json");
  });

  svr.Get("/api/config", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    nlohmann::json cfg = app_.config;
    mask_keys(cfg);
    res.set_content(json_str(cfg), "application/json");
  });
  svr.Post("/api/config", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    try {
      auto j = nlohmann::json::parse(req.body);
      if (j.contains("config") && j["config"].is_object()) app_.config = j["config"];
      else app_.config = j;
      if (j.contains("monitor") && j["monitor"].is_object()) app_.monitor = j["monitor"];
      bool ok = save_config_file(app_) &&
                write_file(app_.paths.monitor_config_file, app_.monitor.dump(2));
      res.set_content(ok ? "{\"ok\":true,\"message\":\"config saved\"}" : "{\"ok\":false}", "application/json");
    } catch (...) {
      res.set_content("{\"ok\":false,\"message\":\"bad json\"}", "application/json");
    }
  });

  svr.Get("/api/logs", [this](const httplib::Request& req, httplib::Response& res) {
    size_t n = 800;
    std::string raw_n = req.get_param_value("limit");
    if (raw_n.empty()) raw_n = req.get_param_value("n");
    try {
      if (!raw_n.empty()) n = (size_t)std::max(1LL, std::stoll(raw_n));
    } catch (...) {
    }
    std::string source = req.get_param_value("source");
    std::vector<std::string> lines;
    if (source.empty() || source == "all" || source == "bot") {
      auto bot = tail_file(app_.paths.log_dir + "/web_bot_runtime.log", n);
      lines.insert(lines.end(), bot.begin(), bot.end());
    }
    if (source.empty() || source == "all" || source == "monitor") {
      auto mon = tail_file(app_.paths.log_dir + "/web_monitor_runtime.log", n);
      lines.insert(lines.end(), mon.begin(), mon.end());
    }
    if (source == "reviews") {
      auto rev = tail_file(app_.paths.log_dir + "/web_review_runtime.log", n);
      lines.insert(lines.end(), rev.begin(), rev.end());
    }
    if (lines.size() > n) lines.erase(lines.begin(), lines.end() - n);
    res.set_content(json_str({{"lines", lines}, {"count", lines.size()}, {"source", source}}),
                    "application/json");
  });
  svr.Get("/api/monitor/output", [this](const httplib::Request& req, httplib::Response& res) {
    size_t n = 80;
    try {
      n = (size_t)std::max(1LL, std::stoll(req.get_param_value("limit").empty() ? "80" : req.get_param_value("limit")));
    } catch (...) {
    }
    auto file_lines = tail_file(app_.paths.log_dir + "/web_monitor_runtime.log", n);
    auto buf_lines = LogBuffer::instance().tail(n);
    std::vector<std::string> all;
    all.reserve(file_lines.size() + buf_lines.size());
    all.insert(all.end(), file_lines.begin(), file_lines.end());
    all.insert(all.end(), buf_lines.begin(), buf_lines.end());
    if (all.size() > n) all.erase(all.begin(), all.end() - n);
    res.set_content(json_str({{"output", join_lines(all)}, {"running", monitor_running_.load()}}),
                    "application/json");
  });
  svr.Post("/api/monitor/clear", [this](const httplib::Request&, httplib::Response& res) {
    LogBuffer::instance().clear();
    std::ofstream out(app_.paths.log_dir + "/web_monitor_runtime.log", std::ios::binary | std::ios::trunc);
    if (out) out << "";
    res.set_content("{\"ok\":true,\"message\":\"monitor log cleared\"}", "application/json");
  });
  svr.Get("/api/monitor/status", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    res.set_content(json_str({{"running", monitor_running_.load()}}), "application/json");
  });
  svr.Post("/api/monitor/start", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    if (!monitor_running_.exchange(true)) {
      monitor_thread_ = std::thread([this] { monitor_loop(); });
    }
    res.set_content("{\"ok\":true}", "application/json");
  });
  svr.Post("/api/monitor/stop", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    monitor_running_.store(false);
    if (monitor_thread_.joinable()) monitor_thread_.detach();
    res.set_content("{\"ok\":true}", "application/json");
  });
  svr.Post("/api/monitor/pause", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    try {
      auto j = nlohmann::json::parse(req.body);
      bool paused = j.value("paused", false);
      if (paused) {
        monitor_running_.store(false);
        if (monitor_thread_.joinable()) monitor_thread_.detach();
      } else if (!monitor_running_.exchange(true)) {
        monitor_thread_ = std::thread([this] { monitor_loop(); });
      }
    } catch (...) {
    }
    res.set_content("{\"ok\":true}", "application/json");
  });
  svr.Post("/api/monitor/config", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    try {
      auto j = nlohmann::json::parse(req.body);
      for (auto& [k, v] : j.items()) app_.monitor[k] = v;
      write_file(app_.paths.monitor_config_file, app_.monitor.dump(2));
      res.set_content("{\"ok\":true}", "application/json");
    } catch (...) {
      res.set_content("{\"ok\":false,\"message\":\"bad json\"}", "application/json");
    }
  });

  svr.Get("/api/kb/stats", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    KnowledgeBase kb(app_.paths.knowledge_metadata_file, app_.paths.knowledge_base_dir);
    kb.load();
    res.set_content(json_str({{"note_count", kb.note_count()}, {"total_files", kb.note_count()},
                            {"exists", fs::exists(app_.paths.knowledge_base_dir)},
                            {"categories", nlohmann::json::object()}}), "application/json");
  });
  svr.Get("/api/kb/list-files", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    KnowledgeBase kb(app_.paths.knowledge_metadata_file, app_.paths.knowledge_base_dir);
    kb.load();
    json files = json::array();
    const auto& idx = kb.metadata().value("file_index", nlohmann::json::object());
    if (idx.is_object()) {
      for (auto& [cat, entries] : idx.items()) {
        for (const auto& e : entries) {
          json item = e;
          item["category_path"] = cat;
          item["size_kb"] = 0;
          std::string rel = item.value("path", "");
          std::string full = app_.paths.knowledge_base_dir + "/" + rel;
          std::ifstream f(full, std::ios::binary | std::ios::ate);
          if (f) item["size_kb"] = (long long)(f.tellg()) / 1024;
          files.push_back(item);
        }
      }
    }
    res.set_content(json_str({{"ok", true}, {"files", files}, {"total", files.size()}}), "application/json");
  });
  svr.Get("/api/kb/read-file", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string rel = req.get_param_value("path");
    fs::path root = fs::absolute(fs::path(app_.paths.knowledge_base_dir));
    fs::path target = fs::absolute(root / rel);
    std::string tr = target.string();
    std::string rr = root.string();
    if (tr.rfind(rr, 0) != 0) {
      res.set_content("{\"ok\":false,\"message\":\"forbidden\"}", "application/json");
      return;
    }
    res.set_content(json_str({{"ok", true}, {"content", read_file(tr)}}), "application/json");
  });
  svr.Get("/api/kb/custom-search", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    KnowledgeBase kb(app_.paths.knowledge_metadata_file, app_.paths.knowledge_base_dir);
    kb.load();
    auto hits = kb.search(req.get_param_value("q"), 5);
    nlohmann::json arr = nlohmann::json::array();
    for (const auto& h : hits) {
      arr.push_back({{"path", h.path}, {"title", h.title}, {"score", h.score}, {"snippet", h.snippet}});
    }
    res.set_content(json_str({{"hits", arr}}), "application/json");
  });

  svr.Post("/api/action/analyze-video", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    try {
      auto j = nlohmann::json::parse(req.body);
      std::string bvid = j.value("bvid", "");
      NetClient net(app_);
      AiClient ai(app_, net);
      VideoAnalysis va;
      std::string err;
      if (!analyze_video(app_, net, ai, bvid, va, err)) {
        res.set_content(json_str({{"ok", false}, {"message", err}}), "application/json");
        return;
      }
      KnowledgeBase kb(app_.paths.knowledge_metadata_file, app_.paths.knowledge_base_dir);
      kb.load();
      kb.add_note(detect_category(va.info.title, va.ai_summary), va.info.title, bvid, va.ai_summary);
      kb.add_note(detect_category(va.info.title, va.ai_summary), va.info.title, bvid, va.ai_summary, app_.config);
      res.set_content(json_str({{"ok", true}, {"summary", va.ai_summary}, {"title", va.info.title}}),
                      "application/json");
    } catch (...) {
      res.set_content("{\"ok\":false,\"message\":\"bad json\"}", "application/json");
    }
  });
  svr.Post("/api/action/deep-dive", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    try {
      auto j = nlohmann::json::parse(req.body);
      std::string keyword = j.value("keyword", "");
      int count = j.value("count", 3);
      NetClient net(app_);
      AiClient ai(app_, net);
      std::vector<DeepResult> results;
      std::string err;
      if (!deep_dive(app_, net, ai, keyword, count, results, err)) {
        res.set_content(json_str({{"ok", false}, {"message", err}}), "application/json");
        return;
      }
      nlohmann::json arr = nlohmann::json::array();
      for (const auto& r : results) arr.push_back({{"bvid", r.bvid}, {"title", r.title}, {"summary", r.summary}});
      res.set_content(json_str({{"ok", true}, {"results", arr}}), "application/json");
    } catch (...) {
      res.set_content("{\"ok\":false,\"message\":\"bad json\"}", "application/json");
    }
  });

  auto export_route = [this](const httplib::Request& req, httplib::Response& res, const std::string& fmt) {
    if (!require_auth(req, res)) return;
    try {
      auto j = nlohmann::json::parse(req.body);
      std::string bvid = j.value("bvid", j.value("file", ""));
      std::string mode = j.value("mode", "");
      std::string err, path;
      if (fmt == "mm") {
        std::string mm_dir = app_.paths.user_data_dir + "/Mindmaps";
        std::error_code ec;
        fs::create_directories(mm_dir, ec);
        if (mode == "library") {
          std::string html = "<!doctype html><html><head><meta charset=\"utf-8\"><title>Knowledge Mindmap</title></head><body><h1>Knowledge Mindmap</h1><ul>";
          KnowledgeBase kb(app_.paths.knowledge_metadata_file, app_.paths.knowledge_base_dir);
          kb.load();
          const auto& idx = kb.metadata().value("file_index", nlohmann::json::object());
          for (auto& [cat, entries] : idx.items()) {
            html += "<li><strong>" + cat + "</strong><ul>";
            for (const auto& e : entries) html += "<li>" + e.value("title", "") + "</li>";
            html += "</ul></li>";
          }
          html += "</ul></body></html>";
          path = mm_dir + "/library_" + ts_suffix() + ".mindmap.html";
          write_file(path, html);
        } else {
          std::string content;
          if (!bvid.empty()) {
            std::error_code ec2;
            std::string kb_path = app_.paths.knowledge_base_dir;
            for (const auto& e : fs::recursive_directory_iterator(kb_path, ec2)) {
              if (ec2) break;
              if (e.is_regular_file() && e.path().extension() == ".md" && e.path().stem().string().find(bvid) != std::string::npos) {
                content = read_file(e.path().string());
                break;
              }
            }
          }
          std::string safe = bvid.empty() ? "note" : bvid;
          path = mm_dir + "/" + safe + "_" + ts_suffix() + ".mindmap.html";
          write_file(path, "<!doctype html><html><head><meta charset=\"utf-8\"><title>" + safe + "</title></head><body><pre>" + content + "</pre></body></html>");
        }
      } else if (j.contains("html")) {
        std::string html = j.value("html", "");
        std::string title = j.value("title", "note");
        std::string dir = app_.paths.data_dir + "/DocumentExports";
        std::error_code ec;
        fs::create_directories(dir, ec);
        if (fmt == "txt") {
          path = dir + "/" + title + "_" + ts_suffix() + ".txt";
          write_file(path, html);
        } else {
          path = dir + "/" + title + "_" + ts_suffix() + ".html";
          write_file(path, html);
        }
      } else {
        path = export_note(app_, bvid, fmt, err);
      }
      if (path.empty()) {
        res.set_content(json_str({{"ok", false}, {"message", err.empty() ? "export failed" : err}}), "application/json");
        return;
      }
      res.set_content(json_str({{"ok", true}, {"path", path}}), "application/json");
    } catch (...) {
      res.set_content("{\"ok\":false,\"message\":\"bad json\"}", "application/json");
    }
  };
  svr.Post("/api/action/export-txt", [export_route](const httplib::Request& r, httplib::Response& s) { export_route(r, s, "txt"); });
  svr.Post("/api/action/export-docx", [export_route](const httplib::Request& r, httplib::Response& s) { export_route(r, s, "docx"); });
  svr.Post("/api/action/export-pdf", [export_route](const httplib::Request& r, httplib::Response& s) { export_route(r, s, "pdf"); });
  svr.Post("/api/action/mindmap", [export_route](const httplib::Request& r, httplib::Response& s) { export_route(r, s, "mm"); });

  svr.Get("/api/export", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::vector<std::string> files;
    try {
      for (const auto& e : fs::directory_iterator(app_.paths.data_dir + "/exports")) {
        files.push_back(e.path().filename().string());
      }
    } catch (...) {
    }
    res.set_content(json_str({{"files", files}}), "application/json");
  });

  svr.Get("/api/charts", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    res.set_content("{\"comments\":[],\"moods\":[],\"actions\":[],\"videos\":[]}", "application/json");
  });

  register_extra_routes(svr);
  svr.Get("/api/action/export-txt", [](const httplib::Request&, httplib::Response& res) {
    res.status = 405;
    res.set_content("{\"ok\":false,\"message\":\"use POST\"}", "application/json");
  });
  svr.Get("/api/action/export-docx", [](const httplib::Request&, httplib::Response& res) {
    res.status = 405;
    res.set_content("{\"ok\":false,\"message\":\"use POST\"}", "application/json");
  });
  svr.Get("/api/action/export-pdf", [](const httplib::Request&, httplib::Response& res) {
    res.status = 405;
    res.set_content("{\"ok\":false,\"message\":\"use POST\"}", "application/json");
  });
  svr.Get("/api/action/mindmap", [](const httplib::Request&, httplib::Response& res) {
    res.status = 405;
    res.set_content("{\"ok\":false,\"message\":\"use POST\"}", "application/json");
  });

  auto stub = [](const httplib::Request&, httplib::Response& res) {
    res.status = 501;
    res.set_content("{\"ok\":false,\"message\":\"C++ backend not implemented yet\"}", "application/json");
  };
  svr.Get(R"(/api/(.*))", stub);
  svr.Post(R"(/api/(.*))", stub);
}

bool WebServer::serve(int port) {
  httplib::Server svr;
  register_routes(svr);
  svr.set_exception_handler([this](const httplib::Request& req, httplib::Response& res,
                                   std::exception_ptr ep) {
    std::string msg = "unknown";
    try {
      if (ep) std::rethrow_exception(ep);
    } catch (const std::exception& e) {
      msg = e.what();
    } catch (...) {
    }
    append_bot_log("http 500 " + req.method + " " + req.path + " err=" + msg);
    res.status = 500;
    res.set_content("{\"ok\":false,\"message\":\"internal error\"}", "application/json");
  });
  reminder_running_.store(true);
  reminder_thread_ = std::thread([this] { reminder_loop(); });
  proactive_running_.store(true);
  proactive_thread_ = std::thread([this] { proactive_loop(); });
  std::printf("[WEB] C++ backend listening on http://0.0.0.0:%d\n", port);
  std::fflush(stdout);
  return svr.listen("0.0.0.0", port);
}

}  // namespace bili
