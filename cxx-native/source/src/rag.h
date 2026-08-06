#pragma once

#include "ai.h"
#include "config.h"
#include "net.h"

#include <nlohmann/json.hpp>
#include <string>

namespace bili {

// RAG QA ported from services/rag_qa.py: KB retrieval + optional function
// calling so the model can read/list knowledge files.
nlohmann::json rag_answer(App& app, NetClient& net, AiClient& ai,
                          const std::string& question);

}  // namespace bili
