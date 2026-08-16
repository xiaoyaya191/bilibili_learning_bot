#pragma once

#include <string>

#include "ai.h"
#include "api.h"
#include "config.h"
#include "net.h"
#include "state.h"

namespace bili {

struct Comment {
  long long id = 0;
  long long aid = 0;
  long long root = 0;
  long long parent = 0;
  long long user_id = 0;
  std::string bvid;
  std::string content;
  std::string user;
  std::string source;
  bool force = false;
};

class Monitor {
 public:
  explicit Monitor(App& app);

  // Block-style entry points (each returns process exit code).
  int check_once();
  int check_video(const std::string& bvid);
  int check_coin(const std::string& bvid);
  std::string chat(const std::string& prompt);

  // Fetches the recommendation feed, writes local watch history, and reports
  // playback heartbeat like the original Python bot browsing loop.
  int browse_recommendations();

 private:
  int scan_video_comments();
  int check_reply_feed();
  int check_mentions();
  bool handle_comment(const Comment& c);
  void one_click_three(long long aid, const std::string& bvid, const std::string& user);
  std::string generate_at_reply(const nlohmann::json& notification);
  nlohmann::json parse_at_notification(const nlohmann::json& item) const;
  Comment parse_reply_notification(const nlohmann::json& item) const;

  std::string ensure_marker(std::string text) const;
  std::string build_comment_prompt(const Comment& c) const;
  std::string build_at_prompt(const nlohmann::json& n, const std::string& evidence) const;
  std::string csrf() const;
  bool auto_reply_enabled() const;
  int max_replies() const;
  void log(const char* level, const std::string& msg) const;

  App& app_;
  NetClient net_;
  AiClient ai_;
  CommentLog cmt_;
  AtState at_;
  long long last_browse_ = 0;
  bool at_baseline_ = false;
  int comment_risk_pause_sec_ = 0;  // -412 pause counter (blocks in loop)
};

}  // namespace bili
