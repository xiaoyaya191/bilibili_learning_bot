#include "asr.h"

#include <cstdio>
#include <filesystem>
#include "fscompat.h"
#include <fstream>
#include <sstream>
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

std::string trim(const std::string& s) {
  size_t a = s.find_first_not_of(" \t\r\n");
  if (a == std::string::npos) return "";
  size_t b = s.find_last_not_of(" \t\r\n");
  return s.substr(a, b - a + 1);
}

bool run_command(const std::string& cmd) {
  FILE* p = popen(cmd.c_str(), "r");
  if (!p) return false;
  char buf[256];
  while (fgets(buf, sizeof(buf), p)) {
  }
  int rc = pclose(p);
  return rc == 0;
}

}  // namespace

std::string transcribe_audio(const App& app, const std::string& audio_path) {
  if (audio_path.empty()) return "";
  std::error_code ec;
  if (!fs::exists(audio_path, ec)) return "";

  std::string binary = get_str(app, "asr", "binary_path", "");
  if (binary.empty()) binary = app.paths.data_dir + "/models/asr/whisper-cli";
  std::string model = get_str(app, "asr", "model_path", "");
  if (model.empty()) model = app.paths.data_dir + "/models/asr/ggml-tiny.bin";
  if (!fs::exists(binary, ec) || !fs::exists(model, ec)) return "";

  std::string out_prefix = audio_path + ".out";
  std::string cmd = "\"" + binary + "\" -m \"" + model + "\" -f \"" + audio_path +
                    "\" -otxt -of \"" + out_prefix + "\" -l auto";
  std::string lib_dir = get_str(app, "asr", "lib_path", "");
  if (lib_dir.empty()) {
    std::error_code rce;
    fs::path real_bin = fs::canonical(binary, rce);
    if (rce) real_bin = fs::path(binary);
    lib_dir = (real_bin.parent_path() / "lib").string();
  }
  if (!lib_dir.empty()) cmd = "LD_LIBRARY_PATH=\"" + lib_dir + "\" " + cmd;
  std::fprintf(stderr, "[ASR] cmd: %s\n", cmd.c_str());
  if (!run_command(cmd)) return "";

  std::string txt_path = out_prefix + ".txt";
  if (!fs::exists(txt_path, ec)) {
    // whisper.cpp may write <audio>.txt when -of is omitted.
    txt_path = audio_path + ".txt";
  }
  return trim(read_file(txt_path));
}

}  // namespace bili
