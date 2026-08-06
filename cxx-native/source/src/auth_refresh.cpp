#include "auth_refresh.h"

#include <random>
#include <regex>

#include "cookies.h"
#include "urlcodec.h"

namespace bili {
namespace {


std::string trim(const std::string& s) {
  size_t a = s.find_first_not_of(" \t\r\n");
  if (a == std::string::npos) return "";
  size_t b = s.find_last_not_of(" \t\r\n");
  return s.substr(a, b - a + 1);
}

std::string random_hex() {
  std::random_device rd;
  char buf[16];
  std::snprintf(buf, sizeof(buf), "%08x%08x", rd(), rd());
  return buf;
}

}  // namespace

bool refresh_cookies(App& app, NetClient& net, std::string& error) {
  std::string refresh_token = cookie_value(app, "ac_time_value");
  std::string csrf = cookie_value(app, "bili_jct");
  if (refresh_token.empty() || csrf.empty()) {
    error = "missing refresh_token or bili_jct";
    return false;
  }

  std::string correspond = random_hex();
  NetResponse page = net.raw_get("https://www.bilibili.com/correspond/1/" + correspond);
  std::smatch m;
  std::string refresh_csrf;
  if (std::regex_search(page.body, m, std::regex(R"(<div id="1-name">(.+?)</div>)"))) {
    refresh_csrf = m[1];
  }
  if (refresh_csrf.empty()) {
    error = "refresh csrf not found";
    return false;
  }

  NetResponse refresh = net.post("https://passport.bilibili.com/x/passport-login/web/cookie/refresh",
                                 {{"csrf", csrf}, {"refresh_csrf", refresh_csrf},
                                  {"refresh_token", refresh_token}, {"source", "main_web"}});
  std::string new_token = refresh_token;
  try {
    auto j = nlohmann::json::parse(refresh.body);
    if (j.value("code", -1) != 0) {
      error = "refresh failed: " + j.value("message", "");
      return false;
    }
    new_token = j.value("data", nlohmann::json::object()).value("refresh_token", refresh_token);
  } catch (...) {
    error = "refresh response parse failed";
    return false;
  }

  for (const auto& line : refresh.set_cookies) {
    size_t colon = line.find(":");
    if (colon == std::string::npos) continue;
    std::string rest = line.substr(colon + 1);
    size_t semi = rest.find(';');
    std::string kv = rest.substr(0, semi);
    size_t eq = kv.find('=');
    if (eq == std::string::npos) continue;
    std::string key = trim(kv.substr(0, eq));
    std::string value = trim(kv.substr(eq + 1));
    if (!key.empty() && !value.empty()) app.cookies[key] = value;
  }
  if (!new_token.empty()) app.cookies["ac_time_value"] = new_token;
  if (!save_cookies_file(app)) {
    error = "save cookies failed";
    return false;
  }

  NetResponse confirm = net.get("https://passport.bilibili.com/x/passport-login/web/confirm/refresh",
                                {{"csrf", cookie_value(app, "bili_jct")},
                                 {"refresh_token", new_token}});
  (void)confirm;
  return true;
}

}  // namespace bili
