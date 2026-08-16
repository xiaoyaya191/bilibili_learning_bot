#pragma once

#include <deque>
#include <mutex>
#include <string>
#include <vector>

namespace bili {

// In-memory ring buffer of monitor log lines for the web panel.
class LogBuffer {
 public:
  static LogBuffer& instance();
  void append(const std::string& line);
  std::vector<std::string> tail(size_t n) const;
  void clear();

 private:
  mutable std::mutex mu_;
  std::deque<std::string> lines_;
};

}  // namespace bili
