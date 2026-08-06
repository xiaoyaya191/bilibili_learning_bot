#include "video_asr.h"

#include <cstdio>
#include <filesystem>
#include "fscompat.h"
#include <fstream>
#include <sstream>

namespace fs = std::filesystem;

#include "analysis.h"
#include "api.h"
#include "asr.h"

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

bool write_file(const std::string& path, const std::string& content) {
  std::error_code ec;
  fs::create_directories(fs::path(path).parent_path(), ec);
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  if (!out) return false;
  out << content;
  return out.good();
}

bool run_command(const std::string& cmd) {
  FILE* p = popen(cmd.c_str(), "r");
  if (!p) return false;
  char buf[256];
  while (fgets(buf, sizeof(buf), p)) {
  }
  return pclose(p) == 0;
}

}  // namespace

json video_asr(App& app, NetClient& net, AiClient& ai, const std::string& bvid) {
  (void)ai;
  if (bvid.empty()) return {{"ok", false}, {"message", "bvid required"}};
  std::string err;
  VideoInfo info = video_info(net, bvid, 0, err);
  if (info.cid == 0) return {{"ok", false}, {"message", err.empty() ? "video not found" : err}};

  NetResponse play = net.get("https://api.bilibili.com/x/player/playurl",
                             {{"bvid", bvid}, {"cid", std::to_string(info.cid)},
                              {"fnval", "16"}, {"fnver", "0"}, {"fourk", "1"}});
  std::string audio_url;
  try {
    auto j = json::parse(play.body);
    const auto& dash = j.value("data", json::object()).value("dash", json::object());
    const auto& audios = dash.value("audio", json::array());
    if (!audios.empty()) audio_url = audios[0].value("baseUrl", audios[0].value("base_url", ""));
  } catch (...) {
  }
  if (audio_url.empty()) return {{"ok", false}, {"message", "audio url not found"}};

  std::string ffmpeg = get_str(app, "asr", "ffmpeg_path", "");
  if (ffmpeg.empty()) ffmpeg = "ffmpeg";
  std::string work = app.paths.data_dir + "/asr_work";
  std::error_code ec;
  fs::create_directories(work, ec);
  std::string wav = work + "/" + bvid + ".wav";
  std::string cmd = "\"" + ffmpeg + "\" -y -i \"" + audio_url + "\" -vn -ac 1 -ar 16000 \"" + wav + "\"";
  if (!run_command(cmd)) return {{"ok", false}, {"message", "ffmpeg extract failed"}};

  std::string text = transcribe_audio(app, wav);
  std::string out_dir = app.paths.data_dir + "/transcripts";
  std::string out_path = out_dir + "/" + bvid + ".txt";
  write_file(out_path, text + "\n");
  return {{"ok", !text.empty()}, {"bvid", bvid}, {"text", text}, {"path", out_path}};
}

}  // namespace bili
