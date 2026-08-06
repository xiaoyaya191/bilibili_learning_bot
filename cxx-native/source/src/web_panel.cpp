#include "web.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <cctype>
#include <set>
#include <filesystem>
#include "fscompat.h"
#include <fstream>
#include <map>
#include <regex>
#include <sstream>
#include <thread>

#include "analysis.h"
#include "agent.h"
#include "api.h"
#include "asr.h"
#include "auth_refresh.h"
#include "cookies.h"
#include "export.h"
#include "factory_reset.h"
#include "frames.h"
#include "httplib.h"
#include "kb.h"
#include "logbuf.h"
#include "net.h"
#include "platform.h"
#include "proactive.h"
#include "psycho.h"
#include "qr.h"
#include "rag.h"
#include "websearch.h"
#include "sha256.h"
#include "reminders.h"
#include "urlcodec.h"
#include "verify.h"
#include "platform_adapter.h"
#include "video_asr.h"
#include "zipwriter.h"

namespace fs = std::filesystem;

namespace bili {
namespace {

using json = nlohmann::json;

std::string read_file(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) return "";
  std::ostringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

bool write_file(const std::string& path, const std::string& content) {
  std::error_code ec;
  fs::create_directories(fs::path(path).parent_path(), ec);
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) return false;
  out << content;
  return out.good();
}

json read_json(const std::string& path, const json& fallback = json::object()) {
  std::string raw = read_file(path);
  if (raw.empty()) return fallback;
  if (raw.size() >= 3 && (unsigned char)raw[0] == 0xEF && (unsigned char)raw[1] == 0xBB &&
      (unsigned char)raw[2] == 0xBF) {
    raw = raw.substr(3);
  }
  try {
    return json::parse(raw);
  } catch (...) {
    return fallback;
  }
}

bool write_json(const std::string& path, const json& value) {
  return write_file(path, value.dump(2));
}

std::string json_str(const json& j) { return j.dump(); }

std::string sanitize_utf8(const std::string& s) {
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
      if (c >= 0x20 || c == '\t' || c == '\n' || c == '\r') out += (char)c;
      else hex(c);
      i++;
      continue;
    }
    int len = 0;
    if ((c & 0xE0) == 0xC0) len = 2;
    else if ((c & 0xF0) == 0xE0) len = 3;
    else if ((c & 0xF8) == 0xF0) len = 4;
    if (len == 0 || i + len > s.size()) { hex(c); i++; continue; }
    bool ok = true;
    for (int k = 1; k < len; k++) {
      if (((unsigned char)s[i + k] & 0xC0) != 0x80) { ok = false; break; }
    }
    if (!ok) { hex(c); i++; continue; }
    out.append(s, i, len);
    i += len;
  }
  return out;
}

json sanitize_json(const json& j) {
  if (j.is_string()) return sanitize_utf8(j.get_ref<const std::string&>());
  if (j.is_object()) {
    json o = json::object();
    for (auto it = j.begin(); it != j.end(); ++it) o[it.key()] = sanitize_json(it.value());
    return o;
  }
  if (j.is_array()) {
    json a = json::array();
    for (const auto& v : j) a.push_back(sanitize_json(v));
    return a;
  }
  return j;
}

void send_json(httplib::Response& res, const json& j, int status = 200) {
  res.status = status;
  res.set_content(sanitize_json(j).dump(), "application/json");
}

std::string loggable_preview(const std::string& s, size_t max) {
  std::string out;
  for (unsigned char c : s.substr(0, max)) {
    if (c == '\n') {
      out += "\\n";
    } else if (c == '\r') {
      out += "\\r";
    } else if (c == '\t') {
      out += "\\t";
    } else if (c >= 32 && c < 127) {
      out += static_cast<char>(c);
    } else {
      char buf[8];
      std::snprintf(buf, sizeof(buf), "\\x%02x", c);
      out += buf;
    }
  }
  return out;
}

json parse_body(const httplib::Request& req) {
  try {
    return json::parse(req.body);
  } catch (...) {
    return json::object();
  }
}

std::string qparam(const httplib::Request& req, const std::string& key,
                   const std::string& fallback = "") {
  std::string v = req.get_param_value(key);
  return v.empty() ? fallback : v;
}

std::string trim(std::string s) {
  size_t a = s.find_first_not_of(" \t\r\n");
  if (a == std::string::npos) return "";
  size_t b = s.find_last_not_of(" \t\r\n");
  return s.substr(a, b - a + 1);
}

std::string lower(std::string s) {
  std::transform(s.begin(), s.end(), s.begin(),
                 [](unsigned char c) { return std::tolower(c); });
  return s;
}

bool starts_with(const std::string& s, const std::string& p) { return s.rfind(p, 0) == 0; }

std::string now_iso() {
  std::time_t t = std::time(nullptr);
  std::tm tm{};
  localtime_r(&t, &tm);
  char buf[40];
  std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &tm);
  return buf;
}

std::string now_iso_with_tz() {
  std::time_t t = std::time(nullptr);
  std::tm tm{};
  localtime_r(&t, &tm);
  char buf[40];
  std::strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &tm);
  return buf;
}

long long now_epoch() {
  return std::chrono::duration_cast<std::chrono::seconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

std::string timestamp_suffix() {
  std::time_t t = std::time(nullptr);
  std::tm tm{};
  localtime_r(&t, &tm);
  char buf[40];
  std::strftime(buf, sizeof(buf), "%Y%m%d_%H%M%S", &tm);
  return buf;
}

std::string base64_encode(const std::string& in) {
  static const char* tbl =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  std::string out;
  out.reserve(((in.size() + 2) / 3) * 4);
  for (size_t i = 0; i < in.size(); i += 3) {
    unsigned a = (unsigned char)in[i];
    unsigned b = i + 1 < in.size() ? (unsigned char)in[i + 1] : 0;
    unsigned c = i + 2 < in.size() ? (unsigned char)in[i + 2] : 0;
    out.push_back(tbl[a >> 2]);
    out.push_back(tbl[((a & 3) << 4) | (b >> 4)]);
    out.push_back(i + 1 < in.size() ? tbl[((b & 15) << 2) | (c >> 6)] : '=');
    out.push_back(i + 2 < in.size() ? tbl[c & 63] : '=');
  }
  return out;
}

std::vector<std::string> extract_frames(const std::string& ffmpeg, const std::string& video_url,
                                          const std::string& out_dir, int count) {
  std::vector<std::string> frames;
  if (ffmpeg.empty() || video_url.empty()) return frames;
  std::error_code ec;
  fs::create_directories(out_dir, ec);
  std::string pattern = out_dir + "/f_%02d.jpg";
  std::string cmd = "\"" + ffmpeg + "\" -y -i \"" + video_url + "\" -vf fps=1/8 -frames:v " +
                    std::to_string(count) + " \"" + pattern + "\" >nul 2>nul";
#ifdef _WIN32
  cmd = "\"" + ffmpeg + "\" -y -i \"" + video_url + "\" -vf fps=1/8 -frames:v " +
        std::to_string(count) + " \"" + pattern + "\" >nul 2>nul";
#else
  cmd = "\"" + ffmpeg + "\" -y -i \"" + video_url + "\" -vf fps=1/8 -frames:v " +
        std::to_string(count) + " \"" + pattern + "\" >/dev/null 2>&1";
#endif
  int rc = std::system(cmd.c_str());
  if (rc != 0) return frames;
  std::vector<fs::path> files;
  for (const auto& e : fs::directory_iterator(out_dir, ec)) {
    if (ec || !e.is_regular_file()) continue;
    if (e.path().extension() == ".jpg") files.push_back(e.path());
  }
  std::sort(files.begin(), files.end());
  for (const auto& f : files) frames.push_back(f.string());
  return frames;
}

json find_qr_callback(const json& root) {
  std::vector<const json*> queue = {&root};
  json fallback;
  while (!queue.empty()) {
    const json* cur = queue.back();
    queue.pop_back();
    if (!cur->is_object()) continue;
    for (auto& [k, v] : cur->items()) {
      if (k == "url" && v.is_string()) {
        if (v.get<std::string>().find("SESSDATA=") != std::string::npos) return *cur;
        if (fallback.empty()) fallback = *cur;
      } else if (v.is_object()) {
        queue.push_back(&v);
      } else if (v.is_array()) {
        for (const auto& e : v) {
          if (e.is_object()) queue.push_back(&e);
        }
      }
    }
  }
  return fallback;
}

std::string quote_sessdata(const std::string& raw) {
  std::string out;
  for (unsigned char c : raw) {
    if (std::isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~' || c == '/') {
      out += (char)c;
    } else if (c == ' ') {
      out += "%20";
    } else {
      char buf[4];
      std::snprintf(buf, sizeof(buf), "%%%02X", c);
      out += buf;
    }
  }
  return out;
}

std::string base64_decode(const std::string& in) {
  static int vals[256];
  static bool init = false;
  if (!init) {
    for (int i = 0; i < 256; i++) vals[i] = -1;
    const char* tbl =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    for (int i = 0; i < 64; i++) vals[(unsigned char)tbl[i]] = i;
    init = true;
  }
  std::string out;
  int buf = 0, bits = 0;
  for (unsigned char ch : in) {
    if (ch == '=') break;
    int v = vals[ch];
    if (v < 0) continue;
    buf = (buf << 6) | v;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out.push_back((char)((buf >> bits) & 0xFF));
    }
  }
  return out;
}

std::string safe_bvid(const std::string& raw) {
  std::smatch m;
  if (std::regex_search(raw, m, std::regex("BV[0-9A-Za-z]{10}"))) {
    return m[0];
  }
  return "";
}

std::string duration_label(long long seconds) {
  if (seconds <= 0) return "--:--";
  long long minutes = seconds / 60;
  long long hours = minutes / 60;
  minutes %= 60;
  seconds %= 60;
  char buf[32];
  if (hours) {
    std::snprintf(buf, sizeof(buf), "%lld:%02lld:%02lld", (long long)hours, (long long)minutes,
                  (long long)seconds);
  } else {
    std::snprintf(buf, sizeof(buf), "%lld:%02lld", (long long)minutes, (long long)seconds);
  }
  return buf;
}

std::string size_kb(long long bytes) {
  char buf[32];
  std::snprintf(buf, sizeof(buf), "%.1f", bytes / 1024.0);
  return buf;
}

json watch_history_cards(const App& app) {
  json source = read_json(app.paths.data_dir + "/history_videos.json", json::object());
  json metadata = read_json(app.paths.data_dir + "/watch_history_metadata.json", json::object());
  if (!metadata.is_object()) metadata = json::object();
  const json& entries = source.value("videos", json::array());
  std::map<std::string, json> grouped;
  if (entries.is_array()) {
    for (const auto& raw : entries) {
      if (!raw.is_object()) continue;
      std::string bvid = safe_bvid(raw.value("bvid", ""));
      if (bvid.empty()) continue;
      json& item = grouped[bvid];
      if (item.empty()) {
        item = {{"bvid", bvid}, {"title", ""}, {"up", ""}, {"aid", 0}, {"pic", ""},
                {"duration", 0}, {"category", ""}, {"interest_reason", ""},
                {"source", "history"}, {"result", ""}, {"actions", json::array()},
                {"score", 0.0}, {"time", ""}, {"revisit_count", 0}};
      }
      std::string action = lower(raw.value("action", "view"));
      if (action.empty()) action = "view";
      bool seen = false;
      for (const auto& a : item["actions"]) {
        if (a.get<std::string>() == action) seen = true;
      }
      if (!seen) item["actions"].push_back(action);
      for (const char* key : {"title", "up", "pic", "category", "interest_reason", "source", "result"}) {
        if (raw.contains(key) && raw[key].is_string() && !raw[key].get<std::string>().empty()) {
          item[key] = raw[key];
        }
      }
      if (raw.contains("aid")) item["aid"] = raw["aid"];
      if (raw.contains("duration") && raw["duration"].is_number()) item["duration"] = raw["duration"];
      if (raw.contains("score") && raw["score"].is_number()) {
        double s = raw["score"].get<double>();
        if (s > item["score"].get<double>()) item["score"] = s;
      }
      if (raw.contains("time") && raw["time"].is_string()) {
        if (item["time"].get<std::string>() < raw["time"].get<std::string>()) {
          item["time"] = raw["time"];
        }
      }
    }
  }

  json cards = json::array();
  static const std::map<std::string, std::string> labels = {
      {"view", "watched"}, {"like", "liked"}, {"fav", "favorited"}, {"coin", "coined"}};
  for (auto& [bvid, item] : grouped) {
    const json& detail = metadata.value(bvid, json::object());
    for (const char* key : {"title", "up", "pic", "category"}) {
      if ((!item.contains(key) || !item[key].is_string() || item[key].get<std::string>().empty()) &&
          detail.contains(key) && detail[key].is_string()) {
        item[key] = detail[key];
      }
    }
    long long dur = item.value("duration", 0);
    if (dur <= 0 && detail.contains("duration") && detail["duration"].is_number()) {
      dur = detail["duration"].get<long long>();
    }
    std::string pic = item.value("pic", "");
    if (starts_with(pic, "//")) pic = "https:" + pic;
    json actions = json::array();
    for (const auto& a : item["actions"]) {
      std::string key = a.get<std::string>();
      auto it = labels.find(key);
      actions.push_back(it == labels.end() ? key : it->second);
    }
    json card = {{"bvid", bvid},
                 {"title", item.value("title", bvid)},
                 {"up", item.value("up", "unknown UP")},
                 {"aid", item.value("aid", 0)},
                 {"cover", pic},
                 {"duration", duration_label(dur)},
                 {"category", item.value("category", "")},
                 {"watched_at", item.value("time", "--")},
                 {"score", item.value("score", 0.0)},
                 {"interest_reason", item.value("interest_reason", "")},
                 {"source", item.value("source", "history")},
                 {"result", item.value("result", "interacted")},
                 {"actions", actions},
                 {"archived", false},
                 {"revisit_count", item.value("revisit_count", 0)},
                 {"url", "https://www.bilibili.com/video/" + bvid},
                 {"view_count", detail.contains("view_count") ? detail["view_count"] : json()},
                 {"like_count", detail.contains("like_count") ? detail["like_count"] : json()},
                 {"coin_count", detail.contains("coin_count") ? detail["coin_count"] : json()},
                 {"favorite_count", detail.contains("favorite_count") ? detail["favorite_count"] : json()},
                 {"published_at", detail.value("published_at", 0)}};
    cards.push_back(card);
  }
  std::sort(cards.begin(), cards.end(), [](const json& a, const json& b) {
    return a.value("watched_at", "") > b.value("watched_at", "");
  });
  return cards;
}

std::string ai_chat_once(const App& app, const std::string& system,
                         const std::string& user) {
  NetClient net(app);
  AiClient ai(app, net);
  return ai.chat({{"system", system}, {"user", user}});
}

void redact_config(json& cfg) {
  if (cfg.contains("api") && cfg["api"].is_object()) {
    for (const char* key : {"unified_api_key", "vision_api_key"}) {
      if (cfg["api"].contains(key) && cfg["api"][key].is_string()) {
        std::string v = cfg["api"][key].get<std::string>();
        if (v.size() > 8) cfg["api"][key] = v.substr(0, 4) + "****" + v.substr(v.size() - 4);
      }
    }
  }
}

}  // namespace

void WebServer::append_bot_log(const std::string& line) {
  std::string full = "[" + now_iso_with_tz() + "] " + line;
  {
    std::lock_guard<std::mutex> lock(bot_log_mu_);
    bot_log_.push_back(full);
    if (bot_log_.size() > 1000) bot_log_.erase(bot_log_.begin(), bot_log_.begin() + 600);
  }
  LogBuffer::instance().append(full);
  std::string log_path = app_.paths.log_dir + "/web_bot_runtime.log";
  std::ofstream out(log_path, std::ios::binary | std::ios::app);
  if (out) out << full << "\n";
}

void WebServer::bot_loop() {
  append_bot_log("bot worker started");
  Monitor monitor(app_);
  while (bot_running_.load()) {
    try {
      monitor.check_once();
    } catch (...) {
      append_bot_log("bot worker error");
    }
    for (int i = 0; i < 25 && bot_running_.load(); i++) {
      std::this_thread::sleep_for(std::chrono::milliseconds(400));
    }
  }
  append_bot_log("bot worker stopped");
}

void WebServer::standby_loop() {
  append_bot_log("standby worker started");
  Monitor monitor(app_);
  long long last_run = 0;
  while (standby_running_.load()) {
    long long now = now_epoch();
    if (now - last_run >= 60) {
      last_run = now;
      try {
        monitor.check_once();
      } catch (...) {
        append_bot_log("standby worker error");
      }
      json st = read_json(app_.paths.data_dir + "/standby_stats.json", json::object());
      st["running"] = true;
      st["last_run_at"] = now_iso();
      write_json(app_.paths.data_dir + "/standby_stats.json", st);
    }
    for (int i = 0; i < 30 && standby_running_.load(); i++) {
      std::this_thread::sleep_for(std::chrono::seconds(1));
    }
  }
  append_bot_log("standby worker stopped");
}

void WebServer::qr_worker(const std::string& session_id) {
  {
    std::lock_guard<std::mutex> lock(state_mu_);
    if (qr_state_.value("session_id", "") != session_id) return;
    qr_state_["active"] = true;
    qr_state_["status"] = "generating";
    qr_state_["message"] = "Generating QR code...";
    qr_state_["img_b64"] = "";
  }
  NetClient net(app_);
  ensure_buvid4(app_, net);
  NetResponse gen = net.get(
      "https://passport.bilibili.com/x/passport-login/web/qrcode/generate?source=main-fe-header");
  json gj;
  try {
    gj = json::parse(gen.body);
  } catch (...) {
    gj = json::object();
  }
  if (gj.value("code", -1) != 0 || !gj.contains("data")) {
    append_bot_log("QR generate failed: http=" + std::to_string(gen.http_code) +
                   " size=" + std::to_string(gen.body.size()) +
                   " encoding=" + gen.content_encoding +
                   " err=" + gen.curl_error);
    append_bot_log("QR generate head: " + loggable_preview(gen.body, 240));
    std::lock_guard<std::mutex> lock(state_mu_);
    if (qr_state_.value("session_id", "") != session_id) return;
    qr_state_["status"] = "error";
    qr_state_["message"] = "Failed to get QR code (http=" + std::to_string(gen.http_code) +
                            ", size=" + std::to_string(gen.body.size()) +
                            ", err=" + gen.curl_error + ")";
    qr_state_["active"] = false;
    return;
  }
  const json& gdata = gj["data"];
  std::string qr_url = gdata.value("url", "");
  std::string qr_key = gdata.value("qrcode_key", "");
  if (qr_url.empty() || qr_key.empty()) {
    std::lock_guard<std::mutex> lock(state_mu_);
    if (qr_state_.value("session_id", "") != session_id) return;
    qr_state_["status"] = "error";
    qr_state_["message"] = "Empty QR payload";
    qr_state_["active"] = false;
    return;
  }
  std::string png_path = app_.paths.data_dir + "/login_qrcode.png";
  if (render_qr_png(qr_url, png_path, 4)) {
    std::string raw = read_file(png_path);
    if (!raw.empty()) {
      std::lock_guard<std::mutex> lock(state_mu_);
      if (qr_state_.value("session_id", "") != session_id) return;
      qr_state_["img_b64"] = base64_encode(raw);
      qr_state_["url"] = qr_url;
      qr_state_["status"] = "waiting_scan";
      qr_state_["message"] = "Scan with Bilibili app";
    }
  } else {
    std::lock_guard<std::mutex> lock(state_mu_);
    if (qr_state_.value("session_id", "") != session_id) return;
    qr_state_["status"] = "error";
    qr_state_["message"] = "QR PNG render failed";
    qr_state_["active"] = false;
    return;
  }

  const std::string poll_url = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll";
  auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(180);
  bool scanned = false;
  while (std::chrono::steady_clock::now() < deadline) {
    {
      std::lock_guard<std::mutex> lock(state_mu_);
      if (qr_state_.value("session_id", "") != session_id) return;
    }
    NetResponse resp = net.get(poll_url, {{"qrcode_key", qr_key}, {"source", "main-fe-header"}});
    json pj;
    try {
      pj = json::parse(resp.body);
    } catch (...) {
      std::this_thread::sleep_for(std::chrono::seconds(2));
      continue;
    }
    if (pj.value("code", -1) != 0 || !pj.contains("data")) {
      std::this_thread::sleep_for(std::chrono::seconds(2));
      continue;
    }
    const json& data = pj["data"];
    long status = data.value("code", 86101);
    if (status == 0) {
      json cb = find_qr_callback(data);
      if (cb.empty()) cb = find_qr_callback(pj);
      std::string redirect = cb.value("url", data.value("url", ""));
      std::string refresh_token = cb.value("refresh_token", data.value("refresh_token", ""));
      std::map<std::string, std::string> url_cookies;
      size_t q = redirect.find('?');
      if (q != std::string::npos) {
        std::string query = redirect.substr(q + 1);
        size_t pos = 0;
        while (pos <= query.size()) {
          size_t amp = query.find('&', pos);
          std::string pair = query.substr(pos, amp == std::string::npos ? std::string::npos : amp - pos);
          size_t eq = pair.find('=');
          if (eq != std::string::npos) {
            url_cookies[trim(percent_decode(pair.substr(0, eq)))] = trim(percent_decode(pair.substr(eq + 1)));
          }
          if (amp == std::string::npos) break;
          pos = amp + 1;
        }
      }
      std::map<std::string, std::string> header_cookies;
      auto set_cookie_if_nonempty = [](std::map<std::string, std::string>& m,
                                       const std::string& k, const std::string& v) {
        if (v.empty()) return;
        if (m.count(k) && !m[k].empty()) return;
        m[k] = v;
      };
      for (const std::string& line : resp.set_cookies) {
        std::string lower_line = lower(line);
        size_t colon = lower_line.find("set-cookie:");
        if (colon == std::string::npos) continue;
        std::string rest = line.substr(colon + 11);
        size_t semi = rest.find(';');
        std::string kv = rest.substr(0, semi);
        size_t eq = kv.find('=');
        if (eq != std::string::npos) {
          std::string name = trim(kv.substr(0, eq));
          std::string value = trim(kv.substr(eq + 1));
          set_cookie_if_nonempty(header_cookies, name, value);
        }
      }
      std::string sessdata = url_cookies.count("SESSDATA") ? url_cookies["SESSDATA"] : "";
      std::string jct = url_cookies.count("bili_jct") ? url_cookies["bili_jct"] : "";
      std::string uid = url_cookies.count("DedeUserID") ? url_cookies["DedeUserID"] : "";
      bool sess_from_header = false;
      if (sessdata.empty()) { sessdata = header_cookies["SESSDATA"]; sess_from_header = true; }
      if (jct.empty()) jct = header_cookies["bili_jct"];
      if (uid.empty()) uid = header_cookies["DedeUserID"];
      if (sessdata.empty() || jct.empty() || uid.empty()) {
        NetResponse cb = net.raw_get(redirect, {{"Referer", "https://www.bilibili.com/"}});
        for (const std::string& line : cb.set_cookies) {
          std::string lower_line = lower(line);
          size_t colon = lower_line.find("set-cookie:");
          if (colon == std::string::npos) continue;
          std::string rest = line.substr(colon + 11);
          size_t semi = rest.find(';');
          std::string kv = rest.substr(0, semi);
          size_t eq = kv.find('=');
          if (eq != std::string::npos) {
            std::string name = trim(kv.substr(0, eq));
            std::string value = trim(kv.substr(eq + 1));
            set_cookie_if_nonempty(header_cookies, name, value);
          }
        }
        if (sessdata.empty()) { sessdata = header_cookies["SESSDATA"]; sess_from_header = true; }
        if (jct.empty()) jct = header_cookies["bili_jct"];
        if (uid.empty()) uid = header_cookies["DedeUserID"];
      }
      if (sessdata.empty() || jct.empty() || uid.empty()) {
        std::string qkeys, hkeys;
        for (const auto& [k, v] : url_cookies) qkeys += k + "(" + std::to_string(v.size()) + ") ";
        for (const auto& [k, v] : header_cookies) hkeys += k + "(" + std::to_string(v.size()) + ") ";
        append_bot_log("QR login incomplete: query=" + qkeys + " headers=" + hkeys +
                       " redirect_len=" + std::to_string(redirect.size()));
        std::lock_guard<std::mutex> lock(state_mu_);
        if (qr_state_.value("session_id", "") != session_id) return;
        qr_state_["status"] = "error";
        qr_state_["message"] = "Login cookies incomplete (sess=" + std::to_string(sessdata.size()) +
                               " jct=" + std::to_string(jct.size()) + " uid=" + std::to_string(uid.size()) +
                               " redirect=" + std::to_string(redirect.size()) + " headers=" + std::to_string(header_cookies.size()) + ")";
        qr_state_["active"] = false;
        return;
      }
      app_.cookies["SESSDATA"] = sess_from_header ? sessdata : quote_sessdata(sessdata);
      app_.cookies["bili_jct"] = jct;
      app_.cookies["DedeUserID"] = uid;
      if (url_cookies.count("DedeUserID__ckMd5")) {
        app_.cookies["DedeUserID__ckMd5"] = url_cookies["DedeUserID__ckMd5"];
      }
      if (!header_cookies["buvid3"].empty()) app_.cookies["buvid3"] = header_cookies["buvid3"];
      if (url_cookies.count("buvid3") && !url_cookies["buvid3"].empty()) {
        app_.cookies["buvid3"] = url_cookies["buvid3"];
      }
      if (refresh_token.empty()) refresh_token = url_cookies.count("refresh_token") ? url_cookies["refresh_token"] : "";
      if (!refresh_token.empty()) app_.cookies["ac_time_value"] = refresh_token;
      ensure_buvid3(app_);
      try {
        app_.uid = std::stoll(uid);
      } catch (...) {
      }
      save_cookies_file(app_);
      std::lock_guard<std::mutex> lock(state_mu_);
      if (qr_state_.value("session_id", "") != session_id) return;
      qr_state_["status"] = "success";
      qr_state_["message"] = "Login success";
      qr_state_["uid"] = uid;
      qr_state_["active"] = false;
      return;
    }
    if (status == 86090) {
      if (!scanned) {
        scanned = true;
        std::lock_guard<std::mutex> lock(state_mu_);
        if (qr_state_.value("session_id", "") != session_id) return;
        qr_state_["status"] = "scanned";
        qr_state_["message"] = "Scanned, confirm on phone";
      }
    } else if (status == 86038) {
      std::lock_guard<std::mutex> lock(state_mu_);
      if (qr_state_.value("session_id", "") != session_id) return;
      qr_state_["status"] = "timeout";
      qr_state_["message"] = "QR expired, generate again";
      qr_state_["active"] = false;
      return;
    }
    std::this_thread::sleep_for(std::chrono::seconds(2));
  }
  std::lock_guard<std::mutex> lock(state_mu_);
  if (qr_state_.value("session_id", "") != session_id) return;
  qr_state_["status"] = "timeout";
  qr_state_["message"] = "QR login timed out";
  qr_state_["active"] = false;
}

void WebServer::reminder_loop() {
  while (reminder_running_.load()) {
    try {
      auto due = take_due_reminders(app_);
      for (const auto& r : due) {
        append_bot_log("reminder due: " + r.value("content", ""));
      }
    } catch (...) {
      append_bot_log("reminder worker error");
    }
    for (int i = 0; i < 30 && reminder_running_.load(); i++) {
      std::this_thread::sleep_for(std::chrono::seconds(1));
    }
  }
}

void WebServer::proactive_loop() {
  while (proactive_running_.load()) {
    try {
      run_proactive_cycle(app_, monitor_);
      run_evolution_cycle(app_);
    } catch (...) {
      append_bot_log("proactive worker error");
    }
    long long minutes = get_int(app_, "proactive", "interval_minutes", 30);
    for (long long i = 0; i < minutes * 60 && proactive_running_.load(); i++) {
      std::this_thread::sleep_for(std::chrono::seconds(1));
    }
  }
}

void WebServer::pm_loop() {
  append_bot_log("private message worker started");
  while (pm_running_.load()) {
    try {
      check_private_messages();
    } catch (...) {
      append_bot_log("private message worker error");
    }
    for (int i = 0; i < 30 && pm_running_.load(); i++) {
      std::this_thread::sleep_for(std::chrono::seconds(1));
    }
  }
  append_bot_log("private message worker stopped");
}

void WebServer::check_private_messages() {
  if (!get_bool(app_, "private_message", "enabled", false)) return;
  if (!get_bool(app_, "private_message", "auto_reply", true)) return;
  NetClient net(app_);
  ensure_buvid4(app_, net);
  NetResponse resp = net.get(
      "https://api.vc.bilibili.com/session_svr/v1/session_svr/get_sessions",
      {{"session_type", "1"}, {"group_fold", "1"}, {"unfollow_fold", "0"},
       {"sort_rule", "2"}, {"build", "0"}, {"mobi_app", "web"}});
  json j;
  try {
    j = json::parse(resp.body);
  } catch (...) {
    return;
  }
  if (j.value("code", -1) != 0) return;
  const json& session_list = j.value("data", json::object()).value("session_list", json::array());
  if (!session_list.is_array()) return;
  std::string state_path = app_.paths.data_dir + "/private_sessions.json";
  json state = read_json(state_path, json::object());
  if (!state.contains("processed")) state["processed"] = json::object();
  if (!state.contains("sessions")) state["sessions"] = json::object();
  long long cooldown = get_int(app_, "behavior", "private_reply_cooldown_minutes", 30);
  for (const auto& sess : session_list) {
    if (!sess.is_object()) continue;
    long long talker = sess.value("talker_id", 0);
    long long unread = sess.value("unread_count", 0);
    if (talker <= 0 || unread <= 0) continue;
    const json& last_msg = sess.value("last_msg", json::object());
    std::string msg_id = last_msg.value("msg_seqno", last_msg.value("msg_key", last_msg.value("id", "")));
    if (msg_id.empty()) continue;
    if (state["processed"].contains(msg_id)) continue;
    json context = json::array();
    NetResponse detail = net.get(
        "https://api.vc.bilibili.com/session_svr/v1/session_svr/session_detail",
        {{"talker_id", std::to_string(talker)}, {"session_type", "1"}});
    try {
      auto dj = json::parse(detail.body);
      const auto& messages = dj.value("data", json::object()).value("messages", json::array());
      size_t start = messages.size() > 10 ? messages.size() - 10 : 0;
      for (size_t i = start; i < messages.size(); i++) {
        const auto& m = messages[i];
        std::string c;
        std::string img;
        try {
          json mc = json::parse(m.value("content", "{}"));
          c = trim(mc.value("content", ""));
          img = mc.value("url", mc.value("pic_url", ""));
        } catch (...) {
          c = trim(m.value("content", ""));
        }
        if (!img.empty()) {
          AiClient ai(app_, net);
          std::string desc = ai.chat_vision(
              {{"system", "你是私信图片描述助手。只用一句话描述图片中可确认的主体、文字和情绪。"},
               {"user", "描述这张图片"}}, img);
          if (!desc.empty()) c += "\n[图片] " + desc;
        }
        if (!c.empty()) {
          context.push_back({{"sender", m.value("sender_uid", m.value("sender", ""))},
                             {"content", c.substr(0, 800)}});
        }
      }
    } catch (...) {
    }
    std::string content;
    std::string image_url;
    try {
      json c = json::parse(last_msg.value("content", "{}"));
      content = trim(c.value("content", ""));
      image_url = c.value("url", c.value("pic_url", ""));
    } catch (...) {
      content = trim(last_msg.value("content", ""));
    }
    if (!image_url.empty()) {
      AiClient ai(app_, net);
      std::string desc = ai.chat_vision(
          {{"system", "你是私信图片描述助手。只用一句话描述图片中可确认的主体、文字和情绪。"},
           {"user", "描述这张图片"}}, image_url);
      if (!desc.empty()) content += "\n[图片] " + desc;
    }
    if (content.empty()) {
      state["processed"][msg_id] = now_iso();
      write_json(state_path, state);
      continue;
    }
    std::string user_key = "u" + std::to_string(talker);
    std::string last_reply = state.value("sessions", json::object()).value(user_key, json::object()).value("last_reply_at", "");
    if (!last_reply.empty()) {
      // Best-effort cooldown check using date prefix.
      if (now_iso().substr(0, 16) <= last_reply.substr(0, 16)) continue;
    }
    std::string context_text;
    for (const auto& m : context) {
      context_text += "[" + m.value("sender", "") + "] " +
                      m.value("content", "") + "\n";
    }
    std::string reply = ai_chat_once(
        app_, "You are a friendly Bilibili AI assistant replying to private messages. Keep it short and natural.",
        "会话上下文:\n" + context_text + "\n最新消息: " + content);
    if (reply.empty()) continue;
    std::string err = send_private_message(net, app_, talker, reply);
    state["processed"][msg_id] = now_iso();
    state["sessions"][user_key] = {{"talker_id", talker}, {"last_reply_at", now_iso()},
                                    {"last_message", content}, {"last_reply", reply},
                                    {"last_error", err}};
    write_json(state_path, state);
    append_bot_log(err.empty() ? "PM replied to " + std::to_string(talker) : "PM reply failed: " + err);
  }
}

void WebServer::register_extra_routes(httplib::Server& svr) {
  // ----- QR login -----
  svr.Post("/api/bili/qr/start", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    bool force = body.value("force", false);
    {
      std::lock_guard<std::mutex> lock(state_mu_);
      if (qr_state_.value("active", false) && !force) {
        std::string img = qr_state_.value("img_b64", "");
        if (!img.empty()) {
          send_json(res, {{"ok", true}, {"reused", true}, {"img", img},
                          {"message", "QR still active"}, {"status", qr_state_.value("status", "waiting_scan")}});
          return;
        }
        send_json(res, {{"ok", false}, {"message", "QR is generating, retry later"},
                        {"status", qr_state_.value("status", "generating")}}, 409);
        return;
      }
      std::string session_id = now_iso() + "-" + std::to_string(now_epoch());
      qr_session_ = session_id;
      qr_state_ = {{"active", true}, {"url", ""}, {"status", "generating"},
                   {"message", "Generating..."}, {"uid", ""}, {"img_b64", ""},
                   {"session_id", session_id}};
      if (qr_thread_.joinable()) qr_thread_.detach();
      qr_thread_ = std::thread([this, session_id] { qr_worker(session_id); });
    }
    for (int i = 0; i < 20; i++) {
      std::this_thread::sleep_for(std::chrono::milliseconds(500));
      std::lock_guard<std::mutex> lock(state_mu_);
      if (qr_state_.value("session_id", "") != qr_session_) break;
      if (!qr_state_.value("img_b64", "").empty() ||
          qr_state_.value("status", "") == "error" || qr_state_.value("status", "") == "timeout") {
        break;
      }
    }
    std::lock_guard<std::mutex> lock(state_mu_);
    std::string img = qr_state_.value("img_b64", "");
    std::string status = qr_state_.value("status", "");
    std::string message = qr_state_.value("message", "");
    if (img.empty()) {
      send_json(res, {{"ok", false}, {"img", ""}, {"message", message.empty() ? "QR generation timeout" : message},
                      {"status", status}}, 503);
      return;
    }
    send_json(res, {{"ok", true}, {"img", img}, {"message", message}, {"status", status}});
  });

  svr.Get("/api/bili/qr/image", [this](const httplib::Request&, httplib::Response& res) {
    std::string img;
    {
      std::lock_guard<std::mutex> lock(state_mu_);
      img = qr_state_.value("img_b64", "");
    }
    if (img.empty()) {
      send_json(res, {{"ok", false}, {"message", "No active QR"}}, 404);
      return;
    }
    std::string png = base64_decode(img);
    res.set_content(png, "image/png");
    res.set_header("Cache-Control", "no-store, max-age=0");
  });

  svr.Get("/api/bili/qr/status", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::lock_guard<std::mutex> lock(state_mu_);
    send_json(res, {{"status", qr_state_.value("status", "idle")},
                    {"message", qr_state_.value("message", "")},
                    {"uid", qr_state_.value("uid", "")},
                    {"active", qr_state_.value("active", false)},
                    {"has_image", !qr_state_.value("img_b64", "").empty()}});
  });

  svr.Post("/api/bili/logout", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    app_.cookies = json::object();
    app_.uid = 0;
    save_cookies_file(app_);
    std::error_code ec;
    fs::remove(app_.paths.cookie_file, ec);
    send_json(res, {{"ok", true}, {"message", "Logged out"}});
  });

  // ----- Reminders -----
  svr.Get("/api/reminders", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    send_json(res, {{"ok", true}, {"reminders", list_reminders(app_)}});
  });
  svr.Post("/api/reminders", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string text = trim(body.value("text", ""));
    std::string owner = body.value("owner_uid", std::to_string(app_.uid));
    if (text.empty()) { send_json(res, {{"ok", false}, {"message", "text required"}}, 400); return; }
    send_json(res, create_reminder(app_, text, owner));
  });
  svr.Post("/api/reminders/take", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    send_json(res, {{"ok", true}, {"due", take_due_reminders(app_)}});
  });

  // ----- Bot control -----
  svr.Post("/api/bot/start", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    if (!bot_running_.exchange(true)) {
      if (bot_thread_.joinable()) bot_thread_.detach();
      bot_thread_ = std::thread([this] { bot_loop(); });
    }
    append_bot_log("bot start requested");
    send_json(res, {{"ok", true}, {"message", "Bot started"}});
  });
  svr.Post("/api/bot/stop", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    bot_running_.store(false);
    if (bot_thread_.joinable()) bot_thread_.detach();
    append_bot_log("bot stop requested");
    send_json(res, {{"ok", true}, {"message", "Bot stopped"}});
  });
  svr.Post("/api/bot/restart", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    bot_running_.store(false);
    if (bot_thread_.joinable()) bot_thread_.detach();
    bot_running_.store(true);
    bot_thread_ = std::thread([this] { bot_loop(); });
    append_bot_log("bot restart requested");
    send_json(res, {{"ok", true}, {"message", "Bot restarted"}, {"elapsed", 0}});
  });
  svr.Get("/api/bot/output", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    size_t limit = 80;
    try {
      limit = (size_t)std::max(1LL, std::stoll(qparam(req, "limit", "80")));
    } catch (...) {
    }
    std::vector<std::string> lines;
    {
      std::lock_guard<std::mutex> lock(bot_log_mu_);
      size_t start = bot_log_.size() > limit ? bot_log_.size() - limit : 0;
      lines.assign(bot_log_.begin() + start, bot_log_.end());
    }
    std::ifstream in(app_.paths.log_dir + "/web_bot_runtime.log", std::ios::binary);
    if (in) {
      std::ostringstream ss;
      ss << in.rdbuf();
      std::string raw = ss.str();
      size_t pos = 0;
      std::vector<std::string> file_lines;
      while (pos <= raw.size()) {
        size_t nl = raw.find('\n', pos);
        std::string line = raw.substr(pos, nl == std::string::npos ? std::string::npos : nl - pos);
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (!line.empty()) file_lines.push_back(line);
        if (nl == std::string::npos) break;
        pos = nl + 1;
      }
      if (file_lines.size() > limit) file_lines.erase(file_lines.begin(), file_lines.end() - limit);
      lines = file_lines;
    }
    std::string output;
    for (const auto& l : lines) {
      if (!output.empty()) output += "\n";
      output += l;
    }
    send_json(res, {{"ok", true}, {"output", output}, {"running", bot_running_.load()}});
  });
  svr.Post("/api/bot/clear", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    {
      std::lock_guard<std::mutex> lock(bot_log_mu_);
      bot_log_.clear();
    }
    LogBuffer::instance().clear();
    std::ofstream out(app_.paths.log_dir + "/web_bot_runtime.log", std::ios::binary | std::ios::trunc);
    if (out) out << "";
    send_json(res, {{"ok", true}, {"message", "Log cleared"}});
  });
  svr.Get("/api/bot/browse-flow", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    const json& video = app_.config.value("video", json::object());
    send_json(res, {{"ok", true},
                    {"browse_mode", video.value("browse_mode", "candidate_review")},
                    {"candidate_pool_size", video.value("candidate_pool_size", 20)}});
  });
  svr.Post("/api/bot/browse-flow", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    app_.config["video"]["browse_mode"] = body.value("browse_mode", "candidate_review");
    app_.config["video"]["candidate_pool_size"] = body.value("candidate_pool_size", 20);
    save_config_file(app_);
    send_json(res, {{"ok", true}, {"message", "Browse flow saved"}});
  });
  svr.Get("/api/bot/session-limits", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    const json& limits = app_.config.value("session_limits", json::object());
    send_json(res, {{"ok", true},
                    {"max_duration_minutes", limits.value("max_duration_minutes", 0)},
                    {"max_videos", limits.value("max_videos", 0)},
                    {"max_learned_videos", limits.value("max_learned_videos", 0)},
                    {"completion_action", limits.value("completion_action", "monitor")}});
  });
  svr.Post("/api/bot/session-limits", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    json& limits = app_.config["session_limits"];
    if (body.contains("max_duration_minutes")) limits["max_duration_minutes"] = body["max_duration_minutes"];
    if (body.contains("max_videos")) limits["max_videos"] = body["max_videos"];
    if (body.contains("max_learned_videos")) limits["max_learned_videos"] = body["max_learned_videos"];
    if (body.contains("completion_action")) limits["completion_action"] = body["completion_action"];
    save_config_file(app_);
    send_json(res, {{"ok", true}, {"message", "Session limits saved"}});
  });

  // ----- Onboarding -----
  svr.Get("/api/onboarding", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string state = app_.config.value("web", json::object()).value("onboarding_state", "legacy");
    send_json(res, {{"ok", true}, {"state", state}, {"auto_show", state == "pending"}});
  });
  svr.Post("/api/onboarding", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string state = lower(trim(body.value("state", "")));
    if (state != "completed" && state != "skipped") {
      send_json(res, {{"ok", false}, {"message", "Invalid onboarding state"}}, 400);
      return;
    }
    app_.config["web"]["onboarding_state"] = state;
    save_config_file(app_);
    send_json(res, {{"ok", true}, {"state", state}, {"auto_show", false}});
  });

  // ----- AI presets / models -----
  svr.Get("/api/ai/presets", [](const httplib::Request&, httplib::Response& res) {
    json presets = {
        {"openai", {{"name", "OpenAI"}, {"base_url", "https://api.openai.com/v1"},
                    {"chat", "gpt-4o-mini"}, {"vision", "gpt-4o"}}},
        {"deepseek", {{"name", "DeepSeek"}, {"base_url", "https://api.deepseek.com/v1"},
                      {"chat", "deepseek-chat"}, {"vision", ""}}},
        {"qwen", {{"name", "Qwen"}, {"base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"},
                  {"chat", "qwen-plus"}, {"vision", "qwen-vl-plus"}}},
        {"zhipu", {{"name", "Zhipu"}, {"base_url", "https://open.bigmodel.cn/api/paas/v4"},
                   {"chat", "glm-4-flash"}, {"vision", "glm-4v-flash"}}},
        {"moonshot", {{"name", "Moonshot"}, {"base_url", "https://api.moonshot.cn/v1"},
                      {"chat", "moonshot-v1-8k"}, {"vision", ""}}},
        {"ollama", {{"name", "Ollama"}, {"base_url", "http://127.0.0.1:11434/v1"},
                    {"chat", "qwen2.5"}, {"vision", ""}}}};
    send_json(res, {{"presets", presets}, {"active_preset", ""}});
  });
  svr.Get("/api/models/list", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string api_key = qparam(req, "api_key", get_str(app_, "api", "unified_api_key"));
    std::string base = qparam(req, "base_url", get_str(app_, "api", "unified_base_url"));
    if (api_key.empty() || base.empty()) {
      send_json(res, {{"ok", false}, {"message", "API not configured"}});
      return;
    }
    NetClient net(app_);
    NetResponse resp = net.raw_get(base + "/models", {{"Authorization", "Bearer " + api_key}});
    json models = json::array();
    try {
      json j = json::parse(resp.body);
      for (const auto& m : j.value("data", json::array())) {
        models.push_back({{"id", m.value("id", "")}});
      }
    } catch (...) {
    }
    send_json(res, {{"ok", true}, {"models", models}});
  });

  // ----- Personas -----
  auto load_personas = [this]() -> json {
    json web = read_json(app_.paths.data_dir + "/web_personas.json", json::object());
    json items = web.value("items", json::object());
    if (items.is_object() && !items.empty()) {
      std::string active = web.value("active", "");
      if (active.empty()) {
        for (auto& [k, v] : items.items()) {
          active = k;
          break;
        }
      }
      return {{"active", active}, {"items", items}};
    }
    json runtime = read_json(app_.paths.data_dir + "/personas.json", json::object());
    json runtime_items = runtime.value("personas", json::object());
    if (runtime_items.is_object() && !runtime_items.empty()) {
      std::string active = runtime.value("active_persona", "");
      if (active.empty()) {
        for (auto& [k, v] : runtime_items.items()) {
          active = k;
          break;
        }
      }
      return {{"active", active}, {"items", runtime_items}};
    }
    std::string active = "default";
    json item = {{"name", "AI assistant"}, {"system_prompt", ""}, {"style", "friendly"},
                 {"owner_prompt", ""}, {"rules", json::array()}};
    return {{"active", active}, {"items", {{active, item}}}};
  };
  auto save_personas = [this](const json& data) {
    write_json(app_.paths.data_dir + "/web_personas.json", data);
    json runtime = {{"active_persona", data.value("active", "")},
                    {"personas", data.value("items", json::object())}};
    write_json(app_.paths.data_dir + "/personas.json", runtime);
  };

  svr.Get("/api/personas", [this, load_personas](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    send_json(res, load_personas());
  });
  svr.Post("/api/personas", [this, save_personas](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string name = trim(body.value("name", ""));
    if (name.empty()) {
      send_json(res, {{"ok", false}, {"message", "Name required"}}, 400);
      return;
    }
    json data = read_json(app_.paths.data_dir + "/web_personas.json", json::object());
    if (!data.contains("items") || !data["items"].is_object()) data["items"] = json::object();
    data["items"][name] = {{"name", name},
                           {"system_prompt", body.value("system_prompt", "")},
                           {"style", body.value("style", "")},
                           {"owner_prompt", body.value("owner_prompt", "")},
                           {"rules", body.value("rules", json::array())}};
    save_personas(data);
    send_json(res, {{"ok", true}, {"message", "Persona created"}});
  });
  svr.Post("/api/personas/activate", [this, save_personas](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string name = trim(body.value("name", ""));
    json data = read_json(app_.paths.data_dir + "/web_personas.json", json::object());
    if (!data.value("items", json::object()).contains(name)) {
      send_json(res, {{"ok", false}, {"message", "Persona not found"}}, 404);
      return;
    }
    data["active"] = name;
    save_personas(data);
    app_.config["persona"]["active_persona"] = name;
    save_config_file(app_);
    send_json(res, {{"ok", true}, {"message", "Persona activated"}});
  });
  svr.Get("/api/personas/(.*)", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string key = percent_decode(req.matches[1]);
    json data = read_json(app_.paths.data_dir + "/web_personas.json", json::object());
    json items = data.value("items", json::object());
    if (!items.contains(key)) {
      send_json(res, {{"ok", false}, {"message", "Persona not found"}}, 404);
      return;
    }
    send_json(res, {{"ok", true}, {"item", items[key]}, {"key", key}, {"active", data.value("active", "") == key}});
  });
  svr.Put("/api/personas/(.*)", [this, save_personas](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string key = percent_decode(req.matches[1]);
    json data = read_json(app_.paths.data_dir + "/web_personas.json", json::object());
    if (!data.value("items", json::object()).contains(key)) {
      send_json(res, {{"ok", false}, {"message", "Persona not found"}}, 404);
      return;
    }
    json body = parse_body(req);
    std::string new_name = trim(body.value("name", key));
    if (new_name.empty()) {
      send_json(res, {{"ok", false}, {"message", "Name required"}}, 400);
      return;
    }
    json item = data["items"][key];
    item["name"] = new_name;
    item["system_prompt"] = body.value("system_prompt", "");
    item["style"] = body.value("style", "");
    item["owner_prompt"] = body.value("owner_prompt", "");
    item["rules"] = body.value("rules", json::array());
    data["items"].erase(key);
    data["items"][new_name] = item;
    if (data.value("active", "") == key) {
      data["active"] = new_name;
      app_.config["persona"]["active_persona"] = new_name;
      save_config_file(app_);
    }
    save_personas(data);
    send_json(res, {{"ok", true}, {"message", "Persona saved"}, {"key", new_name}, {"item", item}});
  });
  svr.Delete("/api/personas/(.*)", [this, save_personas](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string key = percent_decode(req.matches[1]);
    json data = read_json(app_.paths.data_dir + "/web_personas.json", json::object());
    if (!data.value("items", json::object()).contains(key)) {
      send_json(res, {{"ok", false}, {"message", "Persona not found"}}, 404);
      return;
    }
    if (data["items"].size() <= 1) {
      send_json(res, {{"ok", false}, {"message", "Keep at least one persona"}}, 400);
      return;
    }
    data["items"].erase(key);
    if (data.value("active", "") == key) {
      for (auto& [k, v] : data["items"].items()) {
        data["active"] = k;
        break;
      }
    }
    save_personas(data);
    send_json(res, {{"ok", true}, {"message", "Persona deleted"}});
  });

  // ----- Comments -----
  svr.Get("/api/comments", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    int limit = 100;
    try {
      limit = std::max(1, std::min(500, std::stoi(qparam(req, "limit", "100"))));
    } catch (...) {
    }
    std::string period = lower(qparam(req, "period", "7d"));
    std::string kind = lower(qparam(req, "kind", "all"));
    std::string query = lower(trim(qparam(req, "q", "")));
    json data = read_json(app_.paths.data_dir + "/comment_log.json", json::object());
    std::vector<json> rows;
    for (const char* coll : {"items", "history"}) {
      const json& arr = data.value(coll, json::array());
      if (arr.is_array()) {
        for (const auto& item : arr) {
          if (item.is_object()) rows.push_back(item);
        }
      }
    }
    json result = json::array();
    std::string today = now_iso().substr(0, 10);
    for (const auto& it : rows) {
      std::string timestamp = it.value("time", it.value("timestamp", it.value("created_at", "")));
      std::string date = timestamp.size() >= 10 ? timestamp.substr(0, 10) : "";
      if (period == "today" && date != today) continue;
      if (period == "7d" && !date.empty() && date < today.substr(0, 4) + "-" + today.substr(5)) continue;
      if (period == "15d" || period == "30d") {
        // Best-effort date comparison; keep if empty.
        if (!date.empty() && date < today) {
          int pd = std::atoi(period.c_str());
          std::time_t now = std::time(nullptr);
          std::tm tm{};
          localtime_r(&now, &tm);
          tm.tm_mday -= pd;
          std::mktime(&tm);
          char cutoff[16];
          std::strftime(cutoff, sizeof(cutoff), "%Y-%m-%d", &tm);
          if (date < cutoff) continue;
        }
      }
      std::string action = it.value("type", it.value("action", "comment"));
      std::string content = it.value("content", it.value("text", it.value("incoming", "")));
      std::string source = it.value("source", it.value("target_user", ""));
      std::string category = "other";
      if (action.find("blocked") != std::string::npos) category = "blocked";
      else if (action == "reply" || action == "comment_reply") category = "reply";
      else if (action == "incoming" || action == "receive") category = "incoming";
      std::string hay = lower(content + " " + source + " " + action);
      if (kind != "all" && category != kind) continue;
      if (!query.empty() && hay.find(query) == std::string::npos) continue;
      result.push_back({{"time", timestamp}, {"type", action}, {"category", category},
                        {"content", content}, {"source", source},
                        {"executed", it.value("executed", true)},
                        {"reason", it.value("reason", "")},
                        {"target_user", it.value("target_user", "")}});
    }
    std::sort(result.begin(), result.end(), [](const json& a, const json& b) {
      return a.value("time", "") > b.value("time", "");
    });
    json out = json::array();
    for (size_t i = 0; i < result.size() && (int)i < limit; i++) out.push_back(result[i]);
    send_json(res, {{"items", out}, {"total", result.size()}, {"period", period}, {"kind", kind}});
  });
  svr.Post("/api/comments/clear", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    if (body.value("confirmed", false) != true) {
      send_json(res, {{"ok", false}, {"message", "Confirm required"}}, 400);
      return;
    }
    std::string path = app_.paths.data_dir + "/comment_log.json";
    json data = read_json(path, json::object());
    std::string period = lower(body.value("period", "all"));
    std::string kind = lower(body.value("kind", "all"));
    std::string query = lower(trim(body.value("q", "")));
    std::string today = now_iso().substr(0, 10);
    int removed = 0;
    auto matches = [&](const json& it) {
      std::string timestamp = it.value("time", it.value("timestamp", it.value("created_at", "")));
      std::string date = timestamp.size() >= 10 ? timestamp.substr(0, 10) : "";
      if (period == "today" && date != today) return false;
      std::string action = it.value("type", it.value("action", "comment"));
      std::string content = it.value("content", it.value("text", it.value("incoming", "")));
      std::string source = it.value("source", it.value("target_user", ""));
      std::string category = "other";
      if (action.find("blocked") != std::string::npos) category = "blocked";
      else if (action == "reply" || action == "comment_reply") category = "reply";
      else if (action == "incoming" || action == "receive") category = "incoming";
      if (kind != "all" && category != kind) return false;
      return query.empty() || lower(content + " " + source + " " + action).find(query) != std::string::npos;
    };
    for (const char* coll : {"items", "history"}) {
      json arr = data.value(coll, json::array());
      if (!arr.is_array()) continue;
      json kept = json::array();
      for (const auto& item : arr) {
        if (item.is_object() && matches(item)) removed++;
        else kept.push_back(item);
      }
      data[coll] = kept;
    }
    write_json(path, data);
    send_json(res, {{"ok", true}, {"removed", removed}, {"message", "Comment log cleared"}});
  });

  // ----- Users -----
  svr.Get("/api/users", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json users = json::object();
    for (const char* f : {"user_profiles.json", "web_user_profiles.json"}) {
      json raw = read_json(app_.paths.data_dir + "/" + f, json::object());
      json wrapped = raw.value("users", raw);
      if (wrapped.is_object()) {
        for (auto& [uid, profile] : wrapped.items()) {
          if (!profile.is_object()) continue;
          json p = users.value(uid, json::object());
          for (auto& [k, v] : profile.items()) p[k] = v;
          users[uid] = p;
        }
      }
    }
    json out = json::object();
    int total = 0, interactions = 0, positive = 0, caution = 0;
    for (auto& [uid, p] : users.items()) {
      double affinity = 0;
      if (p.contains("affinity")) {
        if (p["affinity"].is_number()) affinity = p["affinity"].get<double>();
        else if (p["affinity"].is_string()) {
          try { affinity = std::stod(p["affinity"].get<std::string>()); } catch (...) {}
        }
      }
      double score = affinity >= -1.0 && affinity <= 1.0 ? affinity * 100 : affinity;
      json notes = p.value("notes", json::array());
      if (!notes.is_array()) notes = notes.is_string() ? json::array({notes}) : json::array();
      if (p.contains("impression") && p["impression"].is_string()) notes.push_back(p["impression"]);
      json tags = p.value("tags", json::array());
      if (!tags.is_array()) tags = tags.is_string() ? json::array({tags}) : json::array();
      int interactions_count = 0;
      if (p.contains("interactions")) interactions_count = p["interactions"].is_number() ? (int)p["interactions"].get<long long>() : 0;
      else if (p.contains("interaction_count")) interactions_count = p["interaction_count"].is_number() ? (int)p["interaction_count"].get<long long>() : 0;
      else if (p.contains("comment_count")) interactions_count = p["comment_count"].is_number() ? (int)p["comment_count"].get<long long>() : 0;
      out[uid] = {{"uid", uid}, {"name", p.value("name", uid)}, {"affinity", affinity},
                  {"affinity_score", std::max(-100.0, std::min(100.0, score))},
                  {"interaction_count", interactions_count},
                  {"last_interaction", p.value("last_seen", p.value("last_interaction", p.value("updated_at", "")))},
                  {"notes", notes}, {"tags", tags}};
      total++;
      interactions += interactions_count;
      if (score >= 10) positive++;
      if (score <= -40) caution++;
    }
    send_json(res, {{"ok", true}, {"users", out},
                    {"summary", {{"total", total}, {"interactions", interactions},
                                 {"positive", positive}, {"caution", caution}}}});
  });
  svr.Post("/api/users/update", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string uid = trim(body.value("uid", ""));
    if (uid.empty()) {
      send_json(res, {{"ok", false}, {"message", "UID required"}}, 400);
      return;
    }
    json data = read_json(app_.paths.data_dir + "/user_profiles.json", json::object());
    json store = data.value("users", data);
    if (!store.is_object()) store = json::object();
    json profile = store.value(uid, json::object());
    profile["name"] = body.value("name", profile.value("name", uid));
    profile["tags"] = body.value("tags", json::array());
    profile["notes"] = body.value("notes", json::array());
    profile["updated_at"] = now_iso();
    store[uid] = profile;
    if (data.contains("users") && data["users"].is_object()) data["users"] = store;
    else data = store;
    write_json(app_.paths.data_dir + "/user_profiles.json", data);
    send_json(res, {{"ok", true}, {"message", "Profile saved"}, {"user", profile}});
  });

  // ----- Memory -----
  svr.Get("/api/memory", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json diary = read_json(app_.paths.data_dir + "/bot_diary.json", json::object());
    json entries = diary.value("entries", diary.value("diaries", json::array()));
    if (!entries.is_array()) entries = json::array();
    json evolution = read_json(app_.paths.data_dir + "/self_evolution.json", json::object());
    json events = evolution.value("events", evolution.value("items", json::array()));
    if (!events.is_array()) events = json::array();
    json kb = json::object();
    int total_files = 0;
    std::error_code ec;
    if (fs::exists(app_.paths.knowledge_base_dir, ec)) {
      for (const auto& e : fs::recursive_directory_iterator(app_.paths.knowledge_base_dir, ec)) {
        if (ec) break;
        if (!e.is_regular_file()) continue;
        if (e.path().extension() == ".md") total_files++;
      }
    }
    send_json(res, {{"diary", {{"entries", entries}}},
                    {"evolution", {{"events", events}}},
                    {"knowledge", {{"exists", fs::exists(app_.paths.knowledge_base_dir, ec)},
                                   {"total_files", total_files},
                                   {"categories", json::object()}}}});
  });

  // ----- Watch history -----
  svr.Get("/api/watch-history", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    int offset = 0, limit = 36;
    try {
      offset = std::max(0, std::stoi(qparam(req, "offset", "0")));
      limit = std::max(1, std::min(500, std::stoi(qparam(req, "limit", "36"))));
    } catch (...) {
    }
    std::string query = lower(trim(qparam(req, "q", "")));
    std::string filter_name = qparam(req, "filter", "all");
    json all = watch_history_cards(app_);
    json cards = json::array();
    for (const auto& card : all) {
      std::string title = lower(card.value("title", ""));
      std::string up = lower(card.value("up", ""));
      std::string bvid = card.value("bvid", "");
      std::string category = lower(card.value("category", ""));
      if (!query.empty()) {
        std::string hay = title + " " + up + " " + bvid + " " + category;
        if (hay.find(query) == std::string::npos) continue;
      }
      std::string result = card.value("result", "");
      bool has_result = result.find("skip") != std::string::npos || result.find("unmatch") != std::string::npos || result.find("block") != std::string::npos;
      if (filter_name == "selected" && (result.find("pass") == std::string::npos || has_result)) continue;
      if (filter_name == "archived" && !card.value("archived", false)) continue;
      if (filter_name == "skipped" && !has_result) continue;
      if (filter_name == "matched" && card.value("interest_reason", "").empty()) continue;
      if (filter_name == "interaction") {
        bool any = false;
        for (const auto& a : card.value("actions", json::array())) {
          if (a.get<std::string>() != "watched") any = true;
        }
        if (!any) continue;
      }
      cards.push_back(card);
    }
    json page = json::array();
    for (int i = offset; i < (int)cards.size() && i < offset + limit; i++) page.push_back(cards[i]);
    send_json(res, {{"ok", true}, {"total", cards.size()}, {"offset", offset}, {"limit", limit},
                    {"items", page}, {"counts", {{"all", all.size()}}}});
  });
  svr.Post("/api/watch-history/remove", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    if (body.value("confirmed", false) != true) {
      send_json(res, {{"ok", false}, {"message", "Confirm required"}}, 400);
      return;
    }
    std::string bvid = safe_bvid(body.value("bvid", ""));
    if (bvid.empty()) {
      send_json(res, {{"ok", false}, {"message", "Invalid BV"}}, 400);
      return;
    }
    std::string path = app_.paths.data_dir + "/history_videos.json";
    json data = read_json(path, json::object());
    json kept = json::array();
    int removed = 0;
    for (const auto& item : data.value("videos", json::array())) {
      if (item.is_object() && safe_bvid(item.value("bvid", "")) == bvid) removed++;
      else kept.push_back(item);
    }
    if (!removed) {
      send_json(res, {{"ok", false}, {"message", "Not found"}}, 404);
      return;
    }
    data["videos"] = kept;
    write_json(path, data);
    send_json(res, {{"ok", true}, {"removed", removed}, {"message", "History removed"}});
  });
  svr.Post("/api/watch-history/remove-unmatched", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    if (body.value("confirmed", false) != true) {
      send_json(res, {{"ok", false}, {"message", "Confirm required"}}, 400);
      return;
    }
    std::string path = app_.paths.data_dir + "/history_videos.json";
    json data = read_json(path, json::object());
    json kept = json::array();
    int removed = 0;
    for (const auto& item : data.value("videos", json::array())) {
      std::string result = lower(item.value("result", ""));
      if (result.find("skip") != std::string::npos || result.find("unmatch") != std::string::npos ||
          result.find("block") != std::string::npos) {
        removed++;
      } else {
        kept.push_back(item);
      }
    }
    data["videos"] = kept;
    write_json(path, data);
    send_json(res, {{"ok", true}, {"removed", removed}, {"message", "Unmatched history removed"}});
  });
  svr.Post("/api/watch-history/enrich", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    json bvids = body.value("bvids", json::array());
    std::string meta_path = app_.paths.data_dir + "/watch_history_metadata.json";
    json meta = read_json(meta_path, json::object());
    if (!meta.is_object()) meta = json::object();
    int fetched = 0, failed = 0;
    NetClient net(app_);
    for (const auto& value : bvids) {
      if (fetched + failed >= 12) break;
      std::string bvid = safe_bvid(value.is_string() ? value.get<std::string>() : "");
      if (bvid.empty() || meta.contains(bvid)) continue;
      std::string err;
      VideoInfo info = video_info(net, bvid, 0, err);
      if (!info.bvid.empty()) {
        json detail = {{"pic", ""}, {"duration", 0}, {"category", ""}, {"description", info.desc},
                       {"published_at", 0}, {"view_count", 0}, {"like_count", 0},
                       {"coin_count", 0}, {"favorite_count", 0}, {"danmaku_count", 0},
                       {"up", ""}, {"title", info.title}, {"updated_at", now_iso()}};
        NetResponse view = net.get("https://api.bilibili.com/x/web-interface/view",
                                   {{"bvid", bvid}}, {}, true);
        try {
          json j = json::parse(view.body);
          const json& d = j["data"];
          detail["pic"] = d.value("pic", "");
          detail["duration"] = d.value("duration", 0);
          detail["category"] = d.value("tname", "");
          detail["description"] = d.value("desc", "");
          detail["published_at"] = d.value("pubdate", 0);
          const json& stat = d.value("stat", json::object());
          detail["view_count"] = stat.value("view", 0);
          detail["like_count"] = stat.value("like", 0);
          detail["coin_count"] = stat.value("coin", 0);
          detail["favorite_count"] = stat.value("favorite", 0);
          detail["danmaku_count"] = stat.value("danmaku", 0);
          const json& owner = d.value("owner", json::object());
          detail["up"] = owner.value("name", "");
        } catch (...) {
        }
        meta[bvid] = detail;
        fetched++;
      } else {
        failed++;
      }
    }
    if (fetched) write_json(meta_path, meta);
    send_json(res, {{"ok", true}, {"fetched", fetched}, {"failed", failed},
                    {"items", watch_history_cards(app_)}});
  });

  // ----- Favorites -----
  auto favorite_library = [this]() -> json {
    json data = read_json(app_.paths.data_dir + "/video_favorites.json", json::object());
    if (!data.contains("folders") || !data["folders"].is_array()) data["folders"] = json::array();
    if (!data.contains("items") || !data["items"].is_array()) data["items"] = json::array();
    return data;
  };
  auto favorite_payload = [this, favorite_library]() -> json {
    json lib = favorite_library();
    json cards = watch_history_cards(app_);
    json meta = read_json(app_.paths.data_dir + "/watch_history_metadata.json", json::object());
    std::map<std::string, json> card_map;
    for (const auto& c : cards) card_map[c.value("bvid", "")] = c;
    json folders = json::array();
    for (const auto& f : lib["folders"]) {
      std::string id = f.value("id", "");
      json items = json::array();
      for (const auto& item : lib["items"]) {
        if (item.value("folder_id", "") != id) continue;
        std::string bvid = item.value("bvid", "");
        json card = card_map.count(bvid) ? card_map[bvid] : json::object();
        card["favorite_added_at"] = item.value("added_at", "");
        card["favorite_source"] = item.value("source", "");
        items.push_back(card);
      }
      folders.push_back({{"id", id}, {"name", f.value("name", "")}, {"count", items.size()}, {"items", items}});
    }
    return {{"ok", true}, {"folders", folders}};
  };
  auto new_folder_id = [this]() -> std::string {
    return "f" + std::to_string(now_epoch());
  };
  svr.Get("/api/favorites", [this, favorite_payload](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    send_json(res, favorite_payload());
  });
  svr.Post("/api/favorites/folders", [this, favorite_library, favorite_payload, new_folder_id](
                                         const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string name = trim(body.value("name", ""));
    if (name.empty()) {
      send_json(res, {{"ok", false}, {"message", "Name required"}}, 400);
      return;
    }
    json lib = favorite_library();
    for (const auto& f : lib["folders"]) {
      if (lower(f.value("name", "")) == lower(name)) {
        send_json(res, {{"ok", false}, {"message", "Duplicate folder"}}, 409);
        return;
      }
    }
    json folder = {{"id", new_folder_id()}, {"name", name}, {"created_at", now_iso()}};
    lib["folders"].push_back(folder);
    write_json(app_.paths.data_dir + "/video_favorites.json", lib);
    json payload = favorite_payload();
    send_json(res, {{"ok", true}, {"folder", folder}, {"message", "Folder created"}});
  });
  svr.Get("/api/favorites/folders/(.*)", [this, favorite_library](
                                              const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string id = percent_decode(req.matches[1]);
    json lib = favorite_library();
    for (const auto& f : lib["folders"]) {
      if (f.value("id", "") == id) {
        send_json(res, {{"ok", true}, {"folder", f}});
        return;
      }
    }
    send_json(res, {{"ok", false}, {"message", "Folder not found"}}, 404);
  });
  svr.Put("/api/favorites/folders/(.*)", [this, favorite_library](
                                             const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string id = percent_decode(req.matches[1]);
    json body = parse_body(req);
    json lib = favorite_library();
    bool found = false;
    for (auto& f : lib["folders"]) {
      if (f.value("id", "") == id) {
        f["name"] = trim(body.value("name", f.value("name", "")));
        found = true;
        break;
      }
    }
    if (!found) {
      send_json(res, {{"ok", false}, {"message", "Folder not found"}}, 404);
      return;
    }
    write_json(app_.paths.data_dir + "/video_favorites.json", lib);
    send_json(res, {{"ok", true}, {"message", "Folder renamed"}});
  });
  svr.Delete("/api/favorites/folders/(.*)", [this, favorite_library](
                                               const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string id = percent_decode(req.matches[1]);
    json lib = favorite_library();
    json folders = json::array();
    for (auto& f : lib["folders"]) {
      if (f.value("id", "") != id) folders.push_back(f);
    }
    json items = json::array();
    for (auto& item : lib["items"]) {
      if (item.value("folder_id", "") != id) items.push_back(item);
    }
    lib["folders"] = folders;
    lib["items"] = items;
    write_json(app_.paths.data_dir + "/video_favorites.json", lib);
    send_json(res, {{"ok", true}, {"message", "Folder deleted"}});
  });
  svr.Post("/api/favorites/items", [this, favorite_library, favorite_payload](
                                       const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string folder_id = body.value("folder_id", "");
    std::string bvid = safe_bvid(body.value("bvid", ""));
    json lib = favorite_library();
    bool folder_ok = false;
    for (const auto& f : lib["folders"]) {
      if (f.value("id", "") == folder_id) folder_ok = true;
    }
    if (!folder_ok || bvid.empty()) {
      send_json(res, {{"ok", false}, {"message", "Invalid folder or BV"}}, 400);
      return;
    }
    bool exists = false;
    for (const auto& item : lib["items"]) {
      if (item.value("folder_id", "") == folder_id && safe_bvid(item.value("bvid", "")) == bvid) exists = true;
    }
    if (!exists) {
      lib["items"].push_back({{"folder_id", folder_id}, {"bvid", bvid},
                              {"added_at", now_iso()}, {"source", body.value("source", "user")}});
      write_json(app_.paths.data_dir + "/video_favorites.json", lib);
    }
    json payload = favorite_payload();
    send_json(res, {{"ok", true}, {"message", "Added to folder"}});
  });
  svr.Delete("/api/favorites/items", [this, favorite_library](
                                         const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string folder_id = body.value("folder_id", "");
    std::string bvid = safe_bvid(body.value("bvid", ""));
    json lib = favorite_library();
    json kept = json::array();
    int removed = 0;
    for (auto& item : lib["items"]) {
      if (item.value("folder_id", "") == folder_id && safe_bvid(item.value("bvid", "")) == bvid) removed++;
      else kept.push_back(item);
    }
    lib["items"] = kept;
    write_json(app_.paths.data_dir + "/video_favorites.json", lib);
    send_json(res, {{"ok", true}, {"removed", removed}, {"message", "Removed from folder"}});
  });
  svr.Post("/api/favorites/import-history", [this, favorite_library, favorite_payload](
                                                const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string folder_id = body.value("folder_id", "");
    json lib = favorite_library();
    bool folder_ok = false;
    for (const auto& f : lib["folders"]) {
      if (f.value("id", "") == folder_id) folder_ok = true;
    }
    if (!folder_ok) {
      send_json(res, {{"ok", false}, {"message", "Folder not found"}}, 400);
      return;
    }
    std::map<std::string, bool> existing;
    for (const auto& item : lib["items"]) {
      if (item.value("folder_id", "") == folder_id) existing[safe_bvid(item.value("bvid", ""))] = true;
    }
    int added = 0;
    for (const auto& card : watch_history_cards(app_)) {
      std::string bvid = card.value("bvid", "");
      std::string result = lower(card.value("result", ""));
      if (bvid.empty() || existing.count(bvid) || card.value("interest_reason", "").empty()) continue;
      if (result.find("skip") != std::string::npos || result.find("unmatch") != std::string::npos ||
          result.find("block") != std::string::npos) continue;
      lib["items"].push_back({{"folder_id", folder_id}, {"bvid", bvid},
                              {"added_at", now_iso()}, {"source", "interest"}});
      existing[bvid] = true;
      added++;
    }
    if (added) write_json(app_.paths.data_dir + "/video_favorites.json", lib);
    json payload = favorite_payload();
    send_json(res, {{"ok", true}, {"added", added}, {"message", "Matched videos imported"}});
  });

  // ----- Diary -----
  svr.Get("/api/diary", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json diary = read_json(app_.paths.data_dir + "/bot_diary.json", json::object());
    json entries = diary.value("entries", diary.value("diaries", json::array()));
    if (!entries.is_array()) entries = json::array();
    for (size_t i = 0; i < entries.size(); i++) {
      if (!entries[i].contains("id")) {
        entries[i]["id"] = "legacy-" + std::to_string(i) + "-" + entries[i].value("time", "");
      }
    }
    json evolution = read_json(app_.paths.data_dir + "/self_evolution.json", json::object());
    json events = evolution.value("events", evolution.value("items", json::array()));
    send_json(res, {{"diary", {{"entries", entries}}}, {"evolution", {{"events", events}}}});
  });
  svr.Post("/api/diary/entry", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string content = trim(body.value("content", ""));
    if (content.empty()) {
      send_json(res, {{"ok", false}, {"message", "Content required"}}, 400);
      return;
    }
    std::string path = app_.paths.data_dir + "/bot_diary.json";
    json data = read_json(path, json::object());
    if (!data.contains("entries") || !data["entries"].is_array()) data["entries"] = json::array();
    json mood = read_json(app_.paths.data_dir + "/mood_state.json", json::object());
    json entry = {{"id", "diary-" + std::to_string(now_epoch() * 1000)},
                  {"title", trim(body.value("title", "manual diary"))},
                  {"content", content}, {"time", now_iso()},
                  {"mood", mood.value("mood", "calm")}, {"energy", mood.value("energy", 100)},
                  {"tags", json::array({"manual"})}, {"source", "web_manual"}, {"entry_type", "manual"}};
    data["entries"].push_back(entry);
    write_json(path, data);
    send_json(res, {{"ok", true}, {"entry", entry}, {"message", "Diary saved"}});
  });
  auto diary_find = [this](const std::string& id, json& data) -> size_t {
    json entries = data.value("entries", json::array());
    if (!entries.is_array()) entries = data.value("diaries", json::array());
    for (size_t i = 0; i < entries.size(); i++) {
      if (!entries[i].is_object()) continue;
      std::string actual = entries[i].value("id", "");
      std::string legacy = "legacy-" + std::to_string(i) + "-" + entries[i].value("time", "");
      if (actual == id || legacy == id) return i;
    }
    return std::string::npos;
  };
  svr.Get("/api/diary/entry/(.*)", [this, diary_find](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string id = percent_decode(req.matches[1]);
    json data = read_json(app_.paths.data_dir + "/bot_diary.json", json::object());
    size_t idx = diary_find(id, data);
    if (idx == std::string::npos) {
      send_json(res, {{"ok", false}, {"message", "Not found"}}, 404);
      return;
    }
    send_json(res, {{"ok", true}, {"entry", data["entries"][idx]}});
  });
  svr.Put("/api/diary/entry/(.*)", [this, diary_find](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string id = percent_decode(req.matches[1]);
    json body = parse_body(req);
    std::string content = trim(body.value("content", ""));
    if (content.empty()) {
      send_json(res, {{"ok", false}, {"message", "Content required"}}, 400);
      return;
    }
    std::string path = app_.paths.data_dir + "/bot_diary.json";
    json data = read_json(path, json::object());
    size_t idx = diary_find(id, data);
    if (idx == std::string::npos) {
      send_json(res, {{"ok", false}, {"message", "Not found"}}, 404);
      return;
    }
    json entries = data.value("entries", json::array());
    if (!entries.is_array()) entries = data.value("diaries", json::array());
    entries[idx]["id"] = entries[idx].value("id", "diary-" + std::to_string(now_epoch() * 1000));
    entries[idx]["title"] = body.value("title", entries[idx].value("title", "diary"));
    entries[idx]["content"] = content;
    entries[idx]["updated_at"] = now_iso();
    data["entries"] = entries;
    data.erase("diaries");
    write_json(path, data);
    send_json(res, {{"ok", true}, {"entry", entries[idx]}, {"message", "Diary updated"}});
  });
  svr.Delete("/api/diary/entry/(.*)", [this, diary_find](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string id = percent_decode(req.matches[1]);
    std::string path = app_.paths.data_dir + "/bot_diary.json";
    json data = read_json(path, json::object());
    size_t idx = diary_find(id, data);
    if (idx == std::string::npos) {
      send_json(res, {{"ok", false}, {"message", "Not found"}}, 404);
      return;
    }
    json entries = data.value("entries", json::array());
    if (!entries.is_array()) entries = data.value("diaries", json::array());
    entries.erase(entries.begin() + idx);
    data["entries"] = entries;
    data.erase("diaries");
    write_json(path, data);
    send_json(res, {{"ok", true}, {"message", "Diary deleted"}});
  });

  // ----- Actions / charts / mood / behavior -----
  svr.Get("/api/actions", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    int limit = 50;
    try {
      limit = std::max(1, std::stoi(qparam(req, "limit", "50")));
    } catch (...) {
    }
    json data = read_json(app_.paths.data_dir + "/web_action_log.json", json::object());
    json items = data.value("items", json::array());
    json out = json::array();
    int start = std::max(0, (int)items.size() - limit);
    for (int i = start; i < (int)items.size(); i++) {
      out.push_back({{"time", items[i].value("created_at", items[i].value("time", ""))},
                     {"action", items[i].value("action", "")},
                     {"payload", items[i].value("payload", json::object())},
                     {"executed", items[i].value("executed", false)}});
    }
    send_json(res, {{"items", out}});
  });
  svr.Get("/api/charts", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    int days = 14;
    try {
      days = std::max(1, std::min(90, std::stoi(qparam(req, "days", "14"))));
    } catch (...) {
    }
    json diary = read_json(app_.paths.data_dir + "/bot_diary.json", json::object());
    json moods = json::array();
    for (const auto& e : diary.value("entries", json::array())) {
      std::string t = e.value("time", "");
      moods.push_back({{"date", t.size() >= 10 ? t.substr(0, 10) : t},
                       {"valence", e.value("mood_score", e.value("valence", 50))},
                       {"energy", e.value("energy", 50)}});
    }
    send_json(res, {{"comments", json::array()}, {"moods", moods},
                    {"actions", json::array()}, {"videos", json::array()}});
  });
  svr.Get("/api/mood/status", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json mood = read_json(app_.paths.data_dir + "/mood_state.json", json::object());
    json mc = app_.config.value("mood", json::object());
    send_json(res, {{"current_mood", mood.value("mood", mc.value("default_mood", "calm"))},
                    {"energy", mood.value("energy", 100)},
                    {"random_enabled", mc.value("random_enabled", false)},
                    {"random_interval", mc.value("random_interval_minutes", 5)},
                    {"custom_enabled", mc.value("custom_enabled", false)},
                    {"custom_mood", mc.value("custom_mood", "")},
                    {"default_mood", mc.value("default_mood", "calm")}});
  });
  svr.Post("/api/mood/set", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    json mc = app_.config.value("mood", json::object());
    for (const char* key : {"random_enabled", "custom_enabled"}) {
      if (body.contains(key)) mc[key] = body[key].get<bool>();
    }
    for (const char* key : {"random_interval_minutes"}) {
      if (body.contains(key)) mc[key] = body[key];
    }
    for (const char* key : {"custom_mood", "default_mood"}) {
      if (body.contains(key)) mc[key] = body[key];
    }
    app_.config["mood"] = mc;
    save_config_file(app_);
    if (body.contains("current_mood")) {
      json mood = read_json(app_.paths.data_dir + "/mood_state.json", json::object());
      mood["mood"] = body["current_mood"];
      mood["updated_at"] = now_iso();
      write_json(app_.paths.data_dir + "/mood_state.json", mood);
    }
    send_json(res, {{"ok", true}, {"message", "Mood saved"}});
  });
  svr.Get("/api/behavior/get", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json behavior = app_.config.value("behavior", json::object());
    json energy = app_.config.value("energy", json::object());
    json interaction = app_.config.value("interaction", json::object());
    send_json(res, {{"ok", true}, {"behavior", behavior}, {"energy", energy}, {"interaction", interaction},
                    {"ai_marker", behavior.value("ai_marker", "")},
                    {"ai_marker_enabled", behavior.value("ai_marker_enabled", true)}});
  });
  svr.Post("/api/behavior/save", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    if (body.contains("ai_marker")) app_.config["behavior"]["ai_marker"] = body["ai_marker"];
    if (body.contains("energy")) app_.config["energy"]["base_energy"] = body["energy"];
    if (body.contains("comment_mode")) app_.config["behavior"]["comment_mode"] = body["comment_mode"];
    if (body.contains("energy_recovery_min")) app_.config["energy"]["energy_recovery_min"] = body["energy_recovery_min"];
    if (body.contains("energy_recovery_max")) app_.config["energy"]["energy_recovery_max"] = body["energy_recovery_max"];
    save_config_file(app_);
    send_json(res, {{"ok", true}, {"message", "Behavior saved"}});
  });
  svr.Post("/api/behavior/ai-marker/toggle", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    app_.config["behavior"]["ai_marker_enabled"] = body.value("enabled", false);
    save_config_file(app_);
    send_json(res, {{"ok", true}, {"message", "AI marker toggled"}});
  });
  svr.Get("/api/behavior/safety", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json safety = app_.config.value("reply_safety", json::object());
    send_json(res, {{"ok", true}, {"enabled", safety.value("enabled", false)},
                    {"keywords", safety.value("blocked_keywords", json::array())}});
  });
  svr.Post("/api/behavior/safety/toggle", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    app_.config["reply_safety"]["enabled"] = body.value("enabled", false);
    save_config_file(app_);
    send_json(res, {{"ok", true}, {"message", "Safety toggled"}});
  });
  svr.Post("/api/behavior/safety/save", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    json keywords = body.value("keywords", json::array());
    if (keywords.is_string()) {
      std::string raw = keywords.get<std::string>();
      keywords = json::array();
      size_t pos = 0;
      while (pos <= raw.size()) {
        size_t comma = raw.find_first_of(",\n", pos);
        std::string term = trim(raw.substr(pos, comma == std::string::npos ? std::string::npos : comma - pos));
        if (!term.empty()) keywords.push_back(term);
        if (comma == std::string::npos) break;
        pos = comma + 1;
      }
    }
    app_.config["reply_safety"]["blocked_keywords"] = keywords;
    save_config_file(app_);
    send_json(res, {{"ok", true}, {"message", "Safety keywords saved"}});
  });
  svr.Post("/api/behavior/safety/political-preset", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json preset = json::array({"president", "chairman", "supreme leader", "politburo", "military parade",
                               "presidential election", "state funeral"});
    app_.config["reply_safety"]["blocked_keywords"] = preset;
    save_config_file(app_);
    send_json(res, {{"ok", true}, {"message", "Political safety preset applied"}});
  });
  svr.Get("/api/display/score-colors", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json colors = app_.config.value("display", json::object()).value("score_colors", json::object());
    if (colors.empty()) {
      colors = {{"green", "#16a34a"}, {"blue", "#2563eb"}, {"yellow", "#a16207"},
                {"orange", "#ea580c"}, {"red", "#dc2626"}};
    }
    send_json(res, {{"ok", true}, {"colors", colors}});
  });
  svr.Post("/api/display/score-colors", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    json colors = body.value("colors", json::object());
    app_.config["display"]["score_colors"] = colors;
    save_config_file(app_);
    send_json(res, {{"ok", true}, {"colors", colors}});
  });

  // ----- Observe / timeline -----
  svr.Get("/api/observe", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json runtime = read_json(app_.paths.data_dir + "/bot_runtime_state.json", json::object());
    json observation = runtime.value("video_observation", json::object());
    if (!observation.is_object()) observation = json::object();
    std::string bvid = safe_bvid(observation.value("bvid", ""));
    json cards = watch_history_cards(app_);
    json card = json::object();
    for (const auto& c : cards) {
      if (c.value("bvid", "") == bvid) {
        card = c;
        break;
      }
    }
    observation["bvid"] = bvid;
    auto str_field = [](const json& obj, const char* key, const json& fallback) -> std::string {
      if (obj.contains(key) && obj[key].is_string()) return obj[key].get<std::string>();
      if (fallback.is_string()) return fallback.get<std::string>();
      return "";
    };
    observation["title"] = str_field(observation, "title", json(card.value("title", bvid)));
    observation["up"] = str_field(observation, "up", json(card.value("up", "")));
    observation["cover"] = str_field(observation, "cover", json(card.value("cover", "")));
    observation["duration"] = str_field(observation, "duration", json(std::string(card.value("duration", "--:--"))));
    observation["category"] = str_field(observation, "category", json(card.value("category", "")));
    observation["url"] = bvid.empty() ? "" : "https://www.bilibili.com/video/" + bvid;
    observation["score"] = (observation.contains("score") && observation["score"].is_number())
                              ? observation["score"]
                              : json(card.value("score", 0));
    observation["recent"] = json::array();
    for (const auto& c : cards) {
      if (c.value("bvid", "") != bvid) observation["recent"].push_back(c);
    }
    observation["running"] = bot_running_.load();
    json logs = json::array();
    {
      std::lock_guard<std::mutex> lock(bot_log_mu_);
      size_t start = bot_log_.size() > 32 ? bot_log_.size() - 32 : 0;
      for (size_t i = start; i < bot_log_.size(); i++) logs.push_back(bot_log_[i]);
    }
    observation["logs"] = logs;
    observation["activity"] = {{"label", bot_running_.load() ? "bot running" : "bot stopped"},
                               {"detail", bot_running_.load() ? "waiting for next task" : "showing last state"},
                               {"inferred", false}};
    bool awareness = app_.config.value("ui", json::object()).value("observation_user_awareness", false);
    send_json(res, {{"ok", true}, {"observation", observation}, {"user_awareness", awareness}});
  });
  svr.Post("/api/observe/settings", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    app_.config["ui"]["observation_user_awareness"] = body.value("user_awareness", false);
    save_config_file(app_);
    send_json(res, {{"ok", true}, {"user_awareness", app_.config["ui"]["observation_user_awareness"]}});
  });
  svr.Post("/api/observe/force-judge", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json runtime = read_json(app_.paths.data_dir + "/bot_runtime_state.json", json::object());
    std::string bvid = safe_bvid(runtime.value("video_observation", json::object()).value("bvid", ""));
    if (bvid.empty()) {
      send_json(res, {{"ok", false}, {"message", "No current video"}}, 409);
      return;
    }
    NetClient net(app_);
    AiClient ai(app_, net);
    std::string err;
    VideoInfo info = video_info(net, bvid, 0, err);
    std::string prompt = "Give a brief 0-10 watching value score and reasons. Do not claim you watched it.\n";
    prompt += "Title: " + info.title + "\nDesc: " + info.desc;
    std::string answer = ai.chat({{"system", "You are a cautious video evaluator."}, {"user", prompt}});
    if (answer.empty()) {
      send_json(res, {{"ok", false}, {"message", "AI returned empty"}}, 502);
      return;
    }
    send_json(res, {{"ok", true}, {"answer", answer}, {"bvid", bvid}});
  });
  svr.Get("/api/video/timeline", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string bvid = safe_bvid(qparam(req, "bvid", ""));
    if (bvid.empty()) {
      send_json(res, {{"ok", false}, {"message", "Invalid BV"}}, 400);
      return;
    }
    std::string path = app_.paths.data_dir + "/subtitle_timeline_" + bvid + ".json";
    json data = read_json(path, json::object());
    json segments = data.value("segments", json::array());
    if (!segments.is_array() || segments.empty()) {
      send_json(res, {{"ok", false}, {"message", "No CC timeline available"}}, 404);
      return;
    }
    send_json(res, {{"ok", true}, {"bvid", bvid}, {"track", data.value("track", "")},
                    {"updated_at", data.value("updated_at", "")}, {"segments", segments},
                    {"total", segments.size()}});
  });
  svr.Get("/api/video/timeline/backfill", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json data = read_json(app_.paths.data_dir + "/subtitle_timeline_backfill.json", json::object());
    send_json(res, {{"running", data.value("running", false)}, {"pending", data.value("pending", 0)},
                    {"completed", data.value("completed", 0)}, {"queued", data.value("queued", 0)},
                    {"available", data.value("available", 0)}, {"unavailable", data.value("unavailable", 0)},
                    {"current", data.value("current", "")}});
  });
  svr.Post("/api/video/timeline/backfill", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    int limit = body.value("limit", 20);
    std::string path = app_.paths.data_dir + "/subtitle_timeline_backfill.json";
    json data = read_json(path, json::object());
    data["running"] = true;
    data["queued"] = limit;
    data["completed"] = 0;
    write_json(path, data);
    send_json(res, {{"ok", true}, {"message", "Timeline backfill started"}});
  });
  svr.Post("/api/video/timeline/answer", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string bvid = safe_bvid(body.value("bvid", ""));
    std::string question = trim(body.value("question", ""));
    if (bvid.empty() || question.empty()) {
      send_json(res, {{"ok", false}, {"message", "BV and question required"}}, 400);
      return;
    }
    std::string path = app_.paths.data_dir + "/subtitle_timeline_" + bvid + ".json";
    json data = read_json(path, json::object());
    std::string context;
    for (const auto& s : data.value("segments", json::array())) {
      context += s.value("text", "") + "\n";
    }
    std::string answer = ai_chat_once(
        app_, "You answer from timestamped CC subtitles only.",
        "Question: " + question + "\nCC subtitles:\n" + context);
    send_json(res, {{"ok", true}, {"answer", answer.empty() ? "No answer available" : answer}});
  });

  // ----- Export / import / factory reset -----
  svr.Post("/api/export", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string backup_dir = app_.paths.user_data_dir + "/Backups";
    std::error_code ec;
    fs::create_directories(backup_dir, ec);
    json files = body.value("groups", json::array());
    if (files.empty()) files = json::array({"settings", "memory", "knowledge", "exports"});
    std::string ts = timestamp_suffix();
    std::string out = backup_dir + "/bilibili_learning_bot_backup_" + ts + ".zip";
    std::vector<ZipEntry> zip_entries;
    zip_entries.push_back({"manifest.json", json({{"version", "1"}, {"created_at", now_iso()},
                            {"groups", files}, {"privacy", "credentials excluded"}}).dump(2)});
    for (const auto& g : files) {
      std::string group = g.get<std::string>();
      if (group == "settings") {
        json cfg = app_.config;
        zip_entries.push_back({"settings/config.json", cfg.dump(2)});
      } else if (group == "knowledge") {
        if (fs::exists(app_.paths.knowledge_base_dir, ec)) {
          for (const auto& e : fs::recursive_directory_iterator(app_.paths.knowledge_base_dir, ec)) {
            if (ec || !e.is_regular_file()) continue;
            std::string rel = fs::relative(e.path(), app_.paths.knowledge_base_dir).generic_string();
            zip_entries.push_back({"knowledge/KnowledgeBase/" + rel, read_file(e.path().string())});
          }
        }
      } else {
        for (const auto& e : fs::directory_iterator(app_.paths.data_dir, ec)) {
          if (ec || !e.is_regular_file() || e.path().extension() != ".json") continue;
          std::string name = e.path().filename().string();
          if (name == "config.json" || name == "bilibili_cookies.json") continue;
          zip_entries.push_back({group + "/" + name, read_file(e.path().string())});
        }
      }
    }
    std::string zip = build_zip(zip_entries);
    if (!write_file(out, zip)) {
      send_json(res, {{"ok", false}, {"message", "Backup write failed"}}, 500);
      return;
    }
    send_json(res, {{"ok", true}, {"message", "Backup created"}, {"path", out}, {"groups", files}});
  });
  svr.Get("/api/import", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string dir = app_.paths.user_data_dir + "/Backups";
    json files = json::array();
    std::error_code ec;
    if (fs::exists(dir, ec)) {
      std::vector<fs::path> paths;
      for (const auto& e : fs::directory_iterator(dir, ec)) {
        if (e.is_regular_file() && (e.path().extension() == ".json" || e.path().extension() == ".zip")) paths.push_back(e.path());
      }
      std::sort(paths.begin(), paths.end(), [](const fs::path& a, const fs::path& b) {
        return fs::last_write_time(a) > fs::last_write_time(b);
      });
      for (size_t i = 0; i < paths.size() && i < 20; i++) {
        std::error_code fec;
        files.push_back({{"name", paths[i].filename().string()}, {"mtime", ""}, {"size", size_kb(fs::file_size(paths[i], fec))}});
      }
    }
    send_json(res, {{"files", files}});
  });
  svr.Post("/api/import/apply", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string fname = trim(body.value("filename", ""));
    if (fname.empty()) {
      send_json(res, {{"ok", false}, {"message", "Filename required"}}, 400);
      return;
    }
    std::string dir = app_.paths.user_data_dir + "/Backups";
    std::string path = dir + "/" + fname;
    if (!fs::exists(path)) {
      send_json(res, {{"ok", false}, {"message", "Backup not found"}}, 404);
      return;
    }
    json data = read_json(path, json::object());
    int count = 0;
    for (auto& [key, val] : data.items()) {
      std::string dest = key == "bot_memory.json" || key == "knowledge_metadata.json"
                           ? app_.paths.user_data_dir + "/" + key
                           : app_.paths.data_dir + "/" + key;
      write_json(dest, val);
      count++;
    }
    send_json(res, {{"ok", true}, {"message", "Backup applied"}, {"count", count}});
  });
  svr.Post("/api/factory-reset/request", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    json selected = body.value("selected_groups", json::array());
    std::string token = "RST-" + std::to_string(now_epoch()) + "-" + std::to_string(rand());
    {
      std::lock_guard<std::mutex> lock(state_mu_);
      factory_token_ = token;
      factory_token_at_ = now_epoch();
      factory_groups_.clear();
      for (const auto& g : selected) factory_groups_.push_back(g.get<std::string>());
    }
    json preview = preview_reset_groups(app_, selected);
    send_json(res, {{"ok", true}, {"token", token}, {"preview", preview}});
  });
  svr.Post("/api/factory-reset", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string token = trim(body.value("confirm_token", ""));
    {
      std::lock_guard<std::mutex> lock(state_mu_);
      if (factory_token_.empty() || factory_token_ != token || now_epoch() - factory_token_at_ > 60) {
        factory_token_.clear();
        send_json(res, {{"ok", false}, {"message", "Invalid or expired token"}}, 403);
        return;
      }
      factory_token_.clear();
    }
    json selected = body.value("selected_groups", json::array());
    int deleted = erase_reset_groups(app_, selected);
    send_json(res, {{"ok", true}, {"message", "Factory reset complete"}, {"deleted", deleted}});
  });
  // ----- Cookie refresh / web search / RAG -----
  svr.Post("/api/bili/refresh", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    NetClient net(app_);
    std::string err;
    bool ok = refresh_cookies(app_, net, err);
    send_json(res, {{"ok", ok}, {"message", err.empty() ? "cookies refreshed" : err}});
  });
  svr.Post("/api/search/web", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string query = trim(body.value("query", ""));
    if (query.empty()) { send_json(res, {{"ok", false}, {"message", "query required"}}, 400); return; }
    NetClient net(app_);
    send_json(res, {{"ok", true}, {"results", web_search(net, query, body.value("limit", 5))}});
  });
  svr.Post("/api/rag/ask", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string question = trim(body.value("question", ""));
    if (question.empty()) { send_json(res, {{"ok", false}, {"message", "question required"}}, 400); return; }
    NetClient net(app_);
    AiClient ai(app_, net);
    send_json(res, rag_answer(app_, net, ai, question));
  });

  // ----- AI verification -----
  svr.Post("/api/action/verify-subtitle", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string bvid = safe_bvid(body.value("bvid", ""));
    std::string subtitle = body.value("subtitle", "");
    if (bvid.empty() && subtitle.empty()) {
      send_json(res, {{"ok", false}, {"message", "bvid or subtitle required"}}, 400);
      return;
    }
    NetClient net(app_);
    AiClient ai(app_, net);
    std::string title = "";
    if (bvid.empty() == false && subtitle.empty()) {
      std::string err;
      VideoInfo info = video_info(net, bvid, 0, err);
      title = info.title;
      VideoAnalysis va;
      if (analyze_video(app_, net, ai, bvid, va, err)) subtitle = va.subtitles;
    }
    send_json(res, verify_subtitle_ai(ai, title.empty() ? body.value("title", "") : title, subtitle));
  });
  svr.Post("/api/search/web-verify", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string query = trim(body.value("query", ""));
    if (query.empty()) { send_json(res, {{"ok", false}, {"message", "query required"}}, 400); return; }
    NetClient net(app_);
    AiClient ai(app_, net);
    json results = body.contains("results") ? body["results"] : web_search(net, query, 5);
    send_json(res, verify_search_ai(ai, query, results));
  });

  // ----- Video ASR / psycho deep / platform adapter -----
  svr.Post("/api/action/video-asr", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string bvid = safe_bvid(body.value("bvid", ""));
    if (bvid.empty()) { send_json(res, {{"ok", false}, {"message", "bvid required"}}, 400); return; }
    NetClient net(app_);
    AiClient ai(app_, net);
    send_json(res, video_asr(app_, net, ai, bvid));
  });
  svr.Post("/api/psycho/deep-analyze", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    NetClient net(app_);
    AiClient ai(app_, net);
    send_json(res, psycho_deep_analyze(app_, net, ai));
  });
  svr.Post("/api/platform/adapter", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string url = trim(body.value("url", ""));
    if (url.empty()) { send_json(res, {{"ok", false}, {"message", "url required"}}, 400); return; }
    NetClient net(app_);
    send_json(res, platform_download_plan(app_, net, url));
  });

  // ----- Proactive / evolution -----
  svr.Get("/api/proactive/status", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    send_json(res, proactive_status(app_));
  });
  svr.Post("/api/proactive/toggle", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    app_.config["proactive"]["enabled"] = body.value("enabled", false);
    save_config_file(app_);
    send_json(res, {{"ok", true}, {"enabled", body.value("enabled", false)}});
  });
  svr.Post("/api/proactive/run", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    send_json(res, run_proactive_cycle(app_, monitor_));
  });
  svr.Get("/api/evolution/status", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    send_json(res, evolution_status(app_));
  });
  svr.Post("/api/evolution/trigger", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    NetClient net(app_);
    AiClient ai(app_, net);
    send_json(res, evolution_reflect(app_, net, ai, body.value("force", false)));
  });

  // ----- ASR / system / owner share / up follow -----
  svr.Get("/api/asr/status", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json asr = app_.config.value("asr", json::object());
    std::string model_path = asr.value("model_path", "");
    bool model_ready = !model_path.empty() && fs::exists(model_path);
    send_json(res, {{"enabled", asr.value("enabled", false)}, {"backend", asr.value("backend", "none")},
                    {"model_path", model_path}, {"model_ready", model_ready}, {"job", json::object()}});
  });
  svr.Post("/api/asr/download", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string model_path = app_.paths.data_dir + "/models/asr/ggml-tiny.bin";
    app_.config["asr"]["enabled"] = true;
    app_.config["asr"]["backend"] = "whisper.cpp";
    app_.config["asr"]["model_path"] = model_path;
    app_.config["asr"]["downloading"] = true;
    save_config_file(app_);
    std::thread([this, model_path]() {
      NetClient net(app_);
      NetResponse resp = net.raw_get(
          "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin");
      bool ok = resp.http_code >= 200 && resp.http_code < 400 && !resp.body.empty();
      if (ok) write_file(model_path, resp.body);
      app_.config["asr"]["downloading"] = false;
      app_.config["asr"]["model_ready"] = ok;
      save_config_file(app_);
      append_bot_log(ok ? "ASR model downloaded" : "ASR model download failed");
    }).detach();
    send_json(res, {{"ok", true}, {"message", "ASR model download started"},
                    {"status", {{"state", "running"}, {"model_path", model_path}}}});
  });
  svr.Get("/api/system/metrics", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    send_json(res, {{"cpu_percent", 0}, {"memory_mb", 0}, {"disk_used_mb", 0},
                    {"processes", 1}, {"uptime_seconds", 0}, {"bot_running", bot_running_.load()}});
  });
  svr.Post("/api/asr/transcribe", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string audio = trim(body.value("audio_path", ""));
    if (audio.empty()) { send_json(res, {{"ok", false}, {"message", "audio_path required"}}, 400); return; }
    std::string text = transcribe_audio(app_, audio);
    send_json(res, {{"ok", !text.empty()}, {"text", text}, {"audio_path", audio}});
  });

  // ----- Psycho / persona / curiosity -----
  svr.Get("/api/psycho/status", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    send_json(res, psycho_status(app_));
  });
  svr.Post("/api/psycho/record", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    try {
      send_json(res, psycho_record_action(app_, body.value("action_type", "view"),
                                          body.value("bvid", ""), body.value("title", ""),
                                          body.value("category", "")));
    } catch (const std::exception& e) {
      send_json(res, {{"ok", false}, {"message", e.what()}}, 500);
    }
  });
  svr.Get("/api/curiosity/status", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    send_json(res, curiosity_status(app_));
  });
  svr.Post("/api/curiosity/run", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    NetClient net(app_);
    AiClient ai(app_, net);
    send_json(res, curiosity_run(app_, net, ai, body.value("force", false)));
  });

  svr.Get("/api/owner-share/status", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json data = read_json(app_.paths.data_dir + "/owner_share_state.json", json::object());
    const json& cfg = app_.config.value("owner_share", json::object());
    std::string today = now_iso().substr(0, 10);
    long long count = data.value("last_date", "") == today ? data.value("today_count", 0) : 0;
    long long owner_uid = 0;
    if (cfg.contains("owner_bili_uid")) {
      if (cfg["owner_bili_uid"].is_number_integer()) owner_uid = cfg["owner_bili_uid"].get<long long>();
      else if (cfg["owner_bili_uid"].is_string()) {
        try { owner_uid = std::stoll(cfg["owner_bili_uid"].get<std::string>()); } catch (...) {}
      }
    }
    send_json(res, {{"enabled", cfg.value("enabled", false)}, {"configured", owner_uid > 0},
                    {"today_count", count}, {"daily_limit", cfg.value("daily_limit", 3)},
                    {"last_sent_at", data.value("last_sent_at", "")},
                    {"recent", data.value("items", json::array())}});
  });
  svr.Get("/api/up-follow/list", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json mem = read_json(app_.paths.user_data_dir + "/bot_memory.json", json::object());
    json ups = mem.value("known_ups", json::object());
    json items = json::array();
    for (auto& [name, info] : ups.items()) {
      if (!info.is_object() || !info.value("followed", false)) continue;
      items.push_back({{"name", name}, {"uid", info.value("uid", "")},
                       {"followed_at", info.value("followed_at", "")},
                       {"impressions", info.value("impressions", 0)},
                       {"avg_score", info.value("avg_score", 0.0)},
                       {"favorited", info.value("favorited", false)}});
    }
    send_json(res, {{"total", items.size()}, {"items", items}});
  });

  svr.Post("/api/up-follow/toggle", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    long long uid = body.value("uid", 0LL);
    bool follow = body.value("follow", true);
    if (uid <= 0) { send_json(res, {{"ok", false}, {"message", "uid required"}}, 400); return; }
    NetClient net(app_);
    std::string err = follow_user(net, app_, uid, follow);
    if (!err.empty()) { send_json(res, {{"ok", false}, {"message", err}}, 502); return; }
    json mem = read_json(app_.paths.user_data_dir + "/bot_memory.json", json::object());
    json ups = mem.value("known_ups", json::object());
    if (!ups.contains(std::to_string(uid))) ups[std::to_string(uid)] = json::object();
    ups[std::to_string(uid)]["followed"] = follow;
    ups[std::to_string(uid)]["followed_at"] = now_iso();
    mem["known_ups"] = ups;
    write_json(app_.paths.user_data_dir + "/bot_memory.json", mem);
    send_json(res, {{"ok", true}, {"uid", uid}, {"followed", follow}, {"message", follow ? "followed" : "unfollowed"}});
  });

  // ----- Custom knowledge base -----
  auto custom_dir = [this]() -> std::string { return app_.paths.knowledge_base_dir + "/custom"; };
  auto custom_list = [this, custom_dir]() -> json {
    std::error_code ec;
    json entries = json::array();
    if (!fs::exists(custom_dir(), ec)) return entries;
    for (const auto& e : fs::recursive_directory_iterator(custom_dir(), ec)) {
      if (ec || !e.is_regular_file() || e.path().extension() != ".md") continue;
      std::string rel = fs::relative(e.path(), custom_dir()).generic_string();
      std::string content = read_file(e.path().string());
      std::string title = e.path().stem().string();
      size_t nl = content.find('\n');
      if (nl != std::string::npos && starts_with(content, "# ")) title = trim(content.substr(2, nl - 2));
      std::smatch m;
      std::string bvid;
      std::string hay = title + " " + rel;
      if (std::regex_search(hay, m, std::regex("BV[0-9A-Za-z]{10}"))) bvid = m[0];
      entries.push_back({{"bvid", bvid}, {"title", title}, {"rel_path", rel},
                         {"content", content}, {"category", e.path().parent_path().filename().string()}});
    }
    return entries;
  };
  svr.Get("/api/kb/custom-list", [this, custom_list](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    send_json(res, {{"ok", true}, {"entries", custom_list()}});
  });
  svr.Post("/api/kb/custom-get", [this, custom_list](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string bvid = safe_bvid(body.value("bvid", ""));
    std::string title = trim(body.value("title", ""));
    for (const auto& e : custom_list()) {
      if (e.value("bvid", "") == bvid && (title.empty() || e.value("title", "") == title)) {
        send_json(res, {{"ok", true}, {"content", e.value("content", "")}, {"entry", e}});
        return;
      }
    }
    send_json(res, {{"ok", false}, {"message", "Not found"}}, 404);
  });
  svr.Post("/api/kb/custom-add", [this, custom_dir](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string title = trim(body.value("title", "untitled"));
    std::string content = body.value("content", "");
    if (content.empty()) {
      send_json(res, {{"ok", false}, {"message", "Content required"}}, 400);
      return;
    }
    std::string bvid = safe_bvid(body.value("bvid", ""));
    std::string fname = (bvid.empty() ? "custom" : bvid) + "-" + std::to_string(now_epoch()) + ".md";
    write_file(custom_dir() + "/" + fname, "# " + title + "\n\n" + content + "\n");
    send_json(res, {{"ok", true}, {"message", "Custom note added"}});
  });
  svr.Post("/api/kb/custom-update", [this, custom_list, custom_dir](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string bvid = safe_bvid(body.value("bvid", ""));
    std::string title = trim(body.value("title", ""));
    std::string content = body.value("content", "");
    for (const auto& e : custom_list()) {
      if (e.value("bvid", "") == bvid && e.value("title", "") == title) {
        write_file(custom_dir() + "/" + e.value("rel_path", ""), "# " + title + "\n\n" + content + "\n");
        send_json(res, {{"ok", true}, {"message", "Custom note updated"}});
        return;
      }
    }
    send_json(res, {{"ok", false}, {"message", "Not found"}}, 404);
  });
  svr.Post("/api/kb/custom-delete", [this, custom_list, custom_dir](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string bvid = safe_bvid(body.value("bvid", ""));
    std::string title = trim(body.value("title", ""));
    for (const auto& e : custom_list()) {
      if (e.value("bvid", "") == bvid && e.value("title", "") == title) {
        fs::remove(custom_dir() + "/" + e.value("rel_path", ""));
        send_json(res, {{"ok", true}, {"message", "Custom note deleted"}});
        return;
      }
    }
    send_json(res, {{"ok", false}, {"message", "Not found"}}, 404);
  });
  svr.Post("/api/kb/custom-search", [this, custom_list](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string q = lower(trim(body.value("q", qparam(req, "q", ""))));
    json entries = json::array();
    for (const auto& e : custom_list()) {
      if (q.empty() || lower(e.value("title", "") + " " + e.value("content", "")).find(q) != std::string::npos) {
        entries.push_back(e);
      }
    }
    send_json(res, {{"ok", true}, {"entries", entries}});
  });
  svr.Post("/api/kb/delete-file", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    if (body.value("confirmed", false) != true) {
      send_json(res, {{"ok", false}, {"message", "Confirm required"}}, 400);
      return;
    }
    std::string rel = trim(body.value("rel_path", ""));
    fs::path root = fs::absolute(app_.paths.knowledge_base_dir);
    fs::path target = fs::absolute(fs::path(app_.paths.knowledge_base_dir) / rel);
    if (target.string().rfind(root.string(), 0) != 0 || target.extension() != ".md" || !fs::exists(target)) {
      send_json(res, {{"ok", false}, {"message", "Note not found"}}, 404);
      return;
    }
    fs::remove(target);
    KnowledgeBase kb(app_.paths.knowledge_metadata_file, app_.paths.knowledge_base_dir);
    kb.load();
    kb.rebuild_index();
    send_json(res, {{"ok", true}, {"message", "Knowledge note deleted"}});
  });
  svr.Post("/api/kb/read-file", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    json rels = body.value("rel_paths", body.value("rel_path", json::array()));
    if (rels.is_string()) rels = json::array({rels});
    std::string combined;
    for (const auto& rp : rels) {
      std::string rel = rp.get<std::string>();
      fs::path root = fs::absolute(app_.paths.knowledge_base_dir);
      fs::path target = fs::absolute(fs::path(app_.paths.knowledge_base_dir) / rel);
      if (target.string().rfind(root.string(), 0) != 0 || !fs::exists(target)) {
        send_json(res, {{"ok", false}, {"message", "File not found: " + rel}}, 404);
        return;
      }
      combined += "=== " + target.filename().string() + " ===\n" + read_file(target.string()) + "\n\n";
    }
    send_json(res, {{"ok", true}, {"content", combined}, {"paths", rels}, {"total_size", combined.size()}, {"file_count", rels.size()}});
  });
  svr.Post("/api/kb/tutor-chat", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    json rel_paths = body.value("rel_paths", body.value("rel_path", json::array()));
    std::string message = trim(body.value("message", ""));
    std::string mode = body.value("mode", "chat");
    std::string context;
    if (rel_paths.is_string()) rel_paths = json::array({rel_paths});
    for (const auto& rp : rel_paths) context += read_file(app_.paths.knowledge_base_dir + "/" + rp.get<std::string>()) + "\n\n";
    if (mode == "rewrite") {
      std::string new_content = ai_chat_once(app_, "You rewrite notes preserving facts.", "Rewrite: " + message + "\n\n" + context);
      send_json(res, {{"ok", true}, {"mode", "rewrite"}, {"summary", "Rewritten"}, {"new_content", new_content}});
      return;
    }
    if (mode == "html") {
      std::string html = "<!doctype html><html><head><meta charset=\"utf-8\"><title>Knowledge</title></head><body><pre>" + context + "</pre></body></html>";
      send_json(res, {{"ok", true}, {"mode", "html"}, {"html", html}, {"style", body.value("style", "dark")}});
      return;
    }
    std::string reply = ai_chat_once(app_, "You answer from the supplied notes only.", "Question: " + message + "\n\nNotes:\n" + context);
    send_json(res, {{"ok", true}, {"mode", "chat"}, {"reply", reply}});
  });
  svr.Post("/api/kb/tutor-save", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string rel = trim(body.value("rel_path", ""));
    std::string content = body.value("content", "");
    if (rel.empty() || content.empty()) {
      send_json(res, {{"ok", false}, {"message", "Path and content required"}}, 400);
      return;
    }
    std::string path = app_.paths.knowledge_base_dir + "/" + rel;
    if (!fs::exists(path)) {
      send_json(res, {{"ok", false}, {"message", "Not found"}}, 404);
      return;
    }
    write_file(path, content);
    send_json(res, {{"ok", true}, {"message", "File saved"}});
  });
  svr.Post("/api/kb/tutor-html-save", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string html = body.value("html", "");
    if (html.empty()) {
      send_json(res, {{"ok", false}, {"message", "HTML required"}}, 400);
      return;
    }
    std::string title = trim(body.value("title", "knowledge"));
    std::string dir = app_.paths.knowledge_base_dir + "/.html_exports";
    std::string path = dir + "/" + title + "_" + timestamp_suffix() + ".html";
    write_file(path, html);
    send_json(res, {{"ok", true}, {"path", path}, {"message", "HTML saved"}});
  });

  auto queue_action = [this](const std::string& action, const json& payload) -> std::string {
    std::string id = action + "-" + std::to_string(now_epoch());
    json data = read_json(app_.paths.data_dir + "/web_action_queue.json", json::object());
    data[id] = {{"action", action}, {"payload", payload}, {"status", "queued"}, {"created_at", now_iso()}};
    write_json(app_.paths.data_dir + "/web_action_queue.json", data);
    json log = read_json(app_.paths.data_dir + "/web_action_log.json", json::object());
    if (!log.contains("items") || !log["items"].is_array()) log["items"] = json::array();
    log["items"].push_back({{"created_at", now_iso()}, {"action", action}, {"payload", payload}, {"executed", true}});
    if (log["items"].size() > 500) log["items"].erase(log["items"].begin(), log["items"].end() - 500);
    write_json(app_.paths.data_dir + "/web_action_log.json", log);
    return id;
  };

  // ----- Quiz / deep-dive agents / learning sessions -----
  auto learning_sessions = [this]() -> json {
    json data = read_json(app_.paths.data_dir + "/learning_sessions.json", json::object());
    return data.is_object() ? data : json::object();
  };
  auto session_save = [this, learning_sessions](const std::string& sid, const json& session) {
    json data = learning_sessions();
    data[sid] = session;
    write_json(app_.paths.data_dir + "/learning_sessions.json", data);
  };
  svr.Get("/api/learning-agent/sessions", [this, learning_sessions](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string type = qparam(req, "type", "");
    json data = learning_sessions();
    json out = json::array();
    for (auto& [sid, s] : data.items()) {
      if (!type.empty() && s.value("type", "") != type) continue;
      out.push_back({{"session_id", sid}, {"topic", s.value("topic", "")},
                     {"msg_count", s.value("messages", json::array()).size()}});
    }
    send_json(res, {{"ok", true}, {"sessions", out}});
  });
  svr.Get("/api/learning-agent/session/(.*)", [this, learning_sessions](
                                          const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string sid = percent_decode(req.matches[1]);
    send_json(res, {{"ok", true}, {"session", learning_sessions().value(sid, json::object())}});
  });
  svr.Delete("/api/learning-agent/session/(.*)", [this, learning_sessions](
                                             const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string sid = percent_decode(req.matches[1]);
    json data = learning_sessions();
    if (!data.contains(sid)) {
      send_json(res, {{"ok", false}, {"message", "Session not found"}}, 404);
      return;
    }
    data.erase(sid);
    write_json(app_.paths.data_dir + "/learning_sessions.json", data);
    send_json(res, {{"ok", true}, {"message", "Session deleted"}});
  });
  auto agent_chat = [this](const httplib::Request& req, httplib::Response& res,
                          const std::string& type, const std::string&) {
    json body = parse_body(req);
    std::string sid = trim(body.value("session_id", ""));
    std::string topic = trim(body.value("topic", body.value("keyword", "untitled")));
    std::string user_msg = trim(body.value("message", body.value("question", "")));
    if (type == "deep_dive" && user_msg.empty()) user_msg = "Research topic: " + topic;
    NetClient net(app_);
    AiClient ai(app_, net);
    send_json(res, run_learning_agent(app_, net, ai, type, topic, user_msg, sid));
  };
  svr.Post("/api/action/deep-dive-agent", [this, agent_chat](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    agent_chat(req, res, "deep_dive", "You are a deep research agent. Answer with sourced reasoning.");
  });
  svr.Post("/api/action/quiz-agent", [this, agent_chat](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    agent_chat(req, res, "quiz", "You are a quiz tutor. Ask questions and check answers.");
  });
  svr.Post("/api/action/deep-dive-multi", [this, queue_action](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string topic = trim(body.value("topic", body.value("keyword", "")));
    if (topic.empty()) {
      send_json(res, {{"ok", false}, {"message", "Topic required"}}, 400);
      return;
    }
    std::string id = queue_action("deep_dive_multi", body);
    send_json(res, {{"ok", true}, {"task_id", id}, {"message", "Multi-agent deep dive queued"}});
  });
  svr.Post("/api/action/quiz", [this, queue_action](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string id = queue_action("quiz", body);
    send_json(res, {{"ok", true}, {"task_id", id}, {"message", "Quiz queued"}});
  });

  // ----- Up search / videos / learn -----
  svr.Post("/api/action/up-search", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string query = trim(body.value("query", ""));
    if (query.empty()) {
      send_json(res, {{"ok", false}, {"message", "Query required"}}, 400);
      return;
    }
    NetClient net(app_);
    NetResponse resp = net.get("https://api.bilibili.com/x/web-interface/search/type",
                                {{"search_type", "bili_user"}, {"keyword", query}, {"page", "1"}});
    json users = json::array();
    try {
      json j = json::parse(resp.body);
      for (const auto& u : j["data"]["result"]) {
        users.push_back({{"mid", u.value("mid", 0)}, {"uname", u.value("uname", "")},
                         {"usign", u.value("usign", "")}, {"fans", u.value("fans", 0)}});
      }
    } catch (...) {
    }
    send_json(res, {{"ok", true}, {"users", users}});
  });
  svr.Post("/api/action/up-videos", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    long long uid = body.value("uid", 0);
    int limit = body.value("limit", 10);
    if (uid <= 0) {
      send_json(res, {{"ok", false}, {"message", "UID required"}}, 400);
      return;
    }
    NetClient net(app_);
    std::string err;
    auto videos = user_videos(net, uid, err);
    json items = json::array();
    for (size_t i = 0; i < videos.size() && (int)i < limit; i++) {
      items.push_back({{"aid", videos[i].first}, {"bvid", videos[i].second}});
    }
    send_json(res, {{"ok", true}, {"videos", items}, {"total", items.size()}});
  });
  svr.Post("/api/action/up-learn", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    json bvids = body.value("bvids", json::array());
    std::vector<std::string> cleaned;
    for (const auto& v : bvids) {
      std::string b = safe_bvid(v.get<std::string>());
      if (!b.empty()) cleaned.push_back(b);
    }
    if (cleaned.empty()) {
      send_json(res, {{"ok", false}, {"message", "No valid BV"}}, 400);
      return;
    }
    NetClient net(app_);
    AiClient ai(app_, net);
    int done = 0, failed = 0;
    for (const auto& bvid : cleaned) {
      VideoAnalysis va;
      std::string err;
      if (analyze_video(app_, net, ai, bvid, va, err)) {
        KnowledgeBase kb(app_.paths.knowledge_metadata_file, app_.paths.knowledge_base_dir);
        kb.load();
        kb.add_note(detect_category(va.info.title, va.ai_summary), va.info.title, bvid, va.ai_summary);
        kb.add_note(detect_category(va.info.title, va.ai_summary), va.info.title, bvid, va.ai_summary, app_.config);
        done++;
      } else {
        failed++;
      }
    }
    send_json(res, {{"ok", true}, {"done", done}, {"failed", failed}, {"message", "UP learning finished"}});
  });
  svr.Post("/api/action/video2web", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string bvid = safe_bvid(body.value("bvid", ""));
    if (bvid.empty()) {
      send_json(res, {{"ok", false}, {"message", "BV required"}}, 400);
      return;
    }
    NetClient net(app_);
    AiClient ai(app_, net);
    VideoAnalysis va;
    std::string err;
    if (!analyze_video(app_, net, ai, bvid, va, err)) {
      send_json(res, {{"ok", false}, {"message", err}}, 502);
      return;
    }
    std::string html = "<!doctype html><html><head><meta charset=\"utf-8\"><title>" + va.info.title + "</title></head><body><h1>" + va.info.title + "</h1><p>" + va.ai_summary + "</p></body></html>";
    std::string dir = app_.paths.data_dir + "/html_exports";
    std::string path = dir + "/" + bvid + "_" + timestamp_suffix() + ".html";
    write_file(path, html);
    send_json(res, {{"ok", true}, {"html", html}, {"path", path}, {"message", "HTML generated"}});
  });

  // ----- Flags / tasks / action endpoints -----
  svr.Get("/api/action/flags", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json flags = app_.config.value("feature_flags", json::object());
    send_json(res, {{"ok", true}, {"flags", flags}});
  });
  svr.Post("/api/action/toggle-flag", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string key = body.value("key", "");
    if (key.empty()) {
      send_json(res, {{"ok", false}, {"message", "Flag key required"}}, 400);
      return;
    }
    json& flags = app_.config["feature_flags"];
    flags[key] = flags.value(key, false) ? false : true;
    save_config_file(app_);
    send_json(res, {{"ok", true}, {"flags", flags}, {"key", key}});
  });
  svr.Get("/api/action/task", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string id = qparam(req, "id", "");
    json data = read_json(app_.paths.data_dir + "/web_action_queue.json", json::object());
    send_json(res, {{"ok", true}, {"task", data.value(id, json::object())}, {"id", id}});
  });
  svr.Post("/api/action/agent-skill", [this, queue_action](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string goal = trim(body.value("goal", ""));
    std::string result = goal.empty() ? "No goal provided" : ai_chat_once(app_, "You are an autonomous agent.", goal);
    std::string id = queue_action("agent_skill", {{"goal", goal}, {"result", result}});
    send_json(res, {{"ok", true}, {"task_id", id}, {"result", result}, {"message", "Agent skill executed"}});
  });
  svr.Post("/api/action/kb-organize", [this, queue_action](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    KnowledgeBase kb(app_.paths.knowledge_metadata_file, app_.paths.knowledge_base_dir);
    kb.load();
    kb.rebuild_index();
    std::string id = queue_action("kb_organize", json::object());
    send_json(res, {{"ok", true}, {"task_id", id}, {"message", "Knowledge base organized"}});
  });
  svr.Post("/api/action/kb-revisit", [this, queue_action](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string id = queue_action("kb_revisit", json::object());
    send_json(res, {{"ok", true}, {"task_id", id}, {"message", "Knowledge revisit queued"}});
  });
  svr.Post("/api/action/send-danmaku", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string bvid = safe_bvid(body.value("bvid", ""));
    std::string text = trim(body.value("text", ""));
    if (bvid.empty() || text.empty()) {
      send_json(res, {{"ok", false}, {"message", "BV and text required"}}, 400);
      return;
    }
    NetClient net(app_);
    std::string err;
    VideoInfo info = video_info(net, bvid, 0, err);
    if (info.cid == 0) {
      send_json(res, {{"ok", false}, {"message", err.empty() ? "Video not found" : err}}, 502);
      return;
    }
    NetResponse resp = net.post("https://api.bilibili.com/x/v2/dm/post",
                                {{"type", "1"}, {"oid", std::to_string(info.cid)},
                                 {"msg", text}, {"progress", "3000"}, {"color", "16777215"},
                                 {"fontsize", "25"}, {"pool", "0"}, {"mode", "1"},
                                 {"rnd", std::to_string(now_epoch())}, {"csrf", cookie_value(app_, "bili_jct")},
                                 {"csrf_token", cookie_value(app_, "bili_jct")}});
    try {
      json j = json::parse(resp.body);
      if (j.value("code", -1) == 0) {
        send_json(res, {{"ok", true}, {"message", "Danmaku sent"}});
        return;
      }
      send_json(res, {{"ok", false}, {"message", j.value("message", "send failed")}}, 502);
      return;
    } catch (...) {
      send_json(res, {{"ok", false}, {"message", "send failed"}}, 502);
    }
  });
  svr.Post("/api/platform/probe", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string url = trim(body.value("url", ""));
    std::string platform = lower(body.value("platform", "auto"));
    NetClient net(app_);
    NetResponse resp = net.raw_get(url.empty() ? "https://www.bilibili.com" : url);
    send_json(res, {{"ok", resp.http_code >= 200 && resp.http_code < 400}, {"platform", platform},
                    {"http_code", resp.http_code}, {"message", resp.http_code ? "reachable" : "unreachable"}});
  });

  // ----- Reviews -----
  auto review_store_path = [this]() -> std::string {
    std::string approval = app_.paths.data_dir + "/approval_review_inbox.json";
    std::error_code ec;
    if (fs::exists(approval, ec)) return approval;
    std::string legacy1 = app_.paths.data_dir + "/like_review_inbox.json";
    std::string legacy2 = app_.paths.data_dir + "/action_review_inbox.json";
    json merged = json::object();
    merged["items"] = json::array();
    for (const auto& p : {legacy1, legacy2}) {
      if (!fs::exists(p, ec)) continue;
      json old = read_json(p, json::object());
      json items = old.value("items", old.is_array() ? old : json::array());
      if (items.is_array()) {
        for (auto& it : items) {
          if (it.is_object()) merged["items"].push_back(it);
        }
      }
      fs::rename(p, p + ".migrated", ec);
    }
    if (!merged["items"].empty()) write_json(approval, merged);
    return approval;
  };
  auto review_inbox = [this, review_store_path]() -> json {
    json data = read_json(review_store_path(), json::object());
    if (!data.contains("items") || !data["items"].is_array()) data["items"] = json::array();
    return data;
  };
  svr.Get("/api/reviews", [this, review_inbox](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string status = qparam(req, "status", "all");
    json data = review_inbox();
    json items = json::array();
    int pending = 0;
    for (const auto& item : data["items"]) {
      std::string st = item.value("status", "pending");
      if (status != "all" && st != status) continue;
      if (st == "pending") pending++;
      items.push_back(item);
    }
    send_json(res, {{"items", items}, {"pending", pending}});
  });
  svr.Post("/api/reviews/propose", [this, review_inbox, review_store_path](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string action_type = body.value("action_type", "video_like");
    std::string title = body.value("title", "");
    std::string summary = body.value("summary", "");
    json payload = body.value("payload", json::object());
    std::string dedupe = body.value("dedupe_key", action_type + ":" + payload.dump());
    json data = review_inbox();
    for (const auto& item : data["items"]) {
      if (item.value("dedupe_key", "") == dedupe && item.value("status", "") == "pending") {
        send_json(res, {{"ok", false}, {"message", "already pending"}});
        return;
      }
    }
    json row = {{"id", std::to_string(now_epoch()) + "-" + std::to_string(rand())},
                {"action_type", action_type}, {"action_label", action_type},
                {"scope", "platform"}, {"title", title.substr(0, 180)},
                {"summary", summary.substr(0, 500)}, {"payload", payload},
                {"dedupe_key", dedupe}, {"status", "pending"},
                {"created_at", now_iso()}};
    data["items"].push_back(row);
    write_json(review_store_path(), data);
    send_json(res, {{"ok", true}, {"item", row}});
  });
  svr.Get("/api/reviews/audit/read", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string raw = read_file(app_.paths.data_dir + "/approval_review_audit.jsonl");
    json lines = json::array();
    size_t pos = 0;
    while (pos < raw.size()) {
      size_t nl = raw.find('\n', pos);
      std::string line = raw.substr(pos, nl == std::string::npos ? std::string::npos : nl - pos);
      try { lines.push_back(json::parse(line)); } catch (...) {}
      if (nl == std::string::npos) break;
      pos = nl + 1;
    }
    send_json(res, {{"ok", true}, {"items", lines}});
  });

  svr.Get("/api/reviews/audit", [this, review_inbox](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    send_json(res, {{"items", review_inbox()["items"]}});
  });
  svr.Post("/api/reviews/audit/clear", [this, review_store_path](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    write_json(review_store_path(), json::object());
    send_json(res, {{"ok", true}, {"message", "Audit cleared"}});
  });
  svr.Post("/api/reviews/decision", [this, review_inbox, review_store_path](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    json ids = body.value("ids", json::array());
    std::string decision = body.value("decision", "ignored");
    json data = review_inbox();
    json state_path = app_.paths.data_dir + "/action_execution_state.json";
    json state = read_json(state_path, json::object());
    json results = json::array();
    int succeeded = 0;
    for (auto& item : data["items"]) {
      bool matched = false;
      for (const auto& id : ids) {
        if (item.value("id", "") == id.get<std::string>()) matched = true;
      }
      if (!matched) continue;
      item["status"] = decision;
      item["decided_at"] = now_iso();
      json result = {{"id", item.value("id", "")}, {"ok", true},
                     {"action_label", item.value("action", "")},
                     {"title", item.value("title", item.value("bvid", ""))}};
      if (decision == "approved") {
        NetClient net(app_);
        std::string csrf = cookie_value(app_, "bili_jct");
        std::string action = lower(item.value("action", ""));
        json payload = item.value("payload", json::object());
        std::string bvid = safe_bvid(payload.value("bvid", payload.value("video", "")));
        long long aid = payload.value("aid", 0);
        if (aid == 0 && !bvid.empty()) {
          std::string err;
          VideoInfo info = video_info(net, bvid, 0, err);
          aid = info.aid;
        }
        std::string exec_key = item.value("id", "") + ":" + action + ":" + (bvid.empty() ? std::to_string(aid) : bvid);
        json& st = state[exec_key];
        if (!st.is_object()) st = json::object();
        if (st.value("ok", false)) {
          result["message"] = "already executed";
          item["execution"] = {{"ok", true}, {"message", "already executed"}, {"at", now_iso()}};
        } else if (st.value("attempts", 0) >= 3) {
          result["ok"] = false;
          result["message"] = "retries exhausted";
          item["execution"] = {{"ok", false}, {"message", "retries exhausted"}, {"at", now_iso()}};
        } else {
          std::string exec_err;
          if (action.find("like") != std::string::npos) {
            if (aid != 0 && !bvid.empty()) exec_err = like_video(net, csrf, aid, bvid);
            else exec_err = "missing video";
          } else if (action.find("coin") != std::string::npos) {
            if (aid != 0 && !bvid.empty()) exec_err = pay_coin(net, csrf, aid, bvid);
            else exec_err = "missing video";
          } else if (action.find("favorite") != std::string::npos || action.find("fav") != std::string::npos) {
            std::string ferr;
            long long folder = first_favorite_folder(net, aid, app_.uid, ferr);
            if (folder == 0) exec_err = ferr.empty() ? "no favorite folder" : ferr;
            else exec_err = add_favorite(net, csrf, aid, folder);
          } else if (action.find("comment") != std::string::npos || action.find("reply") != std::string::npos) {
            std::string text = payload.value("text", payload.value("message", ""));
            long long oid = payload.value("oid", aid);
            long long root = payload.value("root", 0);
            long long parent = payload.value("parent", 0);
            if (oid == 0 || text.empty()) exec_err = "missing comment data";
            else exec_err = send_comment(net, csrf, text, oid, root, parent);
          } else if (action.find("danmaku") != std::string::npos) {
            std::string text = payload.value("text", "");
            if (text.empty()) exec_err = "missing danmaku text";
            else {
              VideoInfo info = video_info(net, bvid, aid, exec_err);
              if (info.cid != 0) {
                NetResponse resp = net.post("https://api.bilibili.com/x/v2/dm/post",
                    {{"type", "1"}, {"oid", std::to_string(info.cid)}, {"msg", text},
                     {"progress", "3000"}, {"color", "16777215"}, {"fontsize", "25"},
                     {"pool", "0"}, {"mode", "1"}, {"rnd", std::to_string(now_epoch())}, {"csrf", csrf}});
                try {
                  json j = json::parse(resp.body);
                  exec_err = j.value("code", -1) == 0 ? "" : j.value("message", "danmaku failed");
                } catch (...) { exec_err = "danmaku failed"; }
              }
            }
          } else if (action.find("private") != std::string::npos) {
            long long receiver = payload.value("receiver_uid", payload.value("uid", 0));
            std::string text = payload.value("text", payload.value("message", ""));
            if (receiver <= 0 || text.empty()) exec_err = "missing private message data";
            else exec_err = send_private_message(net, app_, receiver, text);
          } else {
            exec_err = "unsupported action: " + action;
          }
          result["ok"] = exec_err.empty();
          result["message"] = exec_err.empty() ? "executed" : exec_err;
          item["execution"] = {{"ok", exec_err.empty()}, {"message", exec_err}, {"at", now_iso()}};
          st["ok"] = exec_err.empty();
          st["attempts"] = st.value("attempts", 0);
          st["attempts"] = st["attempts"].get<long long>() + 1;
          st["last_error"] = exec_err;
          st["last_at"] = now_iso();
          if (!exec_err.empty()) st["retry_at"] = now_iso();
        }
      } else {
        item["execution"] = {{"ok", true}, {"message", "not executed"}, {"at", now_iso()}};
      }
      if (result.value("ok", false)) succeeded++;
      results.push_back(result);
    }
    write_json(state_path, state);
    write_json(review_store_path(), data);
    {
      std::string audit_path = app_.paths.data_dir + "/approval_review_audit.jsonl";
      std::ofstream audit_out(audit_path, std::ios::binary | std::ios::app);
      if (audit_out) {
        for (const auto& r : results) {
          audit_out << json({{"time", now_iso()}, {"event", "decided"},
                             {"item_id", r.value("id", "")}, {"status", decision},
                             {"title", r.value("title", "")}}).dump() << "\n";
        }
      }
    }
    send_json(res, {{"ok", true}, {"processed", (int)ids.size()}, {"succeeded", succeeded},
                    {"results", results}, {"message", "Review decisions processed"}});
  });
  svr.Get("/api/reviews/settings", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json s = app_.config.value("reviews", json::object());
    send_json(res, {{"enabled", s.value("enabled", true)}, {"desktop_notification", s.value("desktop_notification", true)},
                    {"action_types", s.value("action_types", json::object())}});
  });
  svr.Post("/api/reviews/settings", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    json s = app_.config.value("reviews", json::object());
    for (const char* key : {"enabled", "desktop_notification"}) {
      if (body.contains(key)) s[key] = body[key];
    }
    if (body.contains("action_types")) s["action_types"] = body["action_types"];
    app_.config["reviews"] = s;
    save_config_file(app_);
    send_json(res, {{"ok", true}, {"message", "Review settings saved"}});
  });

  // ----- Mindmaps -----
  auto mindmap_list = [this]() -> json {
    json maps = json::array();
    std::error_code ec;
    std::string dir = app_.paths.user_data_dir + "/Mindmaps";
    if (!fs::exists(dir, ec)) return maps;
    std::vector<fs::path> files;
    for (const auto& e : fs::recursive_directory_iterator(dir, ec)) {
      if (ec) break;
      if (e.is_regular_file() && e.path().extension() == ".html") files.push_back(e.path());
    }
    std::sort(files.begin(), files.end(), [](const fs::path& a, const fs::path& b) {
      return fs::last_write_time(a) > fs::last_write_time(b);
    });
    for (const auto& f : files) {
      std::string rel = fs::relative(f, dir).generic_string();
      maps.push_back({{"name", f.filename().string()}, {"path", rel}, {"url", "/maps/" + rel}});
    }
    return maps;
  };
  svr.Get("/api/mindmaps", [this, mindmap_list](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    send_json(res, {{"ok", true}, {"maps", mindmap_list()}});
  });
  svr.Post("/api/mindmaps/delete", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    if (body.value("confirmed", false) != true) {
      send_json(res, {{"ok", false}, {"message", "Confirm required"}}, 400);
      return;
    }
    std::string rel = trim(body.value("path", ""));
    std::string dir = app_.paths.user_data_dir + "/Mindmaps";
    fs::path root = fs::absolute(dir);
    fs::path target = fs::absolute(fs::path(dir) / rel);
    if (target.string().rfind(root.string(), 0) != 0 || !fs::exists(target)) {
      send_json(res, {{"ok", false}, {"message", "Not found"}}, 404);
      return;
    }
    fs::remove(target);
    send_json(res, {{"ok", true}, {"message", "Mindmap deleted"}});
  });

  // ----- Interests -----
  auto interest_engine = [this]() -> json {
    json data = read_json(app_.paths.data_dir + "/interest_engine.json", json::object());
    return data.is_object() ? data : json::object();
  };
  auto interest_payload = [this, interest_engine]() -> json {
    json data = interest_engine();
    json interests = data.value("interests", json::array());
    json entries = json::array();
    for (const auto& item : interests) {
      if (item.is_object()) {
        std::string keyword = item.value("keyword", "");
        if (keyword.empty()) continue;
        entries.push_back({{"keyword", keyword}, {"weight", item.value("weight", "medium")},
                           {"synonyms", item.value("synonyms", json::array())},
                           {"auto_suggested", item.value("auto_suggested", false)}});
      } else if (item.is_string()) {
        entries.push_back({{"keyword", item.get<std::string>()}, {"weight", "medium"},
                           {"synonyms", json::array()}, {"auto_suggested", false}});
      }
    }
    json settings = data.value("settings", json::object());
    json scoring = settings.value("scoring", json::object());
    return json({{"ok", true}, {"interests", entries},
                 {"negative_keywords", data.value("negative_keywords", json::array())},
                 {"settings", {{"proxy_mode", settings.value("proxy_mode", "smart")},
                               {"serendipity_rate", settings.value("serendipity_rate", 0.0)},
                               {"auto_sync_psycho", settings.value("auto_sync_psycho", true)},
                               {"use_synonyms", settings.value("use_synonyms", true)},
                               {"ai_suggest", settings.value("ai_suggest", true)},
                               {"ai_suggest_interval", settings.value("ai_suggest_interval", 20)},
                               {"scoring_enabled", scoring.value("enabled", true)},
                               {"dynamic_threshold", scoring.value("dynamic_threshold", true)},
                               {"threshold_base", scoring.value("threshold_base", 6.0)}}},
                 {"stats", {{"count", entries.size()}}},
                 {"storage_path", app_.paths.data_dir + "/interest_engine.json"}});
  };
  svr.Get("/api/interests", [this, interest_payload](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json p = interest_payload();
    json keywords = json::array();
    for (const auto& i : p["interests"]) keywords.push_back(i["keyword"]);
    send_json(res, {{"ok", true}, {"interests", keywords}, {"count", keywords.size()}});
  });
  svr.Post("/api/interests", [this, interest_engine](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    json values = body.value("interests", json::array());
    json terms = json::array();
    std::set<std::string> seen;
    for (const auto& v : values) {
      std::string term = lower(trim(v.is_string() ? v.get<std::string>() : ""));
      if (term.size() > 80) term = term.substr(0, 80);
      if (!term.empty() && seen.insert(term).second) terms.push_back(term);
    }
    json data = interest_engine();
    data["interests"] = terms;
    write_json(app_.paths.data_dir + "/interest_engine.json", data);
    send_json(res, {{"ok", true}, {"interests", terms}, {"count", terms.size()}, {"message", "Interests saved"}});
  });
  svr.Get("/api/interest-engine", [this, interest_payload](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    send_json(res, interest_payload());
  });
  auto interest_upsert = [this, interest_engine](const json& body) -> json {
    std::string keyword = lower(trim(body.value("keyword", "")));
    if (keyword.empty()) return {{"ok", false}, {"message", "Keyword required"}};
    json data = interest_engine();
    json interests = data.value("interests", json::array());
    bool found = false;
    for (auto& item : interests) {
      if (item.is_object() && lower(item.value("keyword", "")) == keyword) {
        item["weight"] = body.value("weight", "medium");
        item["synonyms"] = body.value("synonyms", json::array());
        if (body.contains("auto_suggested")) item["auto_suggested"] = body["auto_suggested"];
        found = true;
        break;
      }
    }
    if (!found) {
      interests.push_back({{"keyword", keyword}, {"weight", body.value("weight", "medium")},
                           {"synonyms", body.value("synonyms", json::array())},
                           {"auto_suggested", body.value("auto_suggested", false)}});
    }
    data["interests"] = interests;
    write_json(app_.paths.data_dir + "/interest_engine.json", data);
    return {{"ok", true}, {"message", "Interest saved"}};
  };
  svr.Post("/api/interest-engine", [this, interest_engine, interest_payload](
                                        const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    json data = interest_engine();
    json settings = data.value("settings", json::object());
    if (body.contains("proxy_mode")) settings["proxy_mode"] = body["proxy_mode"];
    if (body.contains("serendipity_rate")) settings["serendipity_rate"] = body["serendipity_rate"];
    for (const char* key : {"auto_sync_psycho", "use_synonyms", "ai_suggest"}) {
      if (body.contains(key)) settings[key] = body[key];
    }
    if (body.contains("ai_suggest_interval")) settings["ai_suggest_interval"] = body["ai_suggest_interval"];
    json scoring = settings.value("scoring", json::object());
    if (body.contains("scoring_enabled")) scoring["enabled"] = body["scoring_enabled"];
    if (body.contains("dynamic_threshold")) scoring["dynamic_threshold"] = body["dynamic_threshold"];
    if (body.contains("threshold_base")) scoring["threshold_base"] = body["threshold_base"];
    settings["scoring"] = scoring;
    data["settings"] = settings;
    write_json(app_.paths.data_dir + "/interest_engine.json", data);
    send_json(res, interest_payload());
  });
  svr.Post("/api/interest-engine/interests", [this, interest_payload, interest_upsert](
                                             const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json r = interest_upsert(parse_body(req));
    if (!r.value("ok", false)) {
      send_json(res, r, 400);
      return;
    }
    json payload = interest_payload();
    payload["message"] = r["message"];
    send_json(res, payload);
  });
  svr.Delete("/api/interest-engine/interests/(.*)", [this, interest_engine, interest_payload](
                                                const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string keyword = lower(percent_decode(req.matches[1]));
    json data = interest_engine();
    json kept = json::array();
    bool removed = false;
    for (auto& item : data.value("interests", json::array())) {
      std::string k = item.is_object() ? lower(item.value("keyword", "")) : lower(item.get<std::string>());
      if (k == keyword) removed = true;
      else kept.push_back(item);
    }
    if (!removed) {
      send_json(res, {{"ok", false}, {"message", "Not found"}}, 404);
      return;
    }
    data["interests"] = kept;
    write_json(app_.paths.data_dir + "/interest_engine.json", data);
    send_json(res, interest_payload());
  });
  svr.Post("/api/interest-engine/exclusions", [this, interest_engine](
                                             const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string keyword = lower(trim(body.value("keyword", "")));
    json data = interest_engine();
    json ex = data.value("negative_keywords", json::array());
    ex.push_back(keyword);
    data["negative_keywords"] = ex;
    write_json(app_.paths.data_dir + "/interest_engine.json", data);
    send_json(res, {{"ok", true}, {"message", "Exclusion added"}});
  });
  svr.Delete("/api/interest-engine/exclusions/(.*)", [this, interest_engine](
                                                  const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string keyword = lower(percent_decode(req.matches[1]));
    json data = interest_engine();
    json kept = json::array();
    for (auto& item : data.value("negative_keywords", json::array())) {
      if (lower(item.get<std::string>()) != keyword) kept.push_back(item);
    }
    data["negative_keywords"] = kept;
    write_json(app_.paths.data_dir + "/interest_engine.json", data);
    send_json(res, {{"ok", true}, {"message", "Exclusion removed"}});
  });
  // ----- Python parity routes -----
  svr.Get("/api/deploy_status", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    send_json(res, {{"ok", true}, {"backend", "cpp"}, {"status", "running"}});
  });
  svr.Get("/app-icon", [](const httplib::Request&, httplib::Response& res) {
    res.status = 404;
    res.set_content("", "image/png");
  });
  svr.Get("/assets/js/(.*)", [](const httplib::Request& req, httplib::Response& res) {
    res.status = 404;
    res.set_content("", "text/plain");
  });
  svr.Get("/api/interests-legacy", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json data = read_json(app_.paths.data_dir + "/interest_engine.json", json::object());
    json terms = data.value("interests", json::array());
    json out = json::array();
    for (const auto& item : terms) {
      if (item.is_string()) out.push_back(item);
      else if (item.is_object()) out.push_back(item.value("keyword", ""));
    }
    send_json(res, {{"ok", true}, {"interests", out}, {"count", out.size()}});
  });
  svr.Post("/api/interests-legacy", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    json values = body.value("interests", json::array());
    json terms = json::array();
    std::set<std::string> seen;
    for (const auto& v : values) {
      std::string t = lower(trim(v.is_string() ? v.get<std::string>() : ""));
      if (!t.empty() && seen.insert(t).second) terms.push_back(t);
    }
    json data = read_json(app_.paths.data_dir + "/interest_engine.json", json::object());
    data["interests"] = terms;
    write_json(app_.paths.data_dir + "/interest_engine.json", data);
    send_json(res, {{"ok", true}, {"interests", terms}, {"count", terms.size()}, {"message", "Interests saved"}});
  });
  svr.Get("/api/behavior/prompt-injection", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json pi = app_.config.value("prompt_injection", json::object());
    send_json(res, {{"ok", true}, {"enabled", pi.value("enabled", true)},
                    {"custom_terms", pi.value("custom_terms", json::array())}});
  });
  svr.Post("/api/behavior/prompt-injection", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    json pi = app_.config.value("prompt_injection", json::object());
    if (body.contains("enabled")) pi["enabled"] = body["enabled"];
    if (body.contains("custom_terms")) pi["custom_terms"] = body["custom_terms"];
    app_.config["prompt_injection"] = pi;
    save_config_file(app_);
    send_json(res, {{"ok", true}, {"message", "Prompt injection settings saved"}});
  });
  svr.Get("/api/backup/options", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json groups = json::array();
    for (const char* id : {"settings", "memory", "knowledge", "exports"}) {
      groups.push_back({{"id", id}, {"label", id}, {"description", "Local data group"},
                        {"default", true}, {"files", 0}, {"bytes", 0}});
    }
    send_json(res, {{"ok", true}, {"groups", groups}});
  });
  svr.Post("/api/owner-share/test", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string bvid = safe_bvid(body.value("video", body.value("bvid", "")));
    if (bvid.empty()) {
      send_json(res, {{"ok", false}, {"message", "Invalid BV"}}, 400);
      return;
    }
    long long owner_uid = 0;
    const json& os_cfg = app_.config.value("owner_share", json::object());
    if (os_cfg.contains("owner_bili_uid")) {
      if (os_cfg["owner_bili_uid"].is_number_integer()) owner_uid = os_cfg["owner_bili_uid"].get<long long>();
      else if (os_cfg["owner_bili_uid"].is_string()) {
        try { owner_uid = std::stoll(os_cfg["owner_bili_uid"].get<std::string>()); } catch (...) {}
      }
    }
    if (owner_uid <= 0) {
      send_json(res, {{"ok", false}, {"message", "Owner Bili UID not configured"}}, 400);
      return;
    }
    NetClient net(app_);
    std::string err;
    VideoInfo info = video_info(net, bvid, 0, err);
    if (info.bvid.empty()) {
      send_json(res, {{"ok", false}, {"message", err.empty() ? "Video not found" : err}}, 502);
      return;
    }
    std::string message = info.title + "\nhttps://www.bilibili.com/video/" + bvid;
    std::string serr = send_private_message(net, app_, owner_uid, message);
    if (!serr.empty()) {
      send_json(res, {{"ok", false}, {"sent", false}, {"bvid", bvid}, {"message", serr}}, 502);
      return;
    }
    json st = read_json(app_.paths.data_dir + "/owner_share_state.json", json::object());
    st["last_sent_at"] = now_iso();
    long long today_count = 0;
    if (st.contains("today_count") && st["today_count"].is_number_integer()) today_count = st["today_count"].get<long long>();
    if (st.value("last_date", "") != now_iso().substr(0, 10)) {
      today_count = 0;
      st["last_date"] = now_iso().substr(0, 10);
    }
    today_count += 1;
    st["today_count"] = today_count;
    write_json(app_.paths.data_dir + "/owner_share_state.json", st);
    send_json(res, {{"ok", true}, {"sent", true}, {"bvid", bvid}, {"title", info.title},
                    {"message", "Owner share sent"}});
  });
  svr.Get("/api/network/proxy", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json proxy = app_.config.value("network", json::object()).value("proxy", json::object());
    send_json(res, {{"ok", true}, {"enabled", proxy.value("enabled", false)},
                    {"url", proxy.value("url", "")}});
  });
  svr.Post("/api/network/proxy", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    json proxy = app_.config.value("network", json::object()).value("proxy", json::object());
    if (body.contains("enabled")) proxy["enabled"] = body["enabled"];
    if (body.contains("url")) proxy["url"] = body["url"];
    app_.config["network"]["proxy"] = proxy;
    save_config_file(app_);
    send_json(res, {{"ok", true}, {"message", "Proxy settings saved"}});
  });
  svr.Post("/api/network/proxy/test", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    NetClient net(app_);
    NetResponse r = net.raw_get("https://www.bilibili.com");
    send_json(res, {{"ok", r.http_code >= 200 && r.http_code < 400}, {"http_code", r.http_code}});
  });
  svr.Get("/api/like-review", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json data = read_json(app_.paths.data_dir + "/action_review_inbox.json", json::object());
    send_json(res, {{"items", data.value("items", json::array())}});
  });
  svr.Post("/api/like-review/(.*)/(.*)", [this, review_store_path](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string id = percent_decode(req.matches[1]);
    std::string decision = percent_decode(req.matches[2]);
    json data = read_json(app_.paths.data_dir + "/action_review_inbox.json", json::object());
    for (auto& item : data["items"]) {
      if (item.value("id", "") == id) {
        item["status"] = decision;
        item["decided_at"] = now_iso();
        write_json(review_store_path(), data);
        send_json(res, {{"ok", true}, {"message", "Decision saved"}});
        return;
      }
    }
    send_json(res, {{"ok", false}, {"message", "Not found"}}, 404);
  });
  auto standby_state = [this]() -> json {
    json data = read_json(app_.paths.data_dir + "/standby_stats.json", json::object());
    if (!data.is_object()) data = json::object();
    return data;
  };
  svr.Get("/api/standby/status", [this, standby_state](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json st = standby_state();
    send_json(res, {{"running", st.value("running", false)}, {"started_at", st.value("started_at", "")}});
  });
  svr.Post("/api/standby/start", [this, standby_state](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    if (!standby_running_.exchange(true)) {
      if (standby_thread_.joinable()) standby_thread_.detach();
      standby_thread_ = std::thread([this] { standby_loop(); });
    }
    json st = standby_state();
    st["running"] = true;
    st["started_at"] = now_iso();
    write_json(app_.paths.data_dir + "/standby_stats.json", st);
    send_json(res, {{"ok", true}, {"message", "Standby started"}});
  });
  svr.Post("/api/standby/stop", [this, standby_state](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    standby_running_.store(false);
    if (standby_thread_.joinable()) standby_thread_.detach();
    json st = standby_state();
    st["running"] = false;
    st["stopped_at"] = now_iso();
    write_json(app_.paths.data_dir + "/standby_stats.json", st);
    send_json(res, {{"ok", true}, {"message", "Standby stopped"}});
  });
  svr.Post("/api/standby/config", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    json cfg = app_.config.value("standby", json::object());
    for (auto& [k, v] : body.items()) cfg[k] = v;
    app_.config["standby"] = cfg;
    save_config_file(app_);
    send_json(res, {{"ok", true}, {"message", "Standby config saved"}});
  });
  svr.Get("/api/standby/output", [this, standby_state](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json st = standby_state();
    send_json(res, {{"output", st.value("output", "")}, {"running", st.value("running", false)}});
  });
  svr.Get("/api/ppt/themes", [](const httplib::Request&, httplib::Response& res) {
    send_json(res, {{"ok", true}, {"themes", json::array({"dark", "light", "tech", "paper"})}});
  });
  svr.Get("/api/ppt/list", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json files = json::array();
    std::error_code ec;
    std::string dir = app_.paths.data_dir + "/ppt_exports";
    if (fs::exists(dir, ec)) {
      for (const auto& e : fs::directory_iterator(dir, ec)) {
        if (e.is_regular_file()) files.push_back(e.path().filename().string());
      }
    }
    send_json(res, {{"ok", true}, {"files", files}});
  });
  svr.Post("/api/ppt/generate", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string title = trim(body.value("title", "PPT"));
    std::string theme = body.value("theme", "dark");
    std::string content;
    json rels = body.value("files", body.value("rel_paths", json::array()));
    if (rels.is_string()) rels = json::array({rels});
    if (rels.empty() && body.contains("bvid")) {
      std::string bvid = safe_bvid(body.value("bvid", ""));
      KnowledgeBase kb(app_.paths.knowledge_metadata_file, app_.paths.knowledge_base_dir);
      kb.load();
      const auto& idx = kb.metadata().value("file_index", nlohmann::json::object());
      for (auto& [cat, entries] : idx.items()) {
        for (const auto& e : entries) {
          if (e.value("bvid", "") == bvid) {
            content = read_file(app_.paths.knowledge_base_dir + "/" + e.value("path", ""));
            break;
          }
        }
      }
    }
    for (const auto& rp : rels) {
      content += read_file(app_.paths.knowledge_base_dir + "/" + rp.get<std::string>()) + "\n\n";
    }
    if (content.empty()) content = "# " + title + "\n\nNo content provided.";
    std::vector<std::string> slides;
    size_t pos = 0;
    while (pos <= content.size()) {
      size_t next = content.find("\n## ", pos);
      slides.push_back(content.substr(pos, next == std::string::npos ? std::string::npos : next - pos));
      if (next == std::string::npos) break;
      pos = next + 1;
    }
    std::string html = "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><title>" + title + "</title>";
    html += "<style>body{font-family:system-ui,'Microsoft YaHei';margin:0;background:" + std::string(theme == "light" ? "#f5f5f5" : "#10141a") + ";color:" + std::string(theme == "light" ? "#111" : "#eee") + "}.slide{min-height:100vh;padding:8vh 10vw;box-sizing:border-box;border-bottom:1px solid rgba(128,128,128,.25)}h1{font-size:44px}pre{white-space:pre-wrap;font-size:18px;line-height:1.8}</style></head><body>";
    for (const auto& slide : slides) {
      html += "<section class=\"slide\"><pre>" + slide + "</pre></section>";
    }
    html += "</body></html>";
    std::string dir = app_.paths.data_dir + "/ppt_exports";
    std::error_code ec;
    fs::create_directories(dir, ec);
    std::string path = dir + "/" + title + "_" + timestamp_suffix() + ".html";
    write_file(path, html);
    send_json(res, {{"ok", true}, {"path", path}, {"slides", slides.size()}, {"message", "PPT generated"}});
  });
  svr.Post("/api/action/deep-research", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string topic = trim(body.value("topic", body.value("keyword", "")));
    if (topic.empty()) {
      send_json(res, {{"ok", false}, {"message", "Topic required"}}, 400);
      return;
    }
    int count = body.value("count", 3);
    count = std::max(1, std::min(10, count));
    NetClient net(app_);
    AiClient ai(app_, net);
    std::vector<DeepResult> results;
    std::string err;
    if (!deep_dive(app_, net, ai, topic, count, results, err)) {
      send_json(res, {{"ok", false}, {"message", err}}, 502);
      return;
    }
    json archive = read_json(app_.paths.data_dir + "/research_archive.json", json::object());
    json records = archive.value("records", json::array());
    json out = json::array();
    for (const auto& r : results) {
      json record = {{"id", "r" + std::to_string(now_epoch()) + "-" + std::to_string(records.size())},
                     {"topic", topic}, {"bvid", r.bvid}, {"title", r.title}, {"summary", r.summary},
                     {"source", {{"url", "https://www.bilibili.com/video/" + r.bvid}, {"title", r.title},
                                  {"author", ""}, {"accessed_at", now_iso()}}},
                     {"evidence", json::array()}, {"materials", {{"notice", "Bilibili video notes"}}},
                     {"created_at", now_iso()}};
      records.push_back(record);
      out.push_back(record);
    }
    archive["records"] = records;
    write_json(app_.paths.data_dir + "/research_archive.json", archive);
    send_json(res, {{"ok", true}, {"results", out}, {"count", out.size()},
                    {"message", "Deep research completed"}});
  });
  svr.Post("/api/action/visual-note", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string bvid = safe_bvid(body.value("bvid", body.value("url", "")));
    if (bvid.empty()) {
      send_json(res, {{"ok", false}, {"message", "Invalid BV"}}, 400);
      return;
    }
    NetClient net(app_);
    AiClient ai(app_, net);
    VideoAnalysis va;
    std::string err;
    if (!analyze_video(app_, net, ai, bvid, va, err)) {
      std::string info_err;
      va.info = video_info(net, bvid, 0, info_err);
      va.subtitles = fetch_subtitles(net, va.info);
    }
    std::string cover;
    NetResponse view = net.get("https://api.bilibili.com/x/web-interface/view", {{"bvid", bvid}}, {}, true);
    try {
      json vj = json::parse(view.body);
      cover = vj["data"].value("pic", "");
      if (starts_with(cover, "//")) cover = "https:" + cover;
    } catch (...) {
    }
    std::string vision_summary;
    std::string frames_dir = app_.paths.data_dir + "/visual_notes/frames/" + bvid;
    std::vector<std::string> frames;
    if (va.info.cid == 0) {
      std::string info_err;
      va.info = video_info(net, bvid, 0, info_err);
    }
    if (va.info.cid != 0) {
      NetResponse play = net.get("https://api.bilibili.com/x/player/playurl",
          {{"bvid", bvid}, {"cid", std::to_string(va.info.cid)}, {"qn", "32"},
           {"fnval", "16"}, {"fnver", "0"}, {"fourk", "0"}}, {}, true);
      std::string video_url;
      try {
        json pj = json::parse(play.body);
        const json& durl = pj["data"].value("durl", json::array());
        if (durl.is_array() && !durl.empty()) video_url = durl[0].value("url", "");
      } catch (...) {
      }
      std::string ffmpeg = get_str(app_, "video", "ffmpeg_path", "");
      if (ffmpeg.empty() || !fs::exists(ffmpeg)) {
        std::string bundled = (fs::current_path() / "ffmpeg.exe").string();
        if (fs::exists(bundled)) ffmpeg = bundled;
        else if (ffmpeg.empty()) ffmpeg = "ffmpeg";
      }
      frames = extract_frames_direct(video_url, frames_dir, 3);
      if (frames.empty()) frames = extract_frames(ffmpeg, video_url, frames_dir, 3);
    }
    if (!cover.empty()) {
      std::string vision_prompt = "Describe this video cover and infer the topic. Keep it under 120 Chinese characters.";
      vision_summary = ai.chat_vision({{"system", "You are a careful video cover analyst."},
                                       {"user", vision_prompt}}, cover);
    }
    for (const auto& frame : frames) {
      std::string b64 = base64_encode(read_file(frame));
      if (b64.empty()) continue;
      std::string frame_summary = ai.chat_vision(
          {{"system", "You analyze video frames. Extract visible text via OCR and describe the scene."},
           {"user", "OCR and describe this frame in under 150 Chinese characters."}},
          std::string("data:image/jpeg;base64,") + b64);
      if (!frame_summary.empty()) {
        vision_summary += std::string(vision_summary.empty() ? "" : "\n") + "[Frame " +
                          std::to_string(frames.size()) + "] " + frame_summary;
      }
    }
    std::string html = "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><title>" + va.info.title + "</title></head><body><h1>" + va.info.title + "</h1>";
    if (!cover.empty()) html += "<img src=\"" + cover + "\" style=\"max-width:480px\" referrerpolicy=\"no-referrer\">";
    for (const auto& frame : frames) {
      std::string b64 = base64_encode(read_file(frame));
      if (!b64.empty()) html += std::string("<img src=\"data:image/jpeg;base64,") + b64 + "\" style=\"max-width:360px;margin:4px\">";
    }
    html += "<h2>AI Summary</h2><p>" + va.ai_summary + "</p>";
    if (!vision_summary.empty()) html += "<h2>Visual Analysis</h2><pre>" + vision_summary + "</pre>";
    html += "<h2>Subtitles</h2><pre>" + va.subtitles + "</pre></body></html>";
    std::string dir = app_.paths.data_dir + "/visual_notes";
    std::error_code ec;
    fs::create_directories(dir, ec);
    std::string path = dir + "/" + bvid + ".html";
    write_file(path, html);
    write_json(app_.paths.data_dir + "/visual_note_status_" + bvid + ".json",
               {{"bvid", bvid}, {"status", "done"}, {"path", path}, {"updated_at", now_iso()}});
    send_json(res, {{"ok", true}, {"bvid", bvid}, {"status", "done"}, {"path", path},
                    {"message", "Visual note generated"}});
  });
  svr.Get("/api/action/visual-note/status/(.*)", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string bvid = safe_bvid(percent_decode(req.matches[1]));
    json st = read_json(app_.paths.data_dir + "/visual_note_status_" + bvid + ".json", json::object());
    send_json(res, {{"ok", true}, {"bvid", bvid}, {"status", st.value("status", "unknown")},
                    {"path", st.value("path", "")}});
  });
  svr.Get("/api/action/mindmap/view", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string rel = trim(qparam(req, "path", ""));
    fs::path root = fs::absolute(app_.paths.user_data_dir + "/Mindmaps");
    fs::path target = fs::absolute(fs::path(app_.paths.user_data_dir + "/Mindmaps") / rel);
    if (target.string().rfind(root.string(), 0) != 0 || !fs::exists(target)) {
      send_json(res, {{"ok", false}, {"message", "Not found"}}, 404);
      return;
    }
    res.set_content(read_file(target.string()), "text/html; charset=utf-8");
  });
  auto research_archive = [this]() -> json {
    json data = read_json(app_.paths.data_dir + "/research_archive.json", json::object());
    if (!data.is_object()) data = json::object();
    return data;
  };
  svr.Get("/api/research/projects", [this, research_archive](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json data = research_archive();
    send_json(res, {{"ok", true}, {"projects", data.value("projects", json::array())}});
  });
  svr.Post("/api/research/projects", [this, research_archive](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string name = trim(body.value("name", "untitled"));
    json data = research_archive();
    json projects = data.value("projects", json::array());
    json project = {{"id", "p" + std::to_string(now_epoch())}, {"name", name},
                    {"tags", body.value("tags", json::array())}, {"created_at", now_iso()}};
    projects.push_back(project);
    data["projects"] = projects;
    write_json(app_.paths.data_dir + "/research_archive.json", data);
    send_json(res, {{"ok", true}, {"project", project}, {"message", "Project created"}});
  });
  svr.Get("/api/research/records", [this, research_archive](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json data = research_archive();
    send_json(res, {{"ok", true}, {"records", data.value("records", json::array())}});
  });
  svr.Post("/api/research/batch", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    json bvids = body.value("bvids", json::array());
    std::vector<std::string> cleaned;
    for (const auto& v : bvids) {
      std::string b = safe_bvid(v.get<std::string>());
      if (!b.empty() && std::find(cleaned.begin(), cleaned.end(), b) == cleaned.end()) cleaned.push_back(b);
      if ((int)cleaned.size() >= 5) break;
    }
    if (cleaned.empty()) {
      send_json(res, {{"ok", false}, {"message", "No valid BV"}}, 400);
      return;
    }
    NetClient net(app_);
    AiClient ai(app_, net);
    json archive = read_json(app_.paths.data_dir + "/research_archive.json", json::object());
    json records = archive.value("records", json::array());
    int done = 0, failed = 0;
    for (const auto& bvid : cleaned) {
      VideoAnalysis va;
      std::string err;
      if (analyze_video(app_, net, ai, bvid, va, err)) {
        json record = {{"id", "r" + std::to_string(now_epoch()) + "-" + std::to_string(records.size())},
                       {"topic", body.value("project_id", "batch")}, {"bvid", bvid},
                       {"title", va.info.title}, {"summary", va.ai_summary},
                       {"source", {{"url", "https://www.bilibili.com/video/" + bvid}, {"title", va.info.title},
                                    {"author", ""}, {"accessed_at", now_iso()}}},
                       {"evidence", json::array()}, {"materials", {{"notice", "video analysis"}}},
                       {"created_at", now_iso()}};
        records.push_back(record);
        done++;
      } else {
        failed++;
      }
    }
    archive["records"] = records;
    write_json(app_.paths.data_dir + "/research_archive.json", archive);
    send_json(res, {{"ok", true}, {"processed", done + failed}, {"done", done}, {"failed", failed},
                    {"task_id", "research-" + std::to_string(now_epoch())},
                    {"message", "Research batch completed"}});
  });
  svr.Get("/api/research/export/(.*)", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    std::string fmt = lower(percent_decode(req.matches[1]));
    json data = read_json(app_.paths.data_dir + "/research_archive.json", json::object());
    std::string text = data.dump(2);
    std::string dir = app_.paths.data_dir + "/exports";
    std::error_code ec;
    fs::create_directories(dir, ec);
    std::string path = dir + "/research_" + timestamp_suffix() + "." + (fmt.empty() ? "json" : fmt);
    write_file(path, text);
    send_json(res, {{"ok", true}, {"path", path}, {"message", "Research exported"}});
  });
  svr.Post("/api/auth/security-question", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    std::string q = trim(body.value("question", ""));
    std::string a = trim(body.value("answer", ""));
    if (q.size() < 2 || a.empty()) {
      send_json(res, {{"ok", false}, {"message", "Question and answer required"}}, 400);
      return;
    }
    app_.config["web"]["recovery_question"] = q;
    app_.config["web"]["recovery_answer_hash"] = sha256_hex(a);
    save_config_file(app_);
    send_json(res, {{"ok", true}, {"message", "Security question saved"}});
  });
  svr.Post("/api/auth/recovery-question", [this](const httplib::Request& req, httplib::Response& res) {
    json body = parse_body(req);
    std::string username = trim(body.value("username", ""));
    if (app_.config.value("web", json::object()).value("username", "") != username) {
      send_json(res, {{"ok", false}, {"message", "User not found"}}, 404);
      return;
    }
    std::string q = app_.config.value("web", json::object()).value("recovery_question", "");
    if (q.empty()) {
      send_json(res, {{"ok", false}, {"message", "Security question not configured"}}, 404);
      return;
    }
    send_json(res, {{"ok", true}, {"question", q}});
  });
  svr.Post("/api/auth/reset-password", [this](const httplib::Request& req, httplib::Response& res) {
    json body = parse_body(req);
    std::string username = trim(body.value("username", ""));
    std::string answer = trim(body.value("answer", ""));
    std::string password = body.value("password", "");
    const auto& web = app_.config.value("web", json::object());
    if (web.value("username", "") != username) {
      send_json(res, {{"ok", false}, {"message", "User not found"}}, 404);
      return;
    }
    if (sha256_hex(answer) != web.value("recovery_answer_hash", "")) {
      send_json(res, {{"ok", false}, {"message", "Wrong answer"}}, 403);
      return;
    }
    if (password.size() < 4) {
      send_json(res, {{"ok", false}, {"message", "Password too short"}}, 400);
      return;
    }
    auth_.setup(username, password);
    save_config_file(app_);
    send_json(res, {{"ok", true}, {"message", "Password reset"}});
  });

  // ----- Private message management -----
  svr.Get("/api/private-message/status", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    send_json(res, {{"running", pm_running_.load()}, {"enabled", get_bool(app_, "private_message", "enabled", false)},
                    {"auto_reply", get_bool(app_, "private_message", "auto_reply", true)}});
  });
  svr.Post("/api/private-message/start", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    app_.config["private_message"]["enabled"] = true;
    save_config_file(app_);
    if (!pm_running_.exchange(true)) {
      if (pm_thread_.joinable()) pm_thread_.detach();
      pm_thread_ = std::thread([this] { pm_loop(); });
    }
    send_json(res, {{"ok", true}, {"message", "Private message worker started"}});
  });
  svr.Post("/api/private-message/stop", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    app_.config["private_message"]["enabled"] = false;
    save_config_file(app_);
    pm_running_.store(false);
    if (pm_thread_.joinable()) pm_thread_.detach();
    send_json(res, {{"ok", true}, {"message", "Private message worker stopped"}});
  });
  svr.Get("/api/private-message/sessions", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json state = read_json(app_.paths.data_dir + "/private_sessions.json", json::object());
    json sessions = json::array();
    for (auto& [k, v] : state.value("sessions", json::object()).items()) {
      sessions.push_back(v);
    }
    send_json(res, {{"ok", true}, {"sessions", sessions}, {"total", sessions.size()}});
  });
  svr.Post("/api/private-message/send", [this](const httplib::Request& req, httplib::Response& res) {
    if (!require_auth(req, res)) return;
    json body = parse_body(req);
    long long uid = body.value("uid", 0);
    std::string text = trim(body.value("text", ""));
    if (uid <= 0 || text.empty()) {
      send_json(res, {{"ok", false}, {"message", "UID and text required"}}, 400);
      return;
    }
    NetClient net(app_);
    std::string err = send_private_message(net, app_, uid, text);
    if (!err.empty()) {
      send_json(res, {{"ok", false}, {"message", err}}, 502);
      return;
    }
    send_json(res, {{"ok", true}, {"message", "Message sent"}});
  });

}
}  // namespace bili
