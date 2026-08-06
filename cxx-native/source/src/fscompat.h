#pragma once

#include <filesystem>

// NDK's libc++ exposes filesystem under std::__fs::filesystem instead of
// std::filesystem. Keeping the portable name avoids touching every call site.
#if defined(__ANDROID__)
namespace std {
namespace filesystem = __fs::filesystem;
}
#endif
