#pragma once

#include <string>
#include <vector>

namespace bili {

// Direct FFmpeg frame extraction (libav*), used when the bundled static
// FFmpeg libraries are available. Falls back to the external ffmpeg binary
// inside web_panel.cpp when BILI_USE_FFMPEG is not defined.
std::vector<std::string> extract_frames_direct(const std::string& video_url,
                                               const std::string& out_dir, int count);

}  // namespace bili
