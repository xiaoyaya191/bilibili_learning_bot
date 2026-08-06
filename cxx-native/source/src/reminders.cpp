#include "reminders.h"

#include <chrono>
#include <cstdio>
#include <filesystem>
#include "fscompat.h"
#include <fstream>
#include <random>
#include <regex>
#include "platform.h"
#include <sstream>

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
  std::error_code ec;
  fs::create_directories(fs::path(path).parent_path(), ec);
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) return false;
  out << content;
  return out.good();
}

nlohmann::json read_rows(const std::string& path) {
  std::string raw = read_file(path);
  if (raw.empty()) return nlohmann::json::array();
  try {
    auto j = nlohmann::json::parse(raw);
    if (j.is_array()) return j;
  } catch (...) {
  }
  return nlohmann::json::array();
}

std::string now_iso(long long ts = 0) {
  std::time_t t = ts ? (std::time_t)ts : std::time(nullptr);
  std::tm tm{};
  localtime_r(&t, &tm);
  char buf[32];
  std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M", &tm);
  return buf;
}

std::string random_id() {
  std::random_device rd;
  char buf[16];
  std::snprintf(buf, sizeof(buf), "%08x%04x", rd(), rd() & 0xffff);
  return buf;
}

std::string trim(const std::string& s) {
  size_t a = s.find_first_not_of(" \t\r\n，。！!；;");
  if (a == std::string::npos) return "";
  size_t b = s.find_last_not_of(" \t\r\n，。！!；;");
  return s.substr(a, b - a + 1);
}

}  // namespace

nlohmann::json parse_reminder_time_json(const std::string& text, long long now_ts) {
  std::time_t base = now_ts ? (std::time_t)now_ts : std::time(nullptr);
  std::string value = text;
  if (value.find("半") != std::string::npos && value.find("小时") != std::string::npos) {
    base += 30 * 60;
    return {{"due_at", now_iso((long long)base)}, {"ok", true}};
  }

  std::smatch m;
  std::regex relative(R"((?:(\d{1,3})\s*(?:小时|时|hours?|hrs?))?\s*(?:(\d{1,4})\s*(?:分钟|分|mins?|minutes?))?\s*(?:后|之后))");
  if (std::regex_search(value, m, relative)) {
    int hours = m[1].matched ? std::stoi(m[1]) : 0;
    int minutes = m[2].matched ? std::stoi(m[2]) : 0;
    if (hours || minutes) {
      base += hours * 3600 + minutes * 60;
      return {{"due_at", now_iso((long long)base)}, {"ok", true}};
    }
  }

  int hour = -1, minute = 0;
  std::regex clock1(R"((\d{1,2})\s*[:：]\s*(\d{1,2}))");
  if (std::regex_search(value, m, clock1)) {
    hour = std::stoi(m[1]);
    minute = std::stoi(m[2]);
  } else {
    std::regex clock2(R"((\d{1,2})\s*点\s*(半|(\d{1,2})\s*分)?)");
    if (std::regex_search(value, m, clock2)) {
      hour = std::stoi(m[1]);
      if (m[2].matched && m[2].str() == "半") minute = 30;
      else if (m[3].matched) minute = std::stoi(m[3]);
    }
  }
  if (hour < 0 || hour > 23 || minute > 59) return nlohmann::json::object();

  if ((value.find("下午") != std::string::npos || value.find("晚上") != std::string::npos ||
       value.find("傍晚") != std::string::npos || value.find("今晚") != std::string::npos) &&
      hour < 12) {
    hour += 12;
  }
  if ((value.find("凌晨") != std::string::npos || value.find("早上") != std::string::npos ||
       value.find("早晨") != std::string::npos || value.find("上午") != std::string::npos) &&
      hour == 12) {
    hour = 0;
  }

  std::tm tm{};
  localtime_r(&base, &tm);
  tm.tm_hour = hour;
  tm.tm_min = minute;
  tm.tm_sec = 0;
  if (value.find("明天") != std::string::npos) tm.tm_mday += 1;
  std::time_t target = std::mktime(&tm);
  if (value.find("今天") == std::string::npos && value.find("明天") == std::string::npos &&
      target <= base) {
    target += 24 * 3600;
  }
  return {{"due_at", now_iso((long long)target)}, {"ok", true}};
}

nlohmann::json create_reminder(const App& app, const std::string& text,
                               const std::string& owner_uid) {
  auto parsed = parse_reminder_time_json(text);
  if (!parsed.value("ok", false)) {
    return {{"ok", false},
            {"message", "没有识别到明确时间，请写“明天 8 点提醒我…”或“30 分钟后提醒我…”"}};
  }
  std::string when = parsed.value("due_at", "");
  std::string content = text;
  size_t pos = content.find("提醒我");
  if (pos != std::string::npos) content = content.substr(pos + std::string("提醒我").size());
  pos = content.find("叫我");
  if (pos != std::string::npos) content = content.substr(pos + std::string("叫我").size());
  content = trim(content);
  if (content.empty()) content = trim(text);

  std::string path = app.paths.data_dir + "/reminders.json";
  nlohmann::json rows = read_rows(path);
  nlohmann::json row = {{"id", random_id()},
                        {"owner_uid", owner_uid},
                        {"content", content.substr(0, 240)},
                        {"due_at", when},
                        {"created_at", now_iso()},
                        {"status", "pending"},
                        {"delivered_at", ""}};
  rows.push_back(row);
  if (rows.size() > 500) rows.erase(rows.begin(), rows.end() - 500);
  write_file(path, rows.dump(2));
  return {{"ok", true}, {"reminder", row}, {"message", "已设定 " + when + " 提醒：" + content.substr(0, 80)}};
}

nlohmann::json take_due_reminders(const App& app) {
  std::string path = app.paths.data_dir + "/reminders.json";
  nlohmann::json rows = read_rows(path);
  std::string now = now_iso();
  nlohmann::json due = nlohmann::json::array();
  bool changed = false;
  for (auto& row : rows) {
    if (!row.is_object() || row.value("status", "") != "pending") continue;
    if (row.value("due_at", "") <= now) {
      row["status"] = "delivered";
      row["delivered_at"] = now;
      due.push_back(row);
      changed = true;
    }
  }
  if (changed) write_file(path, rows.dump(2));
  return due;
}

nlohmann::json list_reminders(const App& app) {
  return read_rows(app.paths.data_dir + "/reminders.json");
}

}  // namespace bili
