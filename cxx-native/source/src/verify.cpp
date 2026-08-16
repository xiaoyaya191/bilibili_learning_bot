#include "verify.h"

namespace bili {
namespace {

using json = nlohmann::json;

}  // namespace

json verify_subtitle_ai(AiClient& ai, const std::string& title,
                        const std::string& subtitle) {
  std::string reply = ai.chat({
      {"system", "你是字幕校验助手。判断字幕是否与视频标题主题匹配，只输出 JSON：{is_match, confidence, reason}"},
      {"user", "标题: " + title + "\n字幕摘录: " + subtitle.substr(0, 4000)}});
  try {
    size_t a = reply.find('{');
    size_t b = reply.rfind('}');
    if (a != std::string::npos && b != std::string::npos && b >= a) {
      return json::parse(reply.substr(a, b - a + 1));
    }
  } catch (...) {
  }
  return {{"is_match", false}, {"confidence", 0.0}, {"reason", reply.substr(0, 200)}};
}

json verify_search_ai(AiClient& ai, const std::string& query, const json& results) {
  std::string context;
  int n = 0;
  for (const auto& r : results) {
    if (n++ >= 5) break;
    context += "- [" + r.value("title", "") + "] " + r.value("snippet", "") + " " +
               r.value("url", "") + "\n";
  }
  std::string reply = ai.chat({
      {"system", "你是搜索质量校验助手。过滤与查询无关的结果，输出 JSON：{kept, summary}"},
      {"user", "查询: " + query + "\n结果:\n" + context}});
  json kept = json::array();
  for (const auto& r : results) {
    if (kept.size() >= 3) break;
    kept.push_back(r);
  }
  try {
    size_t a = reply.find('{');
    size_t b = reply.rfind('}');
    if (a != std::string::npos && b != std::string::npos && b >= a) {
      auto j = json::parse(reply.substr(a, b - a + 1));
      if (j.contains("kept") && j["kept"].is_array()) kept = j["kept"];
      return {{"kept", kept}, {"summary", j.value("summary", "")}};
    }
  } catch (...) {
  }
  return {{"kept", kept}, {"summary", reply.substr(0, 300)}};
}

}  // namespace bili
