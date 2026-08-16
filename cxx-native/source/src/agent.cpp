#include "agent.h"

#include <algorithm>
#include <chrono>
#include <filesystem>
#include "fscompat.h"
#include <fstream>
#include <regex>
#include "platform.h"
#include <sstream>

#include "analysis.h"
#include "api.h"
#include "kb.h"
#include "platform.h"
namespace fs = std::filesystem;

namespace bili {
namespace {
long long now_epoch() {
  return std::chrono::duration_cast<std::chrono::seconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

std::string now_iso() {
  std::time_t t = std::time(nullptr);
  std::tm tm{};
  localtime_r(&t, &tm);
  char buf[32];
  std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &tm);
  return buf;
}



using json = nlohmann::json;

std::string read_file(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) return "";
  std::ostringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

bool write_file(const std::string& path, const std::string& content) {
  std::error_code ec;
  fs::create_directories(fs::path(path).parent_path(), ec);
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) return false;
  out << content;
  return out.good();
}

json read_json_file(const std::string& path) {
  std::string raw = read_file(path);
  if (raw.empty()) return json::object();
  try {
    auto j = json::parse(raw);
    return j.is_object() ? j : json::object();
  } catch (...) {
    return json::object();
  }
}

bool write_json_file(const std::string& path, const json& v) {
  return write_file(path, v.dump(2));
}

json load_sessions(const App& app) {
  return read_json_file(app.paths.data_dir + "/learning_sessions.json");
}

void save_session(const App& app, const std::string& sid, const json& session) {
  json data = load_sessions(app);
  data[sid] = session;
  write_json_file(app.paths.data_dir + "/learning_sessions.json", data);
}

json tools_for(const std::string& type) {
  if (type == "quiz") {
    return json::array({
        {{"type", "function"},
         {"function", {{"name", "get_video_content"},
                       {"description", "获取B站视频的字幕文本内容"},
                       {"parameters", {{"type", "object"},
                                       {"properties", {{"bvid", {{"type", "string"}}}},
                                        {"required", json::array({"bvid"})}}}}}}},
        {{"type", "function"},
         {"function", {{"name", "list_kb_files"},
                       {"description", "列出知识库中的可用文件"},
                       {"parameters", {{"type", "object"}, {"properties", json::object()},
                                       {"required", json::array()}}}}}},
        {{"type", "function"},
         {"function", {{"name", "read_kb_file"},
                       {"description", "读取知识库文件内容"},
                       {"parameters", {{"type", "object"},
                                       {"properties", {{"filename", {{"type", "string"}}}},
                                        {"required", json::array({"filename"})}}}}}}},
        {{"type", "function"},
         {"function", {{"name", "finalize_quiz"},
                       {"description", "完成出题并保存题目"},
                       {"parameters", {{"type", "object"},
                                       {"properties",
                                        {{"source_title", {{"type", "string"}}},
                                         {"quiz_content", {{"type", "string"}}},
                                         {"question_count", {{"type", "integer"}}},
                                         {"difficulty", {{"type", "string"}}}},
                                        {"required", json::array({"source_title", "quiz_content"})}}}}}}},
    });
  }
  return json::array({
      {{"type", "function"},
       {"function", {{"name", "search_bilibili"},
                     {"description", "搜索B站视频"},
                     {"parameters", {{"type", "object"},
                                     {"properties",
                                      {{"query", {{"type", "string"}}},
                                       {"count", {{"type", "integer"}}}},
                                      {"required", json::array({"query"})}}}}}}},
      {{"type", "function"},
       {"function", {{"name", "get_video_content"},
                     {"description", "获取B站视频的字幕文本内容"},
                     {"parameters", {{"type", "object"},
                                     {"properties", {{"bvid", {{"type", "string"}}}},
                                      {"required", json::array({"bvid"})}}}}}}},
      {{"type", "function"},
       {"function", {{"name", "read_kb_file"},
                     {"description", "读取知识库文件内容"},
                     {"parameters", {{"type", "object"},
                                     {"properties", {{"filename", {{"type", "string"}}}},
                                      {"required", json::array({"filename"})}}}}}}},
      {{"type", "function"},
       {"function", {{"name", "finalize_deep_dive"},
                     {"description", "完成深入学习并保存报告"},
                     {"parameters", {{"type", "object"},
                                     {"properties",
                                      {{"topic", {{"type", "string"}}},
                                       {"report", {{"type", "string"}}}},
                                      {"required", json::array({"topic", "report"})}}}}}}},
  });
}

std::string call_name(const json& tool_call) {
  return tool_call.value("function", json::object()).value("name", "");
}

std::string call_args(const json& tool_call) {
  return tool_call.value("function", json::object()).value("arguments", "{}");
}

json parse_args(const std::string& raw) {
  try {
    auto j = json::parse(raw);
    return j.is_object() ? j : json::object();
  } catch (...) {
    return json::object();
  }
}

std::string strip_html(const std::string& s) {
  return std::regex_replace(s, std::regex("<[^>]+>"), "");
}

std::string search_bilibili_tool(NetClient& net, const std::string& query, int count) {
  NetResponse resp = net.get("https://api.bilibili.com/x/web-interface/search/type",
                             {{"search_type", "video"}, {"keyword", query}, {"page", "1"}},
                             {{"Referer", "https://search.bilibili.com/"}});
  try {
    auto j = json::parse(resp.body);
    json out = json::array();
    const auto& result = j.value("data", json::object()).value("result", json::array());
    int n = 0;
    for (const auto& v : result) {
      if (n++ >= count) break;
      out.push_back({{"bvid", v.value("bvid", "")}, {"title", strip_html(v.value("title", ""))},
                     {"author", v.value("author", "")}, {"duration", v.value("duration", "")}});
    }
    return out.dump();
  } catch (...) {
    return "[]";
  }
}

std::string video_content_tool(App& app, NetClient& net, AiClient& ai,
                               const std::string& bvid) {
  VideoAnalysis va;
  std::string err;
  if (!analyze_video(app, net, ai, bvid, va, err)) return "{\"error\":\"" + err + "\"}";
  json out = {{"bvid", bvid}, {"title", va.info.title}, {"desc", va.info.desc},
              {"subtitles", va.subtitles.substr(0, 4000)}, {"ai_summary", va.ai_summary}};
  return out.dump();
}

std::string read_kb_tool(const App& app, const std::string& filename) {
  std::string p = app.paths.knowledge_base_dir + "/" + filename;
  std::string content = read_file(p);
  if (content.empty()) content = read_file(app.paths.knowledge_base_dir + "/custom/" + filename);
  return content.empty() ? "{\"error\":\"file not found\"}" : content;
}

std::string list_kb_tool(const App& app) {
  json out = json::array();
  std::error_code ec;
  for (const auto& e : fs::recursive_directory_iterator(app.paths.knowledge_base_dir, ec)) {
    if (ec) break;
    if (e.is_regular_file() && e.path().extension() == ".md") {
      out.push_back(fs::relative(e.path(), app.paths.knowledge_base_dir).generic_string());
    }
  }
  return out.dump();
}

std::string finalize_report(App& app, const std::string& topic, const std::string& report) {
  std::string dir = app.paths.knowledge_base_dir + "/deep_dive";
  std::error_code ec;
  fs::create_directories(dir, ec);
  std::string safe = topic;
  std::replace_if(safe.begin(), safe.end(), [](char c) { return c == '/' || c == '\\' || c == ':'; }, '_');
  std::string path = dir + "/" + safe + ".md";
  if (!write_file(path, "# " + topic + "\n\n" + report + "\n")) return "{\"error\":\"write failed\"}";
  KnowledgeBase kb(app.paths.knowledge_metadata_file, app.paths.knowledge_base_dir);
  kb.load();
  kb.add_note("deep_dive", topic, "", report, app.config);
  return "{\"ok\":true,\"path\":\"" + path + "\"}";
}

std::string finalize_quiz(App& app, const std::string& title, const std::string& content) {
  std::string dir = app.paths.knowledge_base_dir + "/quizzes";
  std::error_code ec;
  fs::create_directories(dir, ec);
  std::string safe = title;
  std::replace_if(safe.begin(), safe.end(), [](char c) { return c == '/' || c == '\\' || c == ':'; }, '_');
  std::string path = dir + "/" + safe + ".md";
  if (!write_file(path, "# " + title + "\n\n" + content + "\n")) return "{\"error\":\"write failed\"}";
  return "{\"ok\":true,\"path\":\"" + path + "\"}";
}

std::string execute_tool(App& app, NetClient& net, AiClient& ai,
                         const std::string& name, const json& args) {
  if (name == "search_bilibili") {
    return search_bilibili_tool(net, args.value("query", ""), args.value("count", 8));
  }
  if (name == "get_video_content") {
    return video_content_tool(app, net, ai, args.value("bvid", ""));
  }
  if (name == "read_kb_file") {
    return read_kb_tool(app, args.value("filename", ""));
  }
  if (name == "list_kb_files") {
    return list_kb_tool(app);
  }
  if (name == "finalize_deep_dive") {
    return finalize_report(app, args.value("topic", ""), args.value("report", ""));
  }
  if (name == "finalize_quiz") {
    return finalize_quiz(app, args.value("source_title", ""), args.value("quiz_content", ""));
  }
  return "{\"error\":\"unknown tool\"}";
}

}  // namespace

json run_learning_agent(App& app, NetClient& net, AiClient& ai,
                        const std::string& type, const std::string& topic,
                        const std::string& user_msg, const std::string& session_id,
                        int max_steps) {
  std::string sid = session_id.empty() ? type + "-" + std::to_string(now_epoch()) : session_id;
  json sessions = load_sessions(app);
  json session = sessions.value(sid, json::object());
  if (!session.is_object()) session = json::object();
  session["session_id"] = sid;
  session["type"] = type;
  session["topic"] = topic;
  json messages = session.value("messages", json::array());
  if (!messages.is_array()) messages = json::array();
  std::string prompt = user_msg.empty() ? topic : user_msg;
  if (!prompt.empty()) messages.push_back({{"role", "user"}, {"content", prompt}});

  std::string system = type == "quiz"
      ? "You are an AI quiz tutor. Generate questions from supplied content and call finalize_quiz when done."
      : "You are a deep learning agent. Search Bilibili, read video content, and call finalize_deep_dive with a structured report when you have enough material.";

  json tools = tools_for(type);
  json ai_msgs = json::array();
  ai_msgs.push_back({{"role", "system"}, {"content", system}});
  for (const auto& m : messages) ai_msgs.push_back(m);
  std::string reply;
  for (int step = 0; step < max_steps; step++) {
    json msg = ai.chat_tools_json(ai_msgs, tools);
    std::string content = msg.value("content", "");
    json calls = msg.value("tool_calls", json::array());
    if (!calls.is_array() || calls.empty()) {
      if (!content.empty() && content != user_msg) {
        ai_msgs.push_back({{"role", "assistant"}, {"content", content}});
        messages.push_back({{"role", "assistant"}, {"content", content}});
        reply = content;
        break;
      }
      // Model did not call tools: force a first search so the session is useful.
      if (step == 0) {
        json args = {{"query", topic}, {"count", 5}};
        std::string result = search_bilibili_tool(net, topic, 5);
        std::string id = "call-" + std::to_string(now_epoch()) + "-" + std::to_string(step);
        json tool_msg = {{"role", "tool"}, {"tool_call_id", id}, {"content", result.substr(0, 8000)}};
        json call_obj = {{"id", id}, {"type", "function"},
                          {"function", {{"name", "search_bilibili"}, {"arguments", args.dump()}}}};
        ai_msgs.push_back({{"role", "assistant"}, {"content", ""},
                           {"tool_calls", json::array({call_obj})}});
        ai_msgs.push_back(tool_msg);
        messages.push_back(tool_msg);
        continue;
      }
      reply = content;
      break;
    }
    json assistant_msg = {{"role", "assistant"}, {"content", content}};
    if (!calls.empty()) assistant_msg["tool_calls"] = calls;
    ai_msgs.push_back(assistant_msg);
    messages.push_back(assistant_msg);
    for (const auto& call : calls) {
      std::string id = call.value("id", "");
      std::string name = call_name(call);
      json args = parse_args(call_args(call));
      std::string result = execute_tool(app, net, ai, name, args);
      json tool_msg = {{"role", "tool"}, {"tool_call_id", id}, {"content", result.substr(0, 8000)}};
      ai_msgs.push_back(tool_msg);
      messages.push_back(tool_msg);
    }
  }
  if (reply.empty() && !messages.empty()) {
    reply = messages.back().value("content", "");
  }
  session["messages"] = messages;
  session["updated_at"] = now_iso();
  save_session(app, sid, session);
  return {{"ok", true}, {"session_id", sid}, {"reply", reply}, {"session", session}};
}

}  // namespace bili
