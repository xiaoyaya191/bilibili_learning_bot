#include "state.h"

#include <algorithm>
#include "platform.h"
#include <chrono>
#include <ctime>
#include <filesystem>
#include "fscompat.h"
#include <fstream>
#include <iomanip>
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
  std::ofstream out(path, std::ios::binary);
  if (!out) return false;
  out << content;
  return out.good();
}

std::string strip_bom(const std::string& s) {
  if (s.size() >= 3 && (unsigned char)s[0] == 0xEF && (unsigned char)s[1] == 0xBB &&
      (unsigned char)s[2] == 0xBF) {
    return s.substr(3);
  }
  return s;
}

bool contains(const nlohmann::json& arr, const std::string& id) {
  if (!arr.is_array()) return false;
  for (const auto& v : arr) {
    if (v.is_string() && v.get<std::string>() == id) return true;
  }
  return false;
}

void append_unique(nlohmann::json& arr, const std::string& id) {
  if (!arr.is_array()) arr = nlohmann::json::array();
  if (!contains(arr, id)) arr.push_back(id);
}

std::string today_str() {
	std::time_t t = std::time(nullptr);
	std::tm tm{};
	localtime_r(&t, &tm);
	char buf[16];
	std::strftime(buf, sizeof(buf), "%Y-%m-%d", &tm);
	return buf;
}

std::string now_iso() {
	std::time_t t = std::time(nullptr);
	std::tm tm{};
	localtime_r(&t, &tm);
	char buf[40];
	std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &tm);
	return buf;
}

double minutes_since_iso(const std::string& iso) {
	std::tm tm{};
	std::istringstream in(iso);
	in >> std::get_time(&tm, "%Y-%m-%dT%H:%M:%S");
	if (in.fail()) return -1;
	std::time_t past = timegm(&tm);
	return std::difftime(std::time(nullptr), past) / 60.0;
}

}  // namespace

CommentLog::CommentLog(std::string path) : path_(std::move(path)) {}

bool CommentLog::load() {
  std::string raw = read_file(path_);
  if (raw.empty()) {
    data_ = {{"processed_comments", nlohmann::json::array()},
             {"replied_comments", nlohmann::json::array()},
             {"liked_comments", nlohmann::json::array()},
             {"history", nlohmann::json::array()},
             {"user_reply_state", nlohmann::json::object()},
             {"reply_feed_baseline_initialized", false},
             {"conversations", nlohmann::json::object()},
             {"three_action_done", nlohmann::json::object()}};
    return true;
  }
  try {
    data_ = nlohmann::json::parse(strip_bom(raw));
  } catch (...) {
    return false;
  }
  return true;
}

bool CommentLog::save() {
  fs::create_directories(fs::path(path_).parent_path());
  std::string tmp = path_ + ".tmp";
  if (!write_file(tmp, data_.dump(2))) return false;
  std::error_code ec;
  fs::rename(tmp, path_, ec);
  return !ec;
}

bool CommentLog::is_processed(const std::string& id) const {
  if (id.empty()) return true;
  if (contains(data_.value("processed_comments", nlohmann::json()), id)) return true;
  if (contains(data_.value("replied_comments", nlohmann::json()), id)) return true;
  if (contains(data_.value("liked_comments", nlohmann::json()), id)) return true;
  return false;
}

bool CommentLog::mark_processed(const std::string& id) {
  append_unique(data_["processed_comments"], id);
  return save();
}

bool CommentLog::mark_replied(const std::string& id) {
  append_unique(data_["replied_comments"], id);
  return save();
}

bool CommentLog::mark_liked(const std::string& id) {
  append_unique(data_["liked_comments"], id);
  return save();
}

bool CommentLog::log_interaction(const std::string& id, const std::string& action,
                                 const std::string& content,
                                 const std::string& target_user) {
  auto& history = data_["history"];
  if (!history.is_array()) history = nlohmann::json::array();
  history.push_back({{"timestamp", now_iso()}, {"comment_id", id}, {"action", action},
                     {"content", content}, {"target_user", target_user}});
  if (action == "reply") mark_replied(id);
  if (action == "like") mark_liked(id);
  return save();
}

bool CommentLog::reply_feed_baseline() const {
  return data_.value("reply_feed_baseline_initialized", false);
}

bool CommentLog::set_reply_feed_baseline(const std::vector<std::string>& ids) {
  for (const auto& id : ids) {
    if (!id.empty()) append_unique(data_["processed_comments"], id);
  }
  data_["reply_feed_baseline_initialized"] = true;
  return save();
}

bool CommentLog::should_reply_user(const std::string& user_id, const std::string& content,
                                   int cooldown_minutes, std::string& reason) const {
  reason = "pass";
  if (cooldown_minutes <= 0 || user_id.empty()) return true;
  const auto& states = data_.value("user_reply_state", nlohmann::json::object());
  if (!states.contains(user_id)) return true;
  std::string last = states[user_id].value("last_reply_at", "");
  if (last.empty()) return true;
  double elapsed = minutes_since_iso(last);
  if (elapsed < 0) elapsed = 0;
  bool direct = content.find('?') != std::string::npos ||
                content.find("？") != std::string::npos ||
                content.find("怎么") != std::string::npos ||
                content.find("为什么") != std::string::npos;
  if (elapsed < cooldown_minutes && !direct) {
    reason = "same user replied within cooldown";
    return false;
  }
  return true;
}

bool CommentLog::mark_user_replied(const std::string& user_id) {
  auto& states = data_["user_reply_state"];
  if (!states.is_object()) states = nlohmann::json::object();
  auto& st = states[user_id];
  if (!st.is_object()) st = nlohmann::json::object();
  st["last_reply_at"] = now_iso();
  st["count"] = st.value("count", 0LL) + 1;
  return save();
}

bool CommentLog::three_action_done(const std::string& bvid) const {
  const auto& done = data_.value("three_action_done", nlohmann::json::object());
  return done.contains("three:" + bvid);
}

bool CommentLog::mark_three_action(const std::string& bvid, const nlohmann::json& results) {
  auto& done = data_["three_action_done"];
  if (!done.is_object()) done = nlohmann::json::object();
  auto entry = results;
  entry["date"] = today_str();
  done["three:" + bvid] = entry;
  return save();
}

int CommentLog::coin_used_today() const {
  const auto& done = data_.value("three_action_done", nlohmann::json::object());
  std::string today = today_str();
  int count = 0;
  for (const auto& [k, v] : done.items()) {
    if (!v.is_object()) continue;
    if (v.value("date", "") == today && v.value("coin", "") == "ok") count++;
  }
  return count;
}

AtState::AtState(std::string path) : path_(std::move(path)) {}

bool AtState::load() {
  std::string raw = read_file(path_);
  if (raw.empty()) {
    data_ = {{"processed_ids", nlohmann::json::array()},
             {"attempts", nlohmann::json::object()},
             {"source_routing_migrated_ids", nlohmann::json::array()}};
    return true;
  }
  try {
    data_ = nlohmann::json::parse(strip_bom(raw));
  } catch (...) {
    return false;
  }
  return true;
}

bool AtState::save() {
  fs::create_directories(fs::path(path_).parent_path());
  std::string tmp = path_ + ".tmp";
  if (!write_file(tmp, data_.dump(2))) return false;
  std::error_code ec;
  fs::rename(tmp, path_, ec);
  return !ec;
}

bool AtState::processed(const std::string& id) const {
  return contains(data_.value("processed_ids", nlohmann::json()), id);
}

bool AtState::mark_processed(const std::string& id) {
  append_unique(data_["processed_ids"], id);
  auto& attempts = data_["attempts"];
  if (attempts.is_object()) attempts.erase(id);
  return save();
}

int AtState::record_attempt(const std::string& id) {
  auto& attempts = data_["attempts"];
  if (!attempts.is_object()) attempts = nlohmann::json::object();
  int n = attempts.value(id, 0LL) + 1;
  attempts[id] = n;
  save();
  return n;
}

}  // namespace bili
