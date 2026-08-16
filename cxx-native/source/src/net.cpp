#include "net.h"

#include <curl/curl.h>

#ifdef BILI_USE_ZLIB
#include <zlib.h>
#endif

#include <algorithm>
#include <chrono>
#include <cctype>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <sstream>
#include <thread>

#include "cookies.h"
#include "dns.h"
#include "platform.h"
#include "urlcodec.h"
#include "wbi.h"

#include <nlohmann/json.hpp>

namespace bili {
namespace {

const char kUserAgent[] =
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0";

size_t write_cb(char* ptr, size_t size, size_t nmemb, void* userdata) {
  std::string* out = static_cast<std::string*>(userdata);
  out->append(ptr, size * nmemb);
  return size * nmemb;
}

size_t header_cb(char* buffer, size_t size, size_t nitems, void* userdata) {
  auto* out = static_cast<NetResponse*>(userdata);
  size_t len = size * nitems;
  std::string line(buffer, len);
  std::string lower;
  lower.resize(line.size());
  std::transform(line.begin(), line.end(), lower.begin(),
                 [](unsigned char c) { return std::tolower(c); });
  if (lower.rfind("set-cookie:", 0) == 0) {
    out->set_cookies.push_back(line);
  }
  if (lower.rfind("content-encoding:", 0) == 0) {
    std::string v = line.substr(17);
    size_t e = v.find_last_not_of(" \t\r\n");
    if (e != std::string::npos) v = v.substr(0, e + 1);
    if (!v.empty()) out->content_encoding = v;
  }
  return len;
}

std::string lower_ascii(const std::string& s) {
  std::string out = s;
  std::transform(out.begin(), out.end(), out.begin(),
                 [](unsigned char c) { return std::tolower(c); });
  return out;
}

#ifdef BILI_USE_ZLIB
std::string gunzip_body(const std::string& in) {
  if (in.size() < 2 || static_cast<unsigned char>(in[0]) != 0x1f ||
      static_cast<unsigned char>(in[1]) != 0x8b) {
    return in;
  }
  z_stream zs{};
  if (inflateInit2(&zs, 16 + MAX_WBITS) != Z_OK) return in;
  std::string out;
  char buf[16384];
  zs.next_in = reinterpret_cast<Bytef*>(const_cast<char*>(in.data()));
  zs.avail_in = static_cast<uInt>(in.size());
  int rc = Z_OK;
  do {
    zs.next_out = reinterpret_cast<Bytef*>(buf);
    zs.avail_out = sizeof(buf);
    rc = inflate(&zs, Z_NO_FLUSH);
    if (rc != Z_OK && rc != Z_STREAM_END) break;
    out.append(buf, sizeof(buf) - zs.avail_out);
  } while (rc != Z_STREAM_END);
  inflateEnd(&zs);
  return rc == Z_STREAM_END ? out : in;
}
#else
std::string gunzip_body(const std::string& in) { return in; }
#endif

bool is_transient_curl(CURLcode code) {
  switch (code) {
    case CURLE_COULDNT_RESOLVE_HOST:
    case CURLE_COULDNT_CONNECT:
    case CURLE_OPERATION_TIMEDOUT:
    case CURLE_RECV_ERROR:
    case CURLE_SEND_ERROR:
    case CURLE_GOT_NOTHING:
    case CURLE_PARTIAL_FILE:
    case CURLE_READ_ERROR:
      return true;
    default:
      return false;
  }
}

std::mutex g_bili_cooldown_mu;
std::chrono::steady_clock::time_point g_bili_cooldown_until{};

void trigger_bili_cooldown() {
  std::lock_guard<std::mutex> lock(g_bili_cooldown_mu);
  auto now = std::chrono::steady_clock::now();
  if (now >= g_bili_cooldown_until) {
    std::random_device rd;
    int extra = 90 + (int)(rd() % 91);
    g_bili_cooldown_until = now + std::chrono::seconds(extra);
  }
}

void wait_bili_cooldown() {
  std::lock_guard<std::mutex> lock(g_bili_cooldown_mu);
  auto now = std::chrono::steady_clock::now();
  if (now < g_bili_cooldown_until) {
    std::this_thread::sleep_for(g_bili_cooldown_until - now + std::chrono::milliseconds(300));
  }
}

}  // namespace

NetClient::NetClient(const App& app) : app_(app) {
  api_min_gap_ = get_double(app_, "speed", "api_min_gap", 0.3);
  if (api_min_gap_ <= 0) api_min_gap_ = 0.3;
}

NetClient::~NetClient() = default;

std::string NetClient::build_query(
    const std::vector<std::pair<std::string, std::string>>& params) const {
  return build_query_string(params);
}

void NetClient::throttle() {
  wait_bili_cooldown();
  std::lock_guard<std::mutex> lock(mu_);
  auto now = std::chrono::steady_clock::now();
  if (now < cooldown_until_) {
    std::this_thread::sleep_for(cooldown_until_ - now + std::chrono::milliseconds(500));
    now = std::chrono::steady_clock::now();
  }
  if (first_call_) {
    first_call_ = false;
    last_call_ = now;
    return;
  }
  std::random_device rd;
  double jitter = ((double)(rd() % 1000) / 1000.0) * api_min_gap_;
  auto gap = std::chrono::duration<double>(api_min_gap_ + jitter);
  auto wait = gap - (now - last_call_);
  if (wait > std::chrono::milliseconds(10)) {
    std::this_thread::sleep_for(wait);
  }
  last_call_ = std::chrono::steady_clock::now();
}

NetResponse NetClient::perform(const std::string& url, const std::string& query,
                               const std::vector<std::pair<std::string, std::string>>& headers,
                               const std::string& post_body, bool bili_style) {
  std::lock_guard<std::mutex> lock(mu_);
  std::string full = url;
  if (!query.empty()) {
    full += (full.find('?') == std::string::npos ? "?" : "&") + query;
  }

  std::string host;
  size_t scheme_end = full.find("://");
  if (scheme_end != std::string::npos) {
    size_t path_start = full.find('/', scheme_end + 3);
    host = full.substr(scheme_end + 3, path_start - scheme_end - 3);
  }
  std::string host_only = host;
  size_t colon = host_only.rfind(':');
  if (colon != std::string::npos && host_only.find(':') == colon) {
    host_only = host_only.substr(0, colon);
  }
  struct in_addr literal_addr;
#ifdef _WIN32
  bool is_literal = posix_inet_pton(host_only.c_str(), &literal_addr) == 1;
#else
  bool is_literal = posix_inet_pton(host_only.c_str(), &literal_addr) == 1;
#endif
  std::vector<std::string> ips;
  curl_slist* resolve = nullptr;
  bool force_aliyun_dns = get_bool(app_, "network", "force_aliyun_dns", false);
  if (force_aliyun_dns && !is_literal && !host_only.empty()) {
    ips = resolve_aliyun_v4(host_only);
    for (const auto& ip : ips) {
      resolve = curl_slist_append(resolve, (host_only + ":443:" + ip).c_str());
      resolve = curl_slist_append(resolve, (host_only + ":80:" + ip).c_str());
    }
  }

  NetResponse out;
  CURL* curl = curl_easy_init();
  if (!curl) return out;
  curl_slist* header_list = nullptr;
  header_list = curl_slist_append(header_list, "Accept: */*");
  header_list = curl_slist_append(header_list, ("User-Agent: " + std::string(kUserAgent)).c_str());
  if (bili_style) {
    std::string cookies = cookie_header(app_);
    if (!cookies.empty()) {
      header_list = curl_slist_append(header_list, ("Cookie: " + cookies).c_str());
    }
    bool has_referer = false;
    for (const auto& [k, v] : headers) {
      if (lower_ascii(k) == "referer") {
        has_referer = true;
        break;
      }
    }
    if (!has_referer) {
      header_list = curl_slist_append(header_list, "Referer: https://www.bilibili.com");
    }
  }
  for (const auto& [k, v] : headers) {
    header_list = curl_slist_append(header_list, (k + ": " + v).c_str());
  }

  curl_easy_setopt(curl, CURLOPT_URL, full.c_str());
  char errbuf[CURL_ERROR_SIZE] = {0};
  curl_easy_setopt(curl, CURLOPT_ERRORBUFFER, errbuf);

  std::string ca_file_own;
  if (const char* env_ca = std::getenv("BILI_CA_BUNDLE")) ca_file_own = env_ca;
  if (ca_file_own.empty()) {
    std::string data_ca = app_.paths.data_dir + "/cacert.pem";
    for (const std::string& cand : {std::string("cacert.pem"), data_ca}) {
      if (FILE* f = std::fopen(cand.c_str(), "rb")) {
        std::fclose(f);
        ca_file_own = cand;
        break;
      }
    }
  }
  if (!ca_file_own.empty()) {
    curl_easy_setopt(curl, CURLOPT_CAINFO, ca_file_own.c_str());
  }
  bool verify_ssl = get_bool(app_, "network", "verify_ssl", false);
  if (!verify_ssl) {
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 0L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, 0L);
  }
#if defined(__ANDROID__)
  else {
    curl_easy_setopt(curl, CURLOPT_CAPATH, "/system/etc/security/cacerts");
  }
#endif
  curl_easy_setopt(curl, CURLOPT_HTTPHEADER, header_list);
  curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_cb);
  curl_easy_setopt(curl, CURLOPT_WRITEDATA, &out.body);
  curl_easy_setopt(curl, CURLOPT_HEADERFUNCTION, header_cb);
  curl_easy_setopt(curl, CURLOPT_HEADERDATA, &out);
  curl_easy_setopt(curl, CURLOPT_ACCEPT_ENCODING, "");
#if defined(__ANDROID__)
  curl_easy_setopt(curl, CURLOPT_HTTP_CONTENT_DECODING, 0L);
#endif
  curl_easy_setopt(curl, CURLOPT_TIMEOUT, 25L);
  curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 10L);
  curl_easy_setopt(curl, CURLOPT_IPRESOLVE, CURL_IPRESOLVE_V4);
  curl_easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
  curl_easy_setopt(curl, CURLOPT_MAXREDIRS, 5L);
  curl_easy_setopt(curl, CURLOPT_HTTP_VERSION, CURL_HTTP_VERSION_2TLS);
  curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
  const auto& proxy_cfg = app_.config.value("network", nlohmann::json::object()).value("proxy", nlohmann::json::object());
  if (proxy_cfg.value("enabled", false)) {
    std::string proxy_url = proxy_cfg.value("url", "");
    if (!proxy_url.empty()) curl_easy_setopt(curl, CURLOPT_PROXY, proxy_url.c_str());
  } else {
    const char* env_proxy = std::getenv("HTTPS_PROXY");
    if (!env_proxy || !*env_proxy) env_proxy = std::getenv("HTTP_PROXY");
    if (env_proxy && *env_proxy) curl_easy_setopt(curl, CURLOPT_PROXY, env_proxy);
  }
  if (resolve) {
    curl_easy_setopt(curl, CURLOPT_RESOLVE, resolve);
  }
  if (!post_body.empty()) {
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, post_body.c_str());
  }

  bool dns_fallback_done = false;
  for (int attempt = 0; attempt < 2; ++attempt) {
    if (resolve) curl_easy_setopt(curl, CURLOPT_RESOLVE, resolve);
    errbuf[0] = 0;
    out.body.clear();
    out.http_code = 0;
    out.set_cookies.clear();
    out.content_encoding.clear();
    out.curl_error.clear();
    CURLcode rc = curl_easy_perform(curl);
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &out.http_code);
    out.curl_error = errbuf[0] ? errbuf : curl_easy_strerror(rc);
    if (!out.content_encoding.empty() &&
        lower_ascii(out.content_encoding).find("gzip") != std::string::npos) {
      out.body = gunzip_body(out.body);
    }
    if (rc != CURLE_COULDNT_RESOLVE_HOST || dns_fallback_done || is_literal ||
        host_only.empty() || force_aliyun_dns) {
      (void)rc;
      break;
    }
    ips = resolve_aliyun_v4(host_only);
    if (ips.empty()) break;
    for (const auto& ip : ips) {
      resolve = curl_slist_append(resolve, (host_only + ":443:" + ip).c_str());
      resolve = curl_slist_append(resolve, (host_only + ":80:" + ip).c_str());
    }
    dns_fallback_done = true;
  }
  curl_easy_cleanup(curl);
  curl_slist_free_all(header_list);
  if (resolve) curl_slist_free_all(resolve);
  return out;
}

NetResponse NetClient::get(
    const std::string& url,
    const std::vector<std::pair<std::string, std::string>>& params,
    const std::vector<std::pair<std::string, std::string>>& headers, bool signed_request) {
  NetResponse last;
  for (int attempt = 0; attempt < 4; attempt++) {
    throttle();
    std::vector<std::pair<std::string, std::string>> p = params;
    if (signed_request) {
      p = sign_params(*this, p);
    }
    NetResponse resp = perform(url, build_query(p), headers, "", true);
    last = resp;
    if (resp.body.find("\"code\":-799") != std::string::npos) {
      trigger_bili_cooldown();
      if (attempt < 3) {
        std::this_thread::sleep_for(std::chrono::seconds(3 + attempt * 3));
        continue;
      }
    }
    if (resp.http_code == 429) {
      std::this_thread::sleep_for(std::chrono::seconds(1 << attempt));
      continue;
    }
    break;
  }
  return last;
}

NetResponse NetClient::post(
    const std::string& url,
    const std::vector<std::pair<std::string, std::string>>& form,
    const std::vector<std::pair<std::string, std::string>>& headers) {
  std::vector<std::pair<std::string, std::string>> h = headers;
  h.emplace_back("Content-Type", "application/x-www-form-urlencoded");
  NetResponse last;
  for (int attempt = 0; attempt < 4; attempt++) {
    throttle();
    NetResponse resp = perform(url, "", h, build_query(form), true);
    last = resp;
    if (resp.body.find("\"code\":-799") != std::string::npos) {
      trigger_bili_cooldown();
      if (attempt < 3) {
        std::this_thread::sleep_for(std::chrono::seconds(3 + attempt * 3));
        continue;
      }
    }
    if (resp.http_code == 429) {
      std::this_thread::sleep_for(std::chrono::seconds(1 << attempt));
      continue;
    }
    break;
  }
  return last;
}

NetResponse NetClient::raw_get(
    const std::string& url,
    const std::vector<std::pair<std::string, std::string>>& headers) {
  return perform(url, "", headers, "", false);
}

NetResponse NetClient::raw_post(
    const std::string& url,
    const std::vector<std::pair<std::string, std::string>>& headers,
    const std::string& body) {
  return perform(url, "", headers, body, false);
}

bool NetClient::wbi_keys(std::string& img, std::string& sub) {
  std::lock_guard<std::mutex> lock(wbi_mu_);
  auto now = std::chrono::steady_clock::now();
  if (!wbi_img_.empty() && now - wbi_at_ < std::chrono::hours(1)) {
    img = wbi_img_;
    sub = wbi_sub_;
    return true;
  }
  if (!refresh_wbi_keys()) return false;
  img = wbi_img_;
  sub = wbi_sub_;
  return true;
}

bool NetClient::refresh_wbi_keys() {
  NetResponse resp = get("https://api.bilibili.com/x/web-interface/nav");
  try {
    auto j = nlohmann::json::parse(resp.body);
    if (j.value("code", -1) != 0) return false;
    const auto& data = j.at("data");
    const auto& wbi = data.at("wbi_img");
    std::string img_url = wbi.value("img_url", "");
    std::string sub_url = wbi.value("sub_url", "");
    auto filename = [](const std::string& u) -> std::string {
      size_t slash = u.rfind('/');
      size_t dot = u.rfind('.');
      if (slash == std::string::npos || dot == std::string::npos || dot <= slash) return "";
      return u.substr(slash + 1, dot - slash - 1);
    };
    wbi_img_ = filename(img_url);
    wbi_sub_ = filename(sub_url);
    wbi_at_ = std::chrono::steady_clock::now();
    return !wbi_img_.empty() && !wbi_sub_.empty();
  } catch (...) {
    return false;
  }
}

}  // namespace bili
