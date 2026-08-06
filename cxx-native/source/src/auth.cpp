#include "auth.h"

#include <chrono>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include "fscompat.h"
#include <fstream>
#include <sstream>

#include "sha256.h"

namespace bili {
namespace {

std::string random_hex(size_t bytes) {
  std::random_device rd;
  std::string out;
  for (size_t i = 0; i < bytes; i++) {
    char buf[4];
    std::snprintf(buf, sizeof(buf), "%02x", (unsigned char)rd());
    out += buf;
  }
  return out;
}

long long now_unix() {
  return std::chrono::duration_cast<std::chrono::seconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

}  // namespace

Auth::Auth(App& app) : app_(app) {
  std::random_device rd;
  rng_.seed(rd());
  load_tokens();
}

std::string Auth::session_file() const {
  return app_.paths.data_dir + "/web_sessions.json";
}

void Auth::load_tokens() const {
  std::ifstream in(session_file());
  if (!in) return;
  try {
    nlohmann::json j = nlohmann::json::parse(in);
    for (auto& [token, exp] : j.items()) {
      if (exp.is_number_integer()) tokens_[token] = exp.get<long long>();
    }
  } catch (...) {
  }
}

void Auth::save_tokens() const {
  std::error_code ec;
  std::filesystem::create_directories(app_.paths.data_dir, ec);
  nlohmann::json j = nlohmann::json::object();
  long long now = now_unix();
  for (auto& [token, exp] : tokens_) {
    if (exp > now) j[token] = exp;
  }
  std::ofstream out(session_file(), std::ios::binary | std::ios::trunc);
  if (out) out << j.dump(2);
}

bool Auth::configured() const {
  const auto& web = app_.config.value("web", nlohmann::json::object());
  return web.value("username", "").size() >= 2 && web.value("password_hash", "").size() >= 16;
}

std::string Auth::hash(const std::string& salt, const std::string& password) const {
  return sha256_hex(salt + ":" + password);
}

bool Auth::setup(const std::string& username, const std::string& password) {
  if (username.size() < 2 || password.size() < 4) return false;
  auto& web = app_.config["web"];
  if (!web.is_object()) web = nlohmann::json::object();
  std::string salt = random_hex(16);
  web["username"] = username;
  web["password_salt"] = salt;
  web["password_hash"] = hash(salt, password);
  return save_config_file(app_);
}

std::string Auth::login(const std::string& username, const std::string& password) {
  const auto& web = app_.config.value("web", nlohmann::json::object());
  if (web.value("username", "") != username) return "";
  if (hash(web.value("password_salt", ""), password) != web.value("password_hash", "")) {
    return "";
  }
  std::string token = random_hex(32);
  tokens_[token] = now_unix() + 7 * 24 * 3600;
  save_tokens();
  return token;
}

bool Auth::valid(const std::string& token) const {
  if (token.empty()) return false;
  auto it = tokens_.find(token);
  if (it == tokens_.end()) return false;
  if (it->second < now_unix()) {
    tokens_.erase(it);
    return false;
  }
  return true;
}

void Auth::logout(const std::string& token) {
  tokens_.erase(token);
  save_tokens();
}

}  // namespace bili
