#include "version_history.h"

#include <algorithm>
#include <chrono>
#include <ctime>
#include <filesystem>
#include "fscompat.h"
#include <fstream>
#include "platform.h"
#include <sstream>

namespace fs = std::filesystem;
#include <vector>

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
  std::error_code ec;
  fs::create_directories(fs::path(path).parent_path(), ec);
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) return false;
  out << content;
  return out.good();
}

std::string ts() {
  std::time_t t = std::time(nullptr);
  std::tm tm{};
  localtime_r(&t, &tm);
  char buf[40];
  std::strftime(buf, sizeof(buf), "%Y%m%d_%H%M%S", &tm);
  return buf;
}

std::vector<std::string> split_lines(const std::string& s) {
  std::vector<std::string> out;
  std::string cur;
  for (char c : s) {
    if (c == '\n') {
      out.push_back(cur);
      cur.clear();
    } else {
      cur += c;
    }
  }
  if (!cur.empty() || (!s.empty() && s.back() == '\n')) out.push_back(cur);
  return out;
}

std::string unified_diff(const std::string& old_text, const std::string& new_text) {
  auto a = split_lines(old_text);
  auto b = split_lines(new_text);
  size_t n = a.size(), m = b.size();
  std::vector<std::vector<int>> dp(n + 1, std::vector<int>(m + 1, 0));
  for (size_t i = n; i-- > 0;) {
    for (size_t j = m; j-- > 0;) {
      dp[i][j] = a[i] == b[j] ? dp[i + 1][j + 1] + 1 : std::max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  std::ostringstream out;
  size_t i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] == b[j]) {
      out << " " << a[i] << "\n";
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out << "-" << a[i++] << "\n";
    } else {
      out << "+" << b[j++] << "\n";
    }
  }
  while (i < n) out << "-" << a[i++] << "\n";
  while (j < m) out << "+" << b[j++] << "\n";
  return out.str();
}

}  // namespace

nlohmann::json save_note_version(const std::string& note_path, const std::string& content,
                                 const nlohmann::json& config) {
  const auto& opts = config.value("version_history", nlohmann::json::object());
  if (!opts.value("enabled", false)) return nlohmann::json::object();
  int max_versions = std::max(1, (int)opts.value("max_versions", 5));

  fs::path path(note_path);
  fs::path versions_dir = path.parent_path() / ".versions" / path.stem().string();
  std::error_code ec;
  fs::create_directories(versions_dir, ec);

  std::string stamp = ts();
  nlohmann::json result = nlohmann::json::object();
  std::string old_text = fs::exists(path, ec) ? read_file(note_path) : "";
  if (!old_text.empty()) {
    std::string prev = (versions_dir / (stamp + "_previous.md")).string();
    write_file(prev, old_text);
    result["previous"] = prev;
    if (opts.value("diff_on_regenerate", true)) {
      std::string diff = unified_diff(old_text, content);
      std::string diff_path = (versions_dir / (stamp + ".diff")).string();
      write_file(diff_path, diff);
      result["diff"] = diff_path;
    }
  } else {
    std::string initial = (versions_dir / (stamp + "_initial.md")).string();
    write_file(initial, content);
    result["initial"] = initial;
  }

  std::vector<fs::path> versions;
  for (const auto& entry : fs::directory_iterator(versions_dir, ec)) {
    if (entry.is_regular_file() && entry.path().extension() == ".md") {
      versions.push_back(entry.path());
    }
  }
  std::sort(versions.begin(), versions.end(),
            [](const fs::path& a, const fs::path& b) { return a.filename().string() > b.filename().string(); });
  for (size_t k = max_versions; k < versions.size(); k++) {
    fs::remove(versions[k], ec);
  }
  return result;
}

}  // namespace bili
