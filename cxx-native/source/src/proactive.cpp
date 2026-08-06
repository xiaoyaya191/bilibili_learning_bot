#include "proactive.h"

#include <chrono>
#include <filesystem>
#include "fscompat.h"
#include <fstream>
#include "platform.h"
#include <sstream>

namespace fs = std::filesystem;
using json = nlohmann::json;

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

nlohmann::json read_json(const std::string& path) {
  std::string raw = read_file(path);
  if (raw.empty()) return nlohmann::json::object();
  try {
    auto j = nlohmann::json::parse(raw);
    return j.is_object() ? j : nlohmann::json::object();
  } catch (...) {
    return nlohmann::json::object();
  }
}

bool write_json(const std::string& path, const nlohmann::json& v) {
  return write_file(path, v.dump(2));
}

std::string now_iso() {
  std::time_t t = std::time(nullptr);
  std::tm tm{};
  localtime_r(&t, &tm);
  char buf[32];
  std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &tm);
  return buf;
}

}  // namespace

nlohmann::json proactive_status(const App& app) {
  json st = read_json(app.paths.data_dir + "/proactive_state.json");
  return {{"enabled", get_bool(app, "proactive", "enabled", false)},
          {"interval_minutes", get_int(app, "proactive", "interval_minutes", 30)},
          {"last_run_at", st.value("last_run_at", "")},
          {"today_count", st.value("today_count", 0)}};
}

nlohmann::json evolution_status(const App& app) {
  json st = read_json(app.paths.data_dir + "/self_evolution.json");
  json events = st.value("events", st.value("items", json::array()));
  return {{"enabled", get_bool(app, "self_evolution", "enabled", false)},
          {"event_count", events.size()},
          {"last_reflect_at", st.value("last_reflect_at", "")}};
}

nlohmann::json run_proactive_cycle(App& app, Monitor& monitor) {
  if (!get_bool(app, "proactive", "enabled", false)) {
    return {{"ok", false}, {"message", "proactive disabled"}};
  }
  json st = read_json(app.paths.data_dir + "/proactive_state.json");
  int browsed = monitor.browse_recommendations();
  std::string today = now_iso().substr(0, 10);
  if (st.value("date", "") != today) {
    st["date"] = today;
    st["today_count"] = 0;
  }
  st["today_count"] = st.value("today_count", 0);
  st["today_count"] = st["today_count"].get<long long>() + browsed;
  st["last_run_at"] = now_iso();
  write_json(app.paths.data_dir + "/proactive_state.json", st);
  return {{"ok", true}, {"browsed", browsed}, {"state", st}};
}

nlohmann::json run_evolution_cycle(App& app) {
  if (!get_bool(app, "self_evolution", "enabled", false)) {
    return {{"ok", false}, {"message", "evolution disabled"}};
  }
  json st = read_json(app.paths.data_dir + "/self_evolution.json");
  json events = st.value("events", st.value("items", json::array()));
  if (!events.is_array()) events = json::array();
  long long min_events = get_int(app, "self_evolution", "min_events_for_reflect", 10);
  if ((long long)events.size() < min_events) {
    return {{"ok", false}, {"message", "not enough events", "count", events.size()}};
  }
  st["last_reflect_at"] = now_iso();
  json reflection = {{"at", now_iso()}, {"type", "reflect"},
                     {"summary", "自动反思：基于近期互动记录总结偏好并更新行为策略。"},
                     {"events_reviewed", events.size()}};
  if (!st.contains("reflections")) st["reflections"] = json::array();
  st["reflections"].push_back(reflection);
  if (st["reflections"].size() > 200) st["reflections"].erase(st["reflections"].begin(), st["reflections"].end() - 200);
  write_json(app.paths.data_dir + "/self_evolution.json", st);
  return {{"ok", true}, {"reflection", reflection}};
}

}  // namespace bili
