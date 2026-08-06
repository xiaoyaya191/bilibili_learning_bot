#pragma once

#include <nlohmann/json.hpp>

#include <string>
#include <utility>
#include <vector>

#include "net.h"

namespace bili {

struct VideoInfo {
  long long aid = 0;
  long long cid = 0;
  long long up_mid = 0;
  std::string bvid;
  std::string title;
  std::string desc;
};

struct VideoComment {
  long long rpid = 0;
  long long ctime = 0;
  long long member_mid = 0;
  std::string member_uname;
  std::string message;
};

// Flexible numeric conversion (numbers or numeric strings from Bilibili).
long long num(const nlohmann::json& v);

std::vector<std::pair<long long, std::string>> user_videos(NetClient& net, long long uid,
                                                           std::string& error);
std::vector<VideoComment> video_comments(NetClient& net, long long aid, std::string& error);
nlohmann::json reply_feed(NetClient& net, std::string& error);
nlohmann::json at_feed(NetClient& net, std::string& error);
VideoInfo video_info(NetClient& net, const std::string& bvid, long long aid,
                     std::string& error);
std::string video_ai_summary(NetClient& net, const VideoInfo& info);

// Write operations; each returns "" on success or an error description.
std::string send_comment(NetClient& net, const std::string& csrf, const std::string& text,
                         long long oid, long long root, long long parent);
std::string like_comment(NetClient& net, const std::string& csrf, long long oid,
                         long long rpid);
std::string report_history(NetClient& net, const App& app, const std::string& bvid, int played_time);
std::string like_video(NetClient& net, const std::string& csrf, long long aid,
                       const std::string& bvid);
std::string pay_coin(NetClient& net, const std::string& csrf, long long aid,
                     const std::string& bvid);
std::string add_favorite(NetClient& net, const std::string& csrf, long long aid,
                         long long folder_id);

// Sends a text private message to a Bilibili user. Returns "" on success.
std::string send_private_message(NetClient& net, const App& app, long long receiver_uid,
                                const std::string& text);
long long first_favorite_folder(NetClient& net, long long aid, long long uid,
                                std::string& error);
bool has_liked_video(NetClient& net, long long aid, const std::string& bvid);

// Follow or unfollow a Bilibili user. Returns "" on success.
std::string follow_user(NetClient& net, const App& app, long long uid, bool follow);

}  // namespace bili
