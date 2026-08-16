#include "analysis.h"

#include <algorithm>
#include <regex>
#include <sstream>
#include "kb.h"
#include "urlcodec.h"

namespace bili {
namespace {

std::string trim(const std::string& s) {
  size_t a = s.find_first_not_of(" \t\r\n");
  if (a == std::string::npos) return "";
  size_t b = s.find_last_not_of(" \t\r\n");
  return s.substr(a, b - a + 1);
}

std::string truncate(const std::string& s, size_t n) {
  if (s.size() <= n) return s;
  return s.substr(0, n) + "...";
}

}  // namespace

std::string fetch_subtitles(NetClient& net, const VideoInfo& info) {
  if (info.aid == 0 || info.cid == 0) return "";

  auto pick_url = [](const nlohmann::json& j) -> std::string {
    const auto& subs = j.value("data", nlohmann::json::object())
                            .value("subtitle", nlohmann::json::object())
                            .value("subtitles", nlohmann::json::array());
    for (const auto& s : subs) {
      std::string url = s.value("subtitle_url", "");
      if (url.empty()) url = s.value("subtitle_url_v2", "");
      if (!url.empty()) return url;
    }
    return "";
  };
  auto fetch_body = [&](const std::string& url) -> std::string {
    std::string u = url;
    if (u.rfind("//", 0) == 0) u = "https:" + u;
    NetResponse sub = net.raw_get(u);
    std::ostringstream out;
    try {
      auto j = nlohmann::json::parse(sub.body);
      const auto& body = j.value("body", nlohmann::json::array());
      int count = 0;
      for (const auto& line : body) {
        std::string text = line.value("content", "");
        if (!text.empty()) {
          out << text << "\n";
          if (++count >= 500) break;
        }
      }
    } catch (...) {
    }
    return out.str();
  };

  NetResponse player =
      net.get("https://api.bilibili.com/x/player/wbi/v2",
              {{"aid", std::to_string(info.aid)}, {"cid", std::to_string(info.cid)}},
              {}, /*signed_request=*/true);
  std::string subtitle_url;
  try {
    subtitle_url = pick_url(nlohmann::json::parse(player.body));
  } catch (...) {
  }
  if (subtitle_url.empty()) {
    NetResponse player2 =
        net.get("https://api.bilibili.com/x/player/v2",
                {{"aid", std::to_string(info.aid)}, {"cid", std::to_string(info.cid)}});
    try {
      subtitle_url = pick_url(nlohmann::json::parse(player2.body));
    } catch (...) {
    }
  }
  if (subtitle_url.empty()) return "";
  return fetch_body(subtitle_url);
}

std::string fetch_danmaku_text(NetClient& net, long long cid, int limit) {
  if (cid == 0) return "";
  std::string url = "https://comment.bilibili.com/" + std::to_string(cid) + ".xml";
  NetResponse resp = net.raw_get(url);
  static const std::regex re(R"(<d p="[^"]*">(.*?)</d>)");
  std::ostringstream out;
  int count = 0;
  for (std::sregex_iterator it(resp.body.begin(), resp.body.end(), re), end; it != end && count < limit;
       ++it, ++count) {
    out << (*it)[1].str() << "\n";
  }
  return out.str();
}

bool analyze_video(App& app, NetClient& net, AiClient& ai, const std::string& bvid,
                   VideoAnalysis& out, std::string& error) {
	out.info = video_info(net, bvid, 0, error);
	if (!error.empty() || out.info.aid == 0) {
		if (error.empty()) error = "video info empty";
		return false;
	}
  out.subtitles = fetch_subtitles(net, out.info);
  out.danmaku = fetch_danmaku_text(net, out.info.cid);
  out.bili_summary = video_ai_summary(net, out.info);

  std::ostringstream prompt;
  prompt << "请基于以下视频信息写一份简明学习笔记（中文，500 字以内）：\n";
  prompt << "标题: " << out.info.title << "\n";
  prompt << "简介: " << truncate(out.info.desc, 1200) << "\n";
  if (!out.subtitles.empty()) {
    prompt << "字幕摘录:\n" << truncate(out.subtitles, 6000) << "\n";
  }
  if (!out.danmaku.empty()) {
    prompt << "弹幕摘录:\n" << truncate(out.danmaku, 3000) << "\n";
  }
  if (!out.bili_summary.empty()) {
    prompt << "B站AI总结:\n" << truncate(out.bili_summary, 4000) << "\n";
  }
  out.ai_summary = ai.chat(
      {{"system", "你是一个严谨的视频学习助手，只依据提供的材料总结，不编造。"},
       {"user", prompt.str()}});
  if (out.ai_summary.empty()) {
    error = "AI summary empty";
    return false;
  }
  return true;
}


bool deep_dive(App& app, NetClient& net, AiClient& ai, const std::string& keyword,
               int count, std::vector<DeepResult>& out, std::string& error) {
  if (count <= 0) count = 3;
  if (count > 10) count = 10;
  NetResponse resp = net.get("https://api.bilibili.com/x/web-interface/search/type",
                             {{"search_type", "video"}, {"keyword", keyword}, {"page", "1"}},
                             {{"Referer", "https://search.bilibili.com/"}});
  long long code = -1;
  try {
    code = nlohmann::json::parse(resp.body).value("code", -1LL);
  } catch (...) {
    error = "search response parse failed";
    return false;
  }
  if (code != 0) {
    error = "search code=" + std::to_string(code);
    return false;
  }

  std::vector<std::pair<std::string, std::string>> videos;
  try {
    auto j = nlohmann::json::parse(resp.body);
    const auto& result = j["data"].value("result", nlohmann::json::array());
    for (const auto& v : result) {
      std::string bvid = v.value("bvid", "");
      std::string title = v.value("title", "");
      if (!bvid.empty()) videos.emplace_back(bvid, title);
      if ((int)videos.size() >= count) break;
    }
  } catch (...) {
    error = "search result parse failed";
    return false;
  }
  if (videos.empty()) {
    error = "no videos found";
    return false;
  }

  KnowledgeBase kb(app.paths.knowledge_metadata_file, app.paths.knowledge_base_dir);
  kb.load();
  for (const auto& [bvid, title] : videos) {
    VideoAnalysis va;
    std::string aerr;
    if (!analyze_video(app, net, ai, bvid, va, aerr)) {
      // AI 总结失败时降级：优先 B 站 AI 总结，其次字幕摘录，不中断整个深度研究。
      std::string fallback = va.bili_summary;
      if (fallback.empty()) fallback = truncate(va.subtitles, 1200);
      if (fallback.empty()) {
        error = bvid + ": " + aerr;
        return false;
      }
      va.ai_summary = fallback;
    }
    std::string cat = detect_category(va.info.title, va.ai_summary);
    kb.add_note(cat, va.info.title, bvid, va.ai_summary);
    kb.add_note(cat, va.info.title, bvid, va.ai_summary, app.config);
    out.push_back({bvid, va.info.title, truncate(va.ai_summary, 200)});
  }
  return true;
}

}  // namespace bili
