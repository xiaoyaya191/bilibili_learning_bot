#pragma once

#include "config.h"

#include <string>

namespace bili {

// Runs the local whisper.cpp CLI (whisper-cli) on a 16 kHz mono WAV file and
// returns the recognized text. Empty string means failure or no speech.
std::string transcribe_audio(const App& app, const std::string& audio_path);

}  // namespace bili
