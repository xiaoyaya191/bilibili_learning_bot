#include "cookies.h"

#include "net.h"

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <random>
#include <sstream>

#include <nlohmann/json.hpp>

namespace bili {
namespace {

bool is_valid_buvid3(const std::string& v) {
  // Standard UUID + "infoc" suffix.
  const size_t len = v.size();
  if (len < 40 || v.rfind("infoc") != len - 5) return false;
  const std::string head = v.substr(0, len - 5);
  size_t dash = 0;
  for (char c : head) {
    if (c == '-') {
      dash++;
      continue;
    }
    if (!std::isxdigit((unsigned char)c)) return false;
  }
  return dash == 4;
}

std::string random_uuid() {
  std::random_device rd;
  std::mt19937_64 gen(rd());
  char buf[64];
  std::snprintf(buf, sizeof(buf), "%08x-%04x-4%03x-%04x-%012llx", gen() & 0xffffffffu,
                gen() & 0xffff, gen() & 0xfff, (gen() & 0x3fff) | 0x8000,
                (unsigned long long)(gen() & 0xffffffffffffLL));
  return buf;
}

}  // namespace

bool ensure_buvid3(App& app) {
  std::string buvid3 = cookie_value(app, "buvid3");
  if (is_valid_buvid3(buvid3)) return true;
  buvid3 = random_uuid() + "infoc";
  app.cookies["buvid3"] = buvid3;
  return save_cookies_file(app);
}

std::string cookie_value(const App& app, const std::string& key) {
  if (app.cookies.contains(key) && app.cookies[key].is_string()) {
    return app.cookies[key].get<std::string>();
  }
  return "";
}

std::string cookie_header(const App& app) {
  std::ostringstream out;
  bool first = true;
  for (auto it = app.cookies.begin(); it != app.cookies.end(); ++it) {
    if (!it.value().is_string()) continue;
    const std::string value = it.value().get<std::string>();
    if (value.empty()) continue;
    if (!first) out << "; ";
    first = false;
    out << it.key() << "=" << value;
  }
  return out.str();
}

bool ensure_buvid4(App& app, NetClient& net) {
  if (!cookie_value(app, "buvid3").empty() && !cookie_value(app, "buvid4").empty()) {
    return true;
  }
  NetResponse resp = net.raw_get("https://api.bilibili.com/x/frontend/finger/spi");
  try {
    auto j = nlohmann::json::parse(resp.body);
    if (!j.is_object()) return false;
    const auto& data = j.value("data", nlohmann::json::object());
    if (!data.is_object()) return false;
    std::string b3 = data.value("b_3", "");
    std::string b4 = data.value("b_4", "");
    if (b3.empty() || b4.empty()) return false;
    app.cookies["buvid3"] = b3;
    app.cookies["buvid4"] = b4;
    return save_cookies_file(app);
  } catch (...) {
    return false;
  }
}

}  // namespace bili
