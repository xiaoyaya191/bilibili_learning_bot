#pragma once

#include <nlohmann/json.hpp>

#include <string>

namespace bili {

// comment_log.json compatible state (processed/replied/liked all dedupe).
class CommentLog {
 public:
  explicit CommentLog(std::string path);

  bool load();
  bool save();

  bool is_processed(const std::string& id) const;
  bool mark_processed(const std::string& id);
  bool mark_replied(const std::string& id);
  bool mark_liked(const std::string& id);
  bool log_interaction(const std::string& id, const std::string& action,
                       const std::string& content, const std::string& target_user);

  bool reply_feed_baseline() const;
  bool set_reply_feed_baseline(const std::vector<std::string>& ids);

  bool should_reply_user(const std::string& user_id, const std::string& content,
                         int cooldown_minutes, std::string& reason) const;
  bool mark_user_replied(const std::string& user_id);

  bool three_action_done(const std::string& bvid) const;
  bool mark_three_action(const std::string& bvid, const nlohmann::json& results);
  int coin_used_today() const;

 private:
  std::string path_;
  nlohmann::json data_ = nlohmann::json::object();
};

// monitor_at_state.json compatible state for @ notifications.
class AtState {
 public:
  explicit AtState(std::string path);

  bool load();
  bool save();

  bool processed(const std::string& id) const;
  bool mark_processed(const std::string& id);
  int record_attempt(const std::string& id);

 private:
  std::string path_;
  nlohmann::json data_ = nlohmann::json::object();
};

}  // namespace bili
