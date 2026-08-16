#include "login.h"

#include <chrono>
#include <cstdio>
#include <algorithm>
#include <cctype>
#include <map>
#include <thread>

#include "cookies.h"
#include "net.h"
#include "qr.h"
#include "urlcodec.h"

namespace bili {
namespace {

std::map<std::string, std::string> parse_url_query(const std::string& url) {
  std::map<std::string, std::string> out;
  size_t q = url.find('?');
  if (q == std::string::npos) return out;
  std::string query = url.substr(q + 1);
  size_t pos = 0;
  while (pos <= query.size()) {
    size_t amp = query.find('&', pos);
    std::string pair = query.substr(pos, amp == std::string::npos ? std::string::npos : amp - pos);
    size_t eq = pair.find('=');
    if (eq != std::string::npos) {
      out[percent_decode(pair.substr(0, eq))] = percent_decode(pair.substr(eq + 1));
    }
    if (amp == std::string::npos) break;
    pos = amp + 1;
  }
  return out;
}

std::map<std::string, std::string> parse_set_cookies(const std::vector<std::string>& lines) {
  std::map<std::string, std::string> out;
  for (const std::string& line : lines) {
    std::string lower;
    lower.resize(line.size());
    std::transform(line.begin(), line.end(), lower.begin(),
                   [](unsigned char c) { return std::tolower(c); });
    size_t colon = lower.find("set-cookie:");
    if (colon == std::string::npos) continue;
    std::string rest = line.substr(colon + 11);
    size_t semi = rest.find(';');
    std::string kv = rest.substr(0, semi);
    size_t start = kv.find_first_not_of(" \t");
    if (start == std::string::npos) continue;
    kv = kv.substr(start);
    size_t eq = kv.find('=');
    if (eq == std::string::npos) continue;
    std::string name = kv.substr(0, eq);
    std::string value = kv.substr(eq + 1);
    size_t ve = value.find_last_not_of(" \t\r\n");
    if (ve != std::string::npos) value = value.substr(0, ve + 1);
    out[percent_decode(name)] = percent_decode(value);
  }
  return out;
}

}  // namespace

bool run_login(App& app, const std::string& qr_path, int timeout_sec) {
  NetClient net(app);
  ensure_buvid4(app, net);
  NetResponse gen = net.get(
      "https://passport.bilibili.com/x/passport-login/web/qrcode/generate?source=main-fe-header");
  std::fprintf(stderr, "[INFO] generate response http=%ld size=%zu encoding=%s err=%s\n",
              gen.http_code, gen.body.size(), gen.content_encoding.c_str(), gen.curl_error.c_str());
  nlohmann::json gj;
  try {
    gj = nlohmann::json::parse(gen.body);
  } catch (...) {
    std::fprintf(stderr, "[ERR] bad generate response\n");
    std::fprintf(stderr, "[ERR] bad generate response head: %.*s\n",
                static_cast<int>(std::min<size_t>(160, gen.body.size())), gen.body.c_str());
    return false;
  }
  if (gj.value("code", -1) != 0 || !gj.contains("data")) {
    std::fprintf(stderr, "[ERR] generate qrcode code=%d\n", gj.value("code", -1));
    return false;
  }
  const auto& gdata = gj.at("data");
  std::string qr_url = gdata.value("url", "");
  std::string qr_key = gdata.value("qrcode_key", "");
  if (qr_url.empty() || qr_key.empty()) {
    std::fprintf(stderr, "[ERR] generate qrcode returned empty url/key\n");
    return false;
  }

  if (!render_qr_png(qr_url, qr_path)) {
    std::fprintf(stderr, "[WARN] qr png write failed: %s\n", qr_path.c_str());
  }
  std::printf("Scan this QR with the Bilibili app:\n");
  print_ascii_qr(qr_url);
  std::printf("QR PNG: %s\n", qr_path.c_str());

  const std::string poll_url = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll";
  auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(timeout_sec);
  bool scan_detected = false;
  while (std::chrono::steady_clock::now() < deadline) {
    NetResponse resp = net.get(poll_url, {{"qrcode_key", qr_key}, {"source", "main-fe-header"}});
    nlohmann::json pj;
    try {
      pj = nlohmann::json::parse(resp.body);
    } catch (...) {
      std::this_thread::sleep_for(std::chrono::seconds(2));
      continue;
    }
    if (pj.value("code", -1) != 0 || !pj.contains("data")) {
      std::this_thread::sleep_for(std::chrono::seconds(2));
      continue;
    }
    const auto& data = pj.at("data");
    long status = data.value("code", 86101);
    if (status == 0) {
      std::string redirect = data.value("url", pj.value("url", ""));
      auto url_cookies = parse_url_query(redirect);
      auto header_cookies = parse_set_cookies(resp.set_cookies);

      std::string sessdata = url_cookies["SESSDATA"];
      std::string jct = url_cookies["bili_jct"];
      std::string uid = url_cookies["DedeUserID"];
      bool sess_from_header = false;
      if (sessdata.empty()) { sessdata = header_cookies["SESSDATA"]; sess_from_header = true; }
      if (jct.empty()) jct = header_cookies["bili_jct"];
      if (uid.empty()) uid = header_cookies["DedeUserID"];
      if (sessdata.empty() || jct.empty() || uid.empty() || redirect.empty()) {
        if (!redirect.empty()) {
          NetResponse cb = net.get(redirect, {}, {{"Referer", "https://www.bilibili.com/"}});
          auto cb_cookies = parse_set_cookies(cb.set_cookies);
          if (sessdata.empty()) { sessdata = cb_cookies["SESSDATA"]; sess_from_header = true; }
          if (jct.empty()) jct = cb_cookies["bili_jct"];
          if (uid.empty()) uid = cb_cookies["DedeUserID"];
          for (const auto& [k, v] : cb_cookies) header_cookies[k] = v;
        }
      }
      if (sessdata.empty() || jct.empty() || uid.empty()) {
        std::fprintf(stderr,
                     "[ERR] login ok but cookies missing (url=%zu headers=%zu sess=%zu jct=%zu uid=%zu)\n",
                     url_cookies.size(), header_cookies.size(), sessdata.size(), jct.size(), uid.size());
        return false;
      }

      app.cookies["SESSDATA"] = sess_from_header ? sessdata : percent_encode(sessdata);
      app.cookies["bili_jct"] = jct;
      app.cookies["DedeUserID"] = uid;
      if (!url_cookies["DedeUserID__ckMd5"].empty()) {
        app.cookies["DedeUserID__ckMd5"] = url_cookies["DedeUserID__ckMd5"];
      }
      if (!header_cookies["buvid3"].empty()) app.cookies["buvid3"] = header_cookies["buvid3"];
      std::string ac_time = data.value("refresh_token", "");
      if (!ac_time.empty()) app.cookies["ac_time_value"] = ac_time;
      ensure_buvid3(app);
      if (!save_cookies_file(app)) {
        std::fprintf(stderr, "[ERR] save cookies failed\n");
        return false;
      }
      std::printf("[OK] login success, cookies saved: %s\n", app.paths.cookie_file.c_str());
      return true;
    }
    if (status == 86090) {
      if (!scan_detected) {
        std::printf("QR scanned, confirm login on phone...\n");
        scan_detected = true;
      }
    } else if (status == 86038) {
      std::fprintf(stderr, "[ERR] qrcode expired, run -login again\n");
      return false;
    }
    std::this_thread::sleep_for(std::chrono::seconds(2));
  }
  std::fprintf(stderr, "[ERR] login timed out\n");
  return false;
}

}  // namespace bili
