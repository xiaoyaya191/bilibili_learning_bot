#include "websearch.h"

#include <regex>

#include "urlcodec.h"

namespace bili {
namespace {

using json = nlohmann::json;

std::string strip_tags(const std::string& s) {
  std::string out = std::regex_replace(s, std::regex("<[^>]+>"), "");
  out = std::regex_replace(out, std::regex("\\s+"), " ");
  size_t a = out.find_first_not_of(' ');
  if (a == std::string::npos) return "";
  size_t b = out.find_last_not_of(' ');
  return out.substr(a, b - a + 1);
}

json parse_bing(const std::string& html, int limit) {
  json out = json::array();
  std::regex block_re(R"rx(<li class="b_algo".*?</li>)rx", std::regex::icase);
  std::smatch m;
  std::string rest = html;
  int count = 0;
  while (count < limit && std::regex_search(rest, m, block_re)) {
    std::string block = m[0];
    rest = m.suffix();
    std::smatch url_m, title_m, snip_m;
    std::string url, title, snip;
    if (std::regex_search(block, url_m, std::regex(R"rx(<a[^>]*href="(https?://[^"]+)")rx", std::regex::icase))) url = url_m[1];
    if (std::regex_search(block, title_m, std::regex(R"rx(<h2[^>]*>(.*?)</h2>)rx", std::regex::icase))) title = strip_tags(title_m[1]);
    if (std::regex_search(block, snip_m, std::regex(R"rx(<p[^>]*>(.*?)</p>)rx", std::regex::icase))) snip = strip_tags(snip_m[1]);
    if (!title.empty() && (!snip.empty() || !url.empty())) {
      out.push_back({{"title", title.substr(0, 120)}, {"snippet", snip.substr(0, 300)}, {"url", url}});
      count++;
    }
  }
  return out;
}

json parse_sogou(const std::string& html, int limit) {
  json out = json::array();
  std::regex block_re(R"rx(<h3[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>)rx", std::regex::icase);
  std::smatch m;
  std::string rest = html;
  int count = 0;
  while (count < limit && std::regex_search(rest, m, block_re)) {
    std::string url = m[1];
    std::string title = strip_tags(m[2]);
    rest = m.suffix();
    if (!title.empty()) {
      out.push_back({{"title", title.substr(0, 120)}, {"snippet", ""}, {"url", url}});
      count++;
    }
  }
  return out;
}

json parse_duckduckgo(const std::string& html, int limit) {
  json out = json::array();
  std::regex link_re(R"rx(class="result-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>)rx", std::regex::icase);
  std::smatch m;
  std::string rest = html;
  int count = 0;
  while (count < limit && std::regex_search(rest, m, link_re)) {
    std::string url = m[1];
    std::string title = strip_tags(m[2]);
    rest = m.suffix();
    if (!title.empty()) {
      out.push_back({{"title", title.substr(0, 120)}, {"snippet", ""}, {"url", url}});
      count++;
    }
  }
  return out;
}

json parse_wikipedia(NetClient& net, const std::string& query, int limit) {
  json out = json::array();
  NetResponse resp = net.raw_get(
      "https://en.wikipedia.org/w/api.php?action=opensearch&search=" +
      percent_encode(query) + "&limit=" + std::to_string(limit) + "&format=json",
      {{"User-Agent", "TermuxBot/1.0"}});
  try {
    auto j = json::parse(resp.body);
    const auto& titles = j.size() > 1 ? j[1] : json::array();
    const auto& snippets = j.size() > 2 ? j[2] : json::array();
    const auto& urls = j.size() > 3 ? j[3] : json::array();
    for (size_t i = 0; i < titles.size() && i < (size_t)limit; i++) {
      out.push_back({{"title", titles[i].value("", "")},
                     {"snippet", i < snippets.size() ? snippets[i].value("", "") : ""},
                     {"url", i < urls.size() ? urls[i].value("", "") : ""}});
    }
  } catch (...) {
  }
  return out;
}

}  // namespace

json web_search(NetClient& net, const std::string& query, int limit) {
  if (limit <= 0 || limit > 20) limit = 5;
  std::string q = percent_encode(query);
  std::vector<std::pair<std::string, std::string>> headers = {
      {"User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36"}};
  NetResponse bing = net.raw_get("https://www.bing.com/search?q=" + q + "&count=" + std::to_string(limit), headers);
  json out = parse_bing(bing.body, limit);
  if (!out.empty()) return out;

  NetResponse sogou = net.raw_get("https://m.sogou.com/web/sl?keyword=" + q + "&vr=1",
                                  {{"User-Agent", "Mozilla/5.0"}, {"Referer", "https://m.sogou.com/"}});
  out = parse_sogou(sogou.body, limit);
  if (!out.empty()) return out;

  NetResponse ddg = net.raw_get("https://lite.duckduckgo.com/lite/?q=" + q, headers);
  out = parse_duckduckgo(ddg.body, limit);
  if (!out.empty()) return out;

  return parse_wikipedia(net, query, limit);
}

}  // namespace bili
