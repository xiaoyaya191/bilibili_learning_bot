#pragma once

#include <string>

#include "ai.h"
#include "api.h"
#include "net.h"

namespace bili {

struct VideoAnalysis {
  VideoInfo info;
  std::string subtitles;
  std::string danmaku;
  std::string bili_summary;
  std::string ai_summary;
};

// Downloads subtitles (player wbi v2 + subtitle JSON) and returns the joined
// subtitle lines.
std::string fetch_subtitles(NetClient& net, const VideoInfo& info);

// Downloads danmaku from the legacy XML endpoint and returns up to limit
// lines of comment text.
std::string fetch_danmaku_text(NetClient& net, long long cid, int limit = 200);

// Full pipeline: info + subtitles + danmaku + Bilibili AI conclusion + our AI
// summary. On failure, error describes the first blocking failure.
bool analyze_video(App& app, NetClient& net, AiClient& ai, const std::string& bvid,
                   VideoAnalysis& out, std::string& error);

struct DeepResult {
  std::string bvid;
  std::string title;
  std::string summary;
};

// 深度研究：搜索 B 站视频，逐个分析并把笔记写入知识库。
bool deep_dive(App& app, NetClient& net, AiClient& ai, const std::string& keyword,
               int count, std::vector<DeepResult>& out, std::string& error);

}  // namespace bili
