#pragma once

#include <nlohmann/json.hpp>

#include <string>
#include <vector>

namespace bili {

struct SearchHit {
	std::string path;
	std::string title;
	double score = 0;
	std::string snippet;
};

// 简单的关键词自动分类：标题/内容包含哪类词就归到哪类。
std::string detect_category(const std::string& title, const std::string& content);

// Markdown note knowledge base compatible with the Python bot's
// knowledge_metadata.json (categories / file_index) layout.
class KnowledgeBase {
 public:
  KnowledgeBase(std::string metadata_file, std::string kb_root);

  bool load();
  bool rebuild_index();
  bool save();
  bool add_note(const std::string& category, const std::string& title,
                const std::string& bvid, const std::string& content,
                const nlohmann::json& config = nlohmann::json::object());
  const nlohmann::json& metadata() const { return metadata_; }
  std::vector<SearchHit> search(const std::string& query, int max_chunks = 5) const;
  size_t note_count() const;

 private:
  std::string metadata_file_;
  std::string kb_root_;
  nlohmann::json metadata_ = nlohmann::json::object();
};

}  // namespace bili
