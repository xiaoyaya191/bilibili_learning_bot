#pragma once

#include <nlohmann/json.hpp>

#include <string>

namespace bili {

struct AppPaths {
  std::string user_data_dir;
  std::string data_dir;
  std::string config_file;
  std::string cookie_file;
	std::string monitor_config_file;
	std::string monitor_at_state;
	std::string comment_log_file;
	std::string log_dir;
	std::string knowledge_metadata_file;
	std::string knowledge_base_dir;
};

struct App {
  AppPaths paths;
  nlohmann::json config = nlohmann::json::object();
  nlohmann::json cookies = nlohmann::json::object();
  nlohmann::json monitor = nlohmann::json::object();
  long long uid = 0;
};

std::string default_user_data_dir();
App load_app(const std::string& user_data_dir);
bool save_cookies_file(const App& app);
bool save_config_file(const App& app);

std::string get_str(const App& app, const std::string& section, const std::string& key,
                    const std::string& fallback = "");
long long get_int(const App& app, const std::string& section, const std::string& key,
                  long long fallback = 0);
bool get_bool(const App& app, const std::string& section, const std::string& key,
              bool fallback = false);
double get_double(const App& app, const std::string& section, const std::string& key,
                  double fallback = 0);

const nlohmann::json& get_json(const App& app, const std::string& section,
                              const std::string& key);

}  // namespace bili
