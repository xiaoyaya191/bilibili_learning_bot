#pragma once

#include "ai.h"
#include "config.h"
#include "net.h"

#include <nlohmann/json.hpp>
#include <string>

namespace bili {

// End-to-end video ASR: fetch playurl, extract 16 kHz mono WAV with ffmpeg,
// run whisper.cpp, save transcript.
nlohmann::json video_asr(App& app, NetClient& net, AiClient& ai,
                         const std::string& bvid);

}  // namespace bili
