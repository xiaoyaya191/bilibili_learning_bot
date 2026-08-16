#include "platform_adapter.h"

#include <regex>

#include "api.h"

namespace bili {
namespace {

using json = nlohmann::json;

std::string bvid_from_url(const std::string& url) {
  std::smatch m;
  if (std::regex_search(url, m, std::regex(R"(BV[0-9A-Za-z]{10})"))) return m[0];
  return "";
}

}  // namespace

json platform_probe_url(const std::string& url) {
  if (url.find("bilibili.com") != std::string::npos) {
    std::string bvid = bvid_from_url(url);
    return {{"platform", "bilibili"}, {"bvid", bvid}, {"supported", !bvid.empty()}};
  }
  if (url.find("youtube.com") != std::string::npos || url.find("youtu.be") != std::string::npos) {
    return {{"platform", "youtube"}, {"bvid", ""}, {"supported", true}};
  }
  return {{"platform", "unknown"}, {"bvid", ""}, {"supported", false}};
}

json platform_download_plan(App& app, NetClient& net, const std::string& url) {
  json probe = platform_probe_url(url);
  if (probe.value("platform", "") == "bilibili") {
    std::string bvid = probe.value("bvid", "");
    std::string err;
    VideoInfo info = video_info(net, bvid, 0, err);
    if (info.bvid.empty()) return {{"ok", false}, {"platform", "bilibili"}, {"message", err}};
    return {{"ok", true}, {"platform", "bilibili"}, {"bvid", bvid},
            {"title", info.title}, {"plan", "bilibili_api"}};
  }
  if (probe.value("platform", "") == "youtube") {
    return {{"ok", true}, {"platform", "youtube"}, {"plan", "yt_dlp"}};
  }
  return {{"ok", false}, {"platform", "unknown"}, {"message", "unsupported platform"}};
}

}  // namespace bili
