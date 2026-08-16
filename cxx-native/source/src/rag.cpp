#include "rag.h"

#include <filesystem>
#include "fscompat.h"
#include <fstream>
#include <sstream>

namespace fs = std::filesystem;

#include "kb.h"

namespace bili {
namespace {

using json = nlohmann::json;

std::string read_file(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) return "";
  std::ostringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

std::string read_kb(const App& app, const std::string& filename) {
  std::string p = app.paths.knowledge_base_dir + "/" + filename;
  std::string content = read_file(p);
  if (content.empty()) content = read_file(app.paths.knowledge_base_dir + "/custom/" + filename);
  return content;
}

std::string list_kb(const App& app) {
  std::error_code ec;
  json out = json::array();
  for (const auto& e : fs::recursive_directory_iterator(app.paths.knowledge_base_dir, ec)) {
    if (ec) break;
    if (e.is_regular_file() && e.path().extension() == ".md") {
      out.push_back(fs::relative(e.path(), app.paths.knowledge_base_dir).generic_string());
    }
  }
  return out.dump();
}

std::string call_tool(const App& app, const std::string& name, const std::string& raw_args) {
  json args = json::object();
  try { args = json::parse(raw_args); } catch (...) {}
  if (name == "read_kb_file") return read_kb(app, args.value("filename", ""));
  if (name == "list_kb_files") return list_kb(app);
  return "unknown tool";
}

}  // namespace

json rag_answer(App& app, NetClient& net, AiClient& ai, const std::string& question) {
  const auto& cfg = app.config.value("rag_qa", json::object());
  if (!cfg.value("enabled", false)) {
    return {{"ok", false}, {"answer", "RAG 问答未启用"}, {"sources", json::array()}};
  }
  KnowledgeBase kb(app.paths.knowledge_metadata_file, app.paths.knowledge_base_dir);
  kb.load();
  auto hits = kb.search(question, 5);
  std::ostringstream ctx;
  json sources = json::array();
  for (const auto& h : hits) {
    ctx << "[" << h.title << "] " << h.snippet << "\n";
    sources.push_back({{"path", h.path}, {"title", h.title}, {"score", h.score}});
  }
  std::string user = "基于以下知识库片段回答问题：\n" + ctx.str() + "\n问题：" + question;
  bool use_fc = cfg.value("enable_function_calling", false);
  std::string answer;
  if (use_fc) {
    json tools = json::array({
        {{"type", "function"},
         {"function", {{"name", "read_kb_file"},
                       {"description", "读取知识库文件内容"},
                       {"parameters", {{"type", "object"},
                                       {"properties", {{"filename", {{"type", "string"}}}},
                                        {"required", json::array({"filename"})}}}}}}},
        {{"type", "function"},
         {"function", {{"name", "list_kb_files"},
                       {"description", "列出知识库文件"},
                       {"parameters", {{"type", "object"}, {"properties", json::object()},
                                       {"required", json::array()}}}}}},
    });
    json msg = ai.chat_tools({{"system", "你是严谨的 RAG 问答助手，只依据知识库内容回答。"},
                              {"user", user}}, tools);
    json calls = msg.value("tool_calls", json::array());
    if (calls.is_array() && !calls.empty()) {
      std::ostringstream tool_out;
      for (const auto& c : calls) {
        tool_out << call_tool(app, c.value("function", json::object()).value("name", ""),
                              c.value("function", json::object()).value("arguments", "{}"))
                 << "\n";
      }
      answer = ai.chat({{"system", "你是严谨的 RAG 问答助手，只依据知识库内容回答。"},
                        {"user", user + "\n工具结果:\n" + tool_out.str()}});
    } else {
      answer = msg.value("content", "");
    }
  } else {
    answer = ai.chat({{"system", "你是严谨的 RAG 问答助手，只依据知识库内容回答。"}, {"user", user}});
  }
  return {{"ok", true}, {"answer", answer}, {"sources", sources}};
}

}  // namespace bili
