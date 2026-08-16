#include "wbi.h"

#include <chrono>

#include "net.h"
#include "urlcodec.h"

namespace bili {

std::vector<std::pair<std::string, std::string>> sign_params(
    NetClient& net, const std::vector<std::pair<std::string, std::string>>& params) {
  std::string img, sub;
  if (!net.wbi_keys(img, sub)) return params;

  std::vector<std::pair<std::string, std::string>> out = params;
  bool has_location = false;
  for (const auto& [k, v] : out) {
    if (k == "web_location") has_location = true;
  }
  if (!has_location) out.emplace_back("web_location", "1550101");
  out.emplace_back("wts",
                   std::to_string(std::chrono::duration_cast<std::chrono::seconds>(
                                      std::chrono::system_clock::now().time_since_epoch())
                                      .count()));

  std::string query = build_query_string(out);
  out.emplace_back("w_rid", md5_hex(query + img + sub));
  return out;
}

}  // namespace bili
