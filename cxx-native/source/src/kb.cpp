#include "kb.h"
#include "version_history.h"

#include <algorithm>
#include "platform.h"
#include <chrono>
#include <ctime>
#include <filesystem>
#include "fscompat.h"
#include <fstream>
#include <sstream>
#include <set>

namespace fs = std::filesystem;

namespace bili {
namespace {

std::string read_file(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) return "";
  std::ostringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

bool write_file(const std::string& path, const std::string& content) {
  fs::create_directories(fs::path(path).parent_path());
  std::ofstream out(path, std::ios::binary);
  if (!out) return false;
  out << content;
  return out.good();
}

std::string strip_bom(const std::string& s) {
  if (s.size() >= 3 && (unsigned char)s[0] == 0xEF && (unsigned char)s[1] == 0xBB &&
      (unsigned char)s[2] == 0xBF) {
    return s.substr(3);
  }
  return s;
}

std::string lower_ascii(const std::string& s) {
  std::string out = s;
  std::transform(out.begin(), out.end(), out.begin(),
                 [](unsigned char c) { return std::tolower(c); });
  return out;
}

std::string now_iso() {
  std::time_t t = std::time(nullptr);
  std::tm tm{};
  localtime_r(&t, &tm);
  char buf[64];
  std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &tm);
  return buf;
}

std::string truncate(const std::string& s, size_t n) {
  if (s.size() <= n) return s;
  return s.substr(0, n) + "...";
}

std::string trim_copy(const std::string& s) {
  size_t a = s.find_first_not_of(" \t\r\n");
  if (a == std::string::npos) return "";
  size_t b = s.find_last_not_of(" \t\r\n");
  return s.substr(a, b - a + 1);
}

// Mirrors services/rag_qa.py::_score_text so C++ and Python rank the same.
double score_text(const std::string& query, const std::string& text) {
	std::string q = lower_ascii(query);
	std::string compact_q = q;
	compact_q.erase(std::remove(compact_q.begin(), compact_q.end(), ' '), compact_q.end());
	std::string low = lower_ascii(text);
	std::string compact_low = low;
	compact_low.erase(std::remove(compact_low.begin(), compact_low.end(), ' '),
	                    compact_low.end());

	double score = 0;
	if (!compact_q.empty() && compact_low.find(compact_q) != std::string::npos) score += 5.0;

	std::istringstream iss(q);
	std::string token;
	while (iss >> token) {
		if (token.size() >= 2 && low.find(token) != std::string::npos) score += 1.0;
	}
	// CJK query characters: match full UTF-8 code points in U+4E00..U+9FFF.
	for (size_t i = 0; i < query.size();) {
		unsigned char b = (unsigned char)query[i];
		if (b >= 0xE4 && b <= 0xE9 && i + 2 < query.size()) {
			uint32_t cp = ((b & 0x0F) << 12) | (((unsigned char)query[i + 1] & 0x3F) << 6) |
					((unsigned char)query[i + 2] & 0x3F);
			if (cp >= 0x4E00 && cp <= 0x9FFF) {
				if (low.find(query.substr(i, 3)) != std::string::npos) score += 0.08;
			}
			i += 3;
		} else {
			i += b < 0x80 ? 1 : ((b & 0xE0) == 0xC0 ? 2 : 3);
		}
	}
	return score;
}

std::vector<std::string> chunks_of(const std::string& content, size_t size, size_t overlap) {
	std::vector<std::string> out;
	if (content.size() <= size) {
		out.push_back(content);
		return out;
	}
	for (size_t i = 0; i < content.size(); i += size - overlap) {
		out.push_back(content.substr(i, size));
		if (i + size >= content.size()) break;
	}
	return out;
}

}  // namespace

std::string detect_category(const std::string& title, const std::string& content) {
  std::string hay = lower_ascii(title + " " + content);
  struct Rule {
    const char* cat;
    std::vector<const char*> words;
  };
  static const Rule rules[] = {
      {"编程技术", {"编程", "代码", "c++", "python", "go", "rust", "算法", "数据库", "linux", "git"}},
      {"科技数码", {"科技", "数码", "手机", "电脑", "硬件", "ai", "人工智能"}},
      {"音乐艺术", {"音乐", "歌曲", "歌词", "绘画", "艺术", "吉他", "钢琴"}},
      {"学习教程", {"教程", "教学", "课程", "学习", "考试", "知识"}},
      {"生活分享", {"生活", "日常", "vlog", "美食", "旅行", "健身"}},
  };
  for (const auto& rule : rules) {
    for (const char* w : rule.words) {
      if (hay.find(w) != std::string::npos) return rule.cat;
    }
  }
  return "视频学习";
}

KnowledgeBase::KnowledgeBase(std::string metadata_file, std::string kb_root)
    : metadata_file_(std::move(metadata_file)), kb_root_(std::move(kb_root)) {}

bool KnowledgeBase::rebuild_index() {
  std::error_code ec;
  if (!fs::exists(kb_root_, ec)) return false;
  auto& idx = metadata_["file_index"];
  if (!idx.is_object()) idx = nlohmann::json::object();
  for (const auto& entry : fs::recursive_directory_iterator(kb_root_, ec)) {
    if (ec || !entry.is_regular_file()) continue;
    if (entry.path().extension() != ".md") continue;
    std::string rel = fs::relative(entry.path(), kb_root_).generic_string();
    std::string cat = entry.path().parent_path().filename().string();
    if (cat.empty() || cat == ".") cat = "未分类";
    std::string title = entry.path().stem().string();
    std::string content = read_file(entry.path().string());
    size_t nl = content.find('\n');
    if (nl != std::string::npos && content.rfind("# ", 0) == 0) title = trim_copy(content.substr(2, nl - 2));
    auto& arr = idx[cat];
    if (!arr.is_array()) arr = nlohmann::json::array();
    arr.push_back({{"path", rel}, {"title", title}, {"time", now_iso()}, {"source", "auto-index"}});
  }
  metadata_["categories"] = nlohmann::json::object();
  return save();
}

bool KnowledgeBase::load() {
  std::string raw = read_file(metadata_file_);
  if (raw.empty()) {
    metadata_ = {{"categories", nlohmann::json::object()},
                 {"file_index", nlohmann::json::object()},
                 {"last_updated", ""}};
    return true;
  }
	try {
		metadata_ = nlohmann::json::parse(strip_bom(raw));
	} catch (...) {
		return false;
	}
	// 元数据为空时自动扫描 KnowledgeBase 重建 file_index（兼容 Python 面板覆盖）。
	const auto& idx = metadata_.value("file_index", nlohmann::json::object());
	if (!idx.is_object() || idx.empty()) {
		if (rebuild_index()) return true;
	}
	return true;
}

bool KnowledgeBase::save() {
  metadata_["last_updated"] = now_iso();
  return write_file(metadata_file_, metadata_.dump(2));
}

size_t KnowledgeBase::note_count() const {
  const auto& idx = metadata_.value("file_index", nlohmann::json::object());
  size_t n = 0;
  for (const auto& [k, v] : idx.items()) {
    if (v.is_array()) n += v.size();
  }
  return n;
}

bool KnowledgeBase::add_note(const std::string& category, const std::string& title,
                             const std::string& bvid, const std::string& content,
                             const nlohmann::json& config) {
  std::string safe_cat = category.empty() ? "未分类" : category;
  std::string fname = bvid.empty() ? "note" : bvid;
  std::string rel = safe_cat + "/" + fname + ".md";
  std::string abs = kb_root_ + "/" + rel;
  std::string md = "# " + title + "\n\n" + content + "\n";
  save_note_version(abs, md, config);
  if (!write_file(abs, md)) return false;

  auto& idx = metadata_["file_index"];
  if (!idx.is_object()) idx = nlohmann::json::object();
  auto& arr = idx[safe_cat];
  if (!arr.is_array()) arr = nlohmann::json::array();
  nlohmann::json entry = {{"path", rel},
                          {"bvid", bvid},
                          {"title", title},
                          {"time", now_iso()},
                          {"source", "cxx"}};
  // Replace same-bvid entry if present.
  for (auto it = arr.begin(); it != arr.end(); ++it) {
    if (it->value("bvid", "") == bvid) {
      *it = entry;
      return save();
    }
  }
  arr.push_back(entry);
  return save();
}

std::vector<SearchHit> KnowledgeBase::search(const std::string& query,
							 int max_chunks) const {
	std::vector<SearchHit> hits;
	const auto& idx = metadata_.value("file_index", nlohmann::json::object());
	for (const auto& [cat, entries] : idx.items()) {
		if (!entries.is_array()) continue;
		for (const auto& e : entries) {
			std::string rel = e.value("path", "");
			std::string title = e.value("title", "");
			std::string abs = kb_root_ + "/" + rel;
			std::string content = read_file(abs);
			if (content.empty()) continue;
			// RAG: 分块评分，取命中最好的片段
			SearchHit best;
			for (const auto& chunk : chunks_of(content, 500, 80)) {
				double score = score_text(query, chunk);
				if (score > best.score) {
					best = {rel, title, score, truncate(chunk, 500)};
				}
			}
			if (best.score > 0) hits.push_back(best);
		}
	}
	std::sort(hits.begin(), hits.end(),
					[](const SearchHit& a, const SearchHit& b) { return a.score > b.score; });
	if ((int)hits.size() > max_chunks) hits.resize(max_chunks);
	return hits;
}

}  // namespace bili
