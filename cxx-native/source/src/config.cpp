#include "config.h"

#include <cstdlib>
#include <filesystem>
#include "fscompat.h"
#include <fstream>
#include <sstream>

namespace fs = std::filesystem;

namespace bili {
namespace {

std::string trim_bom(const std::string& s) {
  if (s.size() >= 3 && (unsigned char)s[0] == 0xEF && (unsigned char)s[1] == 0xBB &&
      (unsigned char)s[2] == 0xBF) {
    return s.substr(3);
  }
  return s;
}

std::string read_file(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) return "";
  std::ostringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

nlohmann::json read_json(const std::string& path) {
  std::string raw = read_file(path);
  if (raw.empty()) return nlohmann::json();
  try {
    return nlohmann::json::parse(trim_bom(raw));
  } catch (...) {
    return nlohmann::json();
  }
}

std::string getenv_str(const char* name) {
  const char* v = std::getenv(name);
  return v ? std::string(v) : "";
}

}  // namespace

std::string default_user_data_dir() {
  std::string explicit_dir = getenv_str("BILI_USER_DATA_DIR");
  if (!explicit_dir.empty()) return explicit_dir;
  std::string local_app_data = getenv_str("LOCALAPPDATA");
  if (!local_app_data.empty()) return local_app_data + "/BiliLearn";
  const char* home = std::getenv("HOME");
  std::string home_dir = home ? home : ".";
  return home_dir + "/AppData/Local/BiliLearn";
}

App load_app(const std::string& user_data_dir_arg) {
  std::string user_data_dir =
      user_data_dir_arg.empty() ? default_user_data_dir() : user_data_dir_arg;
  App app;
  app.paths.user_data_dir = user_data_dir;
  app.paths.data_dir = user_data_dir + "/Data";
  app.paths.config_file = app.paths.data_dir + "/config.json";
  app.paths.cookie_file = app.paths.data_dir + "/bilibili_cookies.json";
  app.paths.monitor_config_file = app.paths.data_dir + "/monitor_config.json";
	app.paths.monitor_at_state = app.paths.data_dir + "/monitor_at_state.json";
	app.paths.comment_log_file = app.paths.data_dir + "/comment_log.json";
	app.paths.log_dir = app.paths.data_dir + "/logs";
	app.paths.knowledge_metadata_file = user_data_dir + "/knowledge_metadata.json";
	app.paths.knowledge_base_dir = user_data_dir + "/KnowledgeBase";

  std::error_code ec;
  fs::create_directories(app.paths.data_dir, ec);
  fs::create_directories(app.paths.log_dir, ec);
  fs::create_directories(app.paths.user_data_dir, ec);
  fs::create_directories(app.paths.knowledge_base_dir, ec);

  app.config = read_json(app.paths.config_file);
  app.cookies = read_json(app.paths.cookie_file);
  app.monitor = read_json(app.paths.monitor_config_file);
  if (!app.config.is_object()) app.config = nlohmann::json::object();
  if (!app.cookies.is_object()) app.cookies = nlohmann::json::object();
  if (!app.monitor.is_object()) app.monitor = nlohmann::json::object();

  static const char* kSections[] = {
      "api", "behavior", "interaction", "monitor", "private_message", "network",
      "web", "asr", "owner_share", "proactive", "curiosity_search", "self_evolution",
      "rag_qa", "version_history", "chapter_lock", "approval_review", "reviews",
      "display", "ui", "standby", "session_limits", "video", "mood", "energy",
      "prompt_injection", "reply_safety", "persona", "feature_flags",
      "document_export", "mindmap", "dry_goods", "knowledge", "agent",
      "active_chat", "automation", "backup", "session", "diary", "system",
      "up_follow", "up_learning", "local_favorites", "revisit", "note_style",
      "model_presets", "fallback_models", "fallback_provider", "platform_adapter",
      "browser_extension", "learning_workflow", "knowledge_verify", "psycho_engine",
  };
  for (const char* sec : kSections) {
    if (!app.config.contains(sec) || !app.config[sec].is_object()) {
      app.config[sec] = nlohmann::json::object();
    }
  }
  if (!app.config["network"].contains("proxy") || !app.config["network"]["proxy"].is_object()) {
    app.config["network"]["proxy"] = nlohmann::json::object();
  }
  if (!app.config["private_message"].contains("agent") ||
      !app.config["private_message"]["agent"].is_object()) {
    app.config["private_message"]["agent"] = nlohmann::json::object();
  }

  if (app.cookies.contains("DedeUserID") && app.cookies["DedeUserID"].is_string()) {
    try {
      app.uid = std::stoll(app.cookies["DedeUserID"].get<std::string>());
    } catch (...) {
      app.uid = 0;
    }
  }
  return app;
}

bool save_cookies_file(const App& app) {
	std::error_code ec;
	fs::create_directories(app.paths.data_dir, ec);
	std::ofstream out(app.paths.cookie_file, std::ios::binary);
	if (!out) return false;
	out << app.cookies.dump(4) << std::flush;
	return out.good();
}

bool save_config_file(const App& app) {
	std::error_code ec;
	fs::create_directories(app.paths.data_dir, ec);
	std::ofstream out(app.paths.config_file, std::ios::binary);
	if (!out) return false;
	out << app.config.dump(2) << std::flush;
	return out.good();
}

const nlohmann::json* section(const App& app, const std::string& name) {
  if (name.empty()) return &app.config;
  if (app.config.contains(name) && app.config[name].is_object()) {
    return &app.config[name];
  }
  return nullptr;
}

std::string get_str(const App& app, const std::string& sec, const std::string& key,
                    const std::string& fallback) {
  const nlohmann::json* s = section(app, sec);
  if (!s || !s->contains(key)) return fallback;
  const auto& v = (*s)[key];
  if (v.is_string()) return v.get<std::string>();
  if (v.is_number()) return std::to_string(v.get<long long>());
  return fallback;
}

long long get_int(const App& app, const std::string& sec, const std::string& key,
                  long long fallback) {
  const nlohmann::json* s = section(app, sec);
  if (!s || !s->contains(key)) return fallback;
  const auto& v = (*s)[key];
  if (v.is_number_integer()) return v.get<long long>();
  if (v.is_number_float()) return (long long)v.get<double>();
  if (v.is_string()) {
    try {
      return std::stoll(v.get<std::string>());
    } catch (...) {
      return fallback;
    }
  }
  return fallback;
}

bool get_bool(const App& app, const std::string& sec, const std::string& key, bool fallback) {
  const nlohmann::json* s = section(app, sec);
  if (!s || !s->contains(key)) return fallback;
  const auto& v = (*s)[key];
  if (v.is_boolean()) return v.get<bool>();
  return fallback;
}

double get_double(const App& app, const std::string& sec, const std::string& key,
                  double fallback) {
	const nlohmann::json* s = section(app, sec);
	if (!s || !s->contains(key)) return fallback;
	const auto& v = (*s)[key];
	if (v.is_number()) return v.get<double>();
	if (v.is_string()) {
		try {
			return std::stod(v.get<std::string>());
		} catch (...) {
			return fallback;
		}
	}
	return fallback;
}

const nlohmann::json& get_json(const App& app, const std::string& sec,
                              const std::string& key) {
	static const nlohmann::json empty = nlohmann::json::object();
	const nlohmann::json* s = section(app, sec);
	if (!s || !s->contains(key)) return empty;
	return (*s)[key];
}

}  // namespace bili
