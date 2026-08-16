#pragma once

#include "config.h"

#include <mutex>
#include <string>
#include <utility>
#include <vector>

namespace bili {

struct NetResponse {
  long http_code = 0;
  std::string body;
  std::vector<std::string> set_cookies;
  std::string content_encoding;
  std::string curl_error;
};

class NetClient {
 public:
  explicit NetClient(const App& app);
  ~NetClient();

  // GET with optional query params/headers. Performs WBI signing when
  // signed=true (keys refreshed automatically).
  NetResponse get(const std::string& url,
                  const std::vector<std::pair<std::string, std::string>>& params = {},
                  const std::vector<std::pair<std::string, std::string>>& headers = {},
                  bool signed_request = false);

  NetResponse post(const std::string& url,
                   const std::vector<std::pair<std::string, std::string>>& form,
                   const std::vector<std::pair<std::string, std::string>>& headers = {});

  // Raw requests without Bilibili cookies/referer (for the AI gateway).
  NetResponse raw_get(const std::string& url,
                      const std::vector<std::pair<std::string, std::string>>& headers = {});
  NetResponse raw_post(const std::string& url,
                       const std::vector<std::pair<std::string, std::string>>& headers,
                       const std::string& body);

  // WBI keys (img, sub) with refresh-on-demand.
  bool wbi_keys(std::string& img, std::string& sub);

 private:
  NetResponse perform(const std::string& url, const std::string& query,
                      const std::vector<std::pair<std::string, std::string>>& headers,
                      const std::string& post_body, bool bili_style = true);
  void throttle();
  bool refresh_wbi_keys();
  std::string build_query(const std::vector<std::pair<std::string, std::string>>& params) const;

  const App& app_;
  std::mutex mu_;
  std::chrono::steady_clock::time_point last_call_{};
  std::chrono::steady_clock::time_point cooldown_until_{};
  bool first_call_ = true;
  double api_min_gap_ = 0.3;

  std::mutex wbi_mu_;
  std::string wbi_img_;
  std::string wbi_sub_;
  std::chrono::steady_clock::time_point wbi_at_{};
};

}  // namespace bili
