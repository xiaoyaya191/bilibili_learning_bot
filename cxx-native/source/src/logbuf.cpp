#include "logbuf.h"

namespace bili {

LogBuffer& LogBuffer::instance() {
  static LogBuffer buf;
  return buf;
}

void LogBuffer::append(const std::string& line) {
  std::lock_guard<std::mutex> lock(mu_);
  lines_.push_back(line);
  if (lines_.size() > 500) lines_.pop_front();
}

std::vector<std::string> LogBuffer::tail(size_t n) const {
	std::lock_guard<std::mutex> lock(mu_);
	std::vector<std::string> out;
	size_t start = lines_.size() > n ? lines_.size() - n : 0;
	for (size_t i = start; i < lines_.size(); i++) out.push_back(lines_[i]);
	return out;
}

void LogBuffer::clear() {
	std::lock_guard<std::mutex> lock(mu_);
	lines_.clear();
}

}  // namespace bili
