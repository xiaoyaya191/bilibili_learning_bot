#pragma once

#include <map>
#include <random>
#include <string>

#include "config.h"

namespace bili {

// 面板登录：用户名/密码存 config.web，token 存内存。
class Auth {
 public:
  explicit Auth(App& app);

  bool configured() const;
  bool setup(const std::string& username, const std::string& password);
  std::string login(const std::string& username, const std::string& password);
  bool valid(const std::string& token) const;
  void logout(const std::string& token);

 private:
  std::string hash(const std::string& salt, const std::string& password) const;
  std::string session_file() const;
  void load_tokens() const;
  void save_tokens() const;

  App& app_;
  mutable std::mt19937_64 rng_;
  mutable std::map<std::string, long long> tokens_;  // token -> expiry unix seconds
};

}  // namespace bili
