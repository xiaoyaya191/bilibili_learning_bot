#include "factory_reset.h"

#include <algorithm>
#include <filesystem>
#include "fscompat.h"
#include <set>

namespace fs = std::filesystem;
#include <string>
#include <vector>

namespace bili {
namespace {

using json = nlohmann::json;

struct GroupMeta {
  const char* id;
  const char* label;
  const char* description;
  bool default_selected;
};

const GroupMeta kGroups[] = {
    {"credentials_runtime", "登录凭证与运行数据", "Cookie、二维码、API 配置、网页密码、会话、日志和互动记录", true},
    {"knowledge_generated", "知识库与生成内容", "知识库、HTML、思维导图、Word、亮点归档和自定义导出目录", true},
    {"local_models", "本地 ASR 模型", "项目 model 目录及配置指定的 ASR 模型目录", true},
    {"project_docs", "项目 docs 内容", "项目 docs 目录", true},
    {"backup_files", "配置备份（默认保留）", "手动导出的配置备份", false},
};

bool starts_with_path(const fs::path& p, const fs::path& root) {
  std::error_code ec;
  fs::path rp = fs::weakly_canonical(p, ec);
  fs::path rr = fs::weakly_canonical(root, ec);
  if (ec) return false;
  auto it = rp.begin();
  auto it2 = rr.begin();
  for (; it2 != rr.end(); ++it, ++it2) {
    if (it == rp.end() || *it != *it2) return false;
  }
  return true;
}

bool is_safe_target(const fs::path& p, const fs::path& user_data_dir, const fs::path& data_dir) {
  if (p.empty()) return false;
  std::error_code ec;
  fs::path rp = fs::weakly_canonical(p, ec);
  if (ec || rp == rp.root_path()) return false;
  if (rp == user_data_dir) return false;
  if (rp == data_dir) return true;
  return starts_with_path(rp, user_data_dir) || starts_with_path(rp, data_dir);
}

std::pair<long long, long long> usage(const fs::path& p) {
  std::error_code ec;
  if (!fs::exists(p, ec) || fs::is_symlink(p)) return {0, 0};
  if (fs::is_regular_file(p, ec)) {
    auto sz = fs::file_size(p, ec);
    return {1, ec ? 0 : (long long)sz};
  }
  long long files = 0, bytes = 0;
  for (const auto& e : fs::recursive_directory_iterator(p, ec)) {
    if (ec) break;
    if (e.is_regular_file() && !e.is_symlink()) {
      files++;
      auto sz = fs::file_size(e.path(), ec);
      if (!ec) bytes += (long long)sz;
    }
  }
  return {files, bytes};
}

std::vector<std::string> unique_paths(std::vector<std::string> paths,
                                      const fs::path& user_data_dir,
                                      const fs::path& data_dir) {
  std::set<std::string> seen;
  std::vector<std::string> out;
  for (auto& s : paths) {
    fs::path p(s);
    if (!is_safe_target(p, user_data_dir, data_dir)) continue;
    std::string key = fs::weakly_canonical(p).string();
    if (seen.insert(key).second) out.push_back(s);
  }
  return out;
}

std::vector<std::string> group_paths(const App& app, const std::string& group_id) {
  fs::path ud = app.paths.user_data_dir;
  fs::path dd = app.paths.data_dir;
  if (group_id == "credentials_runtime") {
    std::vector<std::string> p = {dd.string()};
    for (const char* name : {"qr_codes", "bot_memory.json", "bot_journal.md",
                             "knowledge_metadata.json", "learning_log.md"}) {
      p.push_back((ud / name).string());
      p.push_back((dd / name).string());
    }
    return unique_paths(p, ud, dd);
  }
  if (group_id == "knowledge_generated") {
    std::vector<std::string> p;
    for (const char* name : {"KnowledgeBase", "highlights", "html_exports",
                             "MindMaps", "Word", "Mindmaps", "exports"}) {
      p.push_back((ud / name).string());
      p.push_back((dd / name).string());
    }
    const auto& cfg = app.config.value("knowledge", json::object());
    if (cfg.contains("base_dir") && cfg["base_dir"].is_string()) {
      p.push_back(cfg["base_dir"].get<std::string>());
    }
    return unique_paths(p, ud, dd);
  }
  if (group_id == "local_models") {
    std::vector<std::string> p = {(ud / "model").string()};
    const auto& asr = app.config.value("asr", json::object());
    if (asr.contains("model_path") && asr["model_path"].is_string()) {
      p.push_back(asr["model_path"].get<std::string>());
    }
    return unique_paths(p, ud, dd);
  }
  if (group_id == "project_docs") {
    return unique_paths({(ud / "docs").string()}, ud, dd);
  }
  if (group_id == "backup_files") {
    return unique_paths({(ud / "backups").string(), (dd / "backups").string()}, ud, dd);
  }
  return {};
}

}  // namespace

json preview_reset_groups(const App& app, const json& selected_groups) {
  std::set<std::string> selected;
  if (selected_groups.is_array()) {
    for (const auto& g : selected_groups) {
      if (g.is_string()) selected.insert(g.get<std::string>());
    }
  }
  json groups = json::array();
  for (const auto& meta : kGroups) {
    bool sel = selected.empty() ? meta.default_selected : selected.count(meta.id) > 0;
    auto paths = group_paths(app, meta.id);
    long long files = 0, bytes = 0;
    for (const auto& p : paths) {
      auto u = usage(p);
      files += u.first;
      bytes += u.second;
    }
    json arr = json::array();
    for (const auto& p : paths) arr.push_back(p);
    groups.push_back({{"id", meta.id}, {"label", meta.label},
                      {"description", meta.description}, {"selected", sel},
                      {"paths", arr}, {"files", files}, {"bytes", bytes}});
  }
  json selected_out = json::array();
  for (const auto& meta : kGroups) {
    if (selected.empty() ? meta.default_selected : selected.count(meta.id) > 0) {
      selected_out.push_back(meta.id);
    }
  }
  return {{"groups", groups}, {"selected_groups", selected_out}};
}

int erase_reset_groups(const App& app, const json& selected_groups) {
  std::set<std::string> selected;
  if (selected_groups.is_array()) {
    for (const auto& g : selected_groups) {
      if (g.is_string()) selected.insert(g.get<std::string>());
    }
  }
  if (selected.empty()) {
    for (const auto& meta : kGroups) {
      if (meta.default_selected) selected.insert(meta.id);
    }
  }
  int deleted = 0;
  for (const auto& meta : kGroups) {
    if (!selected.count(meta.id)) continue;
    for (const auto& p : group_paths(app, meta.id)) {
      fs::path target(p);
      if (!is_safe_target(target, app.paths.user_data_dir, app.paths.data_dir)) continue;
      std::error_code ec;
      if (fs::exists(target, ec)) {
        if (fs::is_directory(target, ec)) fs::remove_all(target, ec);
        else fs::remove(target, ec);
        if (!ec) deleted++;
      }
    }
  }
  return deleted;
}

}  // namespace bili
