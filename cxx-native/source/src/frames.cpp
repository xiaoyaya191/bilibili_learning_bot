#include "frames.h"

#ifdef BILI_USE_FFMPEG

#include <cstdio>
#include <filesystem>
#include "fscompat.h"
#include <vector>

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/imgutils.h>
#include <libswscale/swscale.h>
}

#include "stb_image_write.h"

namespace bili {
namespace {

bool write_rgb_jpeg(const std::string& path, const uint8_t* rgb, int w, int h) {
  return stbi_write_jpg(path.c_str(), w, h, 3, rgb, 0) != 0;
}

}  // namespace

std::vector<std::string> extract_frames_direct(const std::string& video_url,
                                               const std::string& out_dir, int count) {
  std::vector<std::string> out;
  if (count <= 0) return out;
  std::error_code ec;
  std::filesystem::create_directories(out_dir, ec);

  avformat_network_init();
  AVFormatContext* fmt = nullptr;
  if (avformat_open_input(&fmt, video_url.c_str(), nullptr, nullptr) < 0) return out;
  if (avformat_find_stream_info(fmt, nullptr) < 0) {
    avformat_close_input(&fmt);
    return out;
  }
  int vs = av_find_best_stream(fmt, AVMEDIA_TYPE_VIDEO, -1, -1, nullptr, 0);
  if (vs < 0) {
    avformat_close_input(&fmt);
    return out;
  }
  AVStream* stream = fmt->streams[vs];
  AVCodecParameters* params = stream->codecpar;
  const AVCodec* dec = avcodec_find_decoder(params->codec_id);
  if (!dec) {
    avformat_close_input(&fmt);
    return out;
  }
  AVCodecContext* ctx = avcodec_alloc_context3(dec);
  if (!ctx) {
    avformat_close_input(&fmt);
    return out;
  }
  if (avcodec_parameters_to_context(ctx, params) < 0 || avcodec_open2(ctx, dec, nullptr) < 0) {
    avcodec_free_context(&ctx);
    avformat_close_input(&fmt);
    return out;
  }

  int width = ctx->width > 0 ? ctx->width : 640;
  int height = ctx->height > 0 ? ctx->height : 360;
  SwsContext* sws = sws_getContext(width, height, ctx->pix_fmt, width, height, AV_PIX_FMT_RGB24,
                                   SWS_BILINEAR, nullptr, nullptr, nullptr);
  if (!sws) {
    avcodec_free_context(&ctx);
    avformat_close_input(&fmt);
    return out;
  }
  std::vector<uint8_t> rgb(static_cast<size_t>(width) * height * 3);

  AVPacket* pkt = av_packet_alloc();
  AVFrame* frame = av_frame_alloc();
  if (!pkt || !frame) {
    av_packet_free(&pkt);
    av_frame_free(&frame);
    sws_freeContext(sws);
    avcodec_free_context(&ctx);
    avformat_close_input(&fmt);
    return out;
  }

  long long duration = stream->duration > 0 ? stream->duration : (fmt->duration > 0 ? fmt->duration : 0);
  for (int i = 0; i < count; i++) {
    long long ts = 0;
    if (duration > 0 && count > 1) {
      ts = (duration / (count - 1)) * i;
    }
    if (ts > 0) {
      av_seek_frame(fmt, vs, ts, AVSEEK_FLAG_BACKWARD);
      avcodec_flush_buffers(ctx);
    }
    bool got = false;
    while (av_read_frame(fmt, pkt) >= 0) {
      if (pkt->stream_index != vs) {
        av_packet_unref(pkt);
        continue;
      }
      int ret = avcodec_send_packet(ctx, pkt);
      av_packet_unref(pkt);
      if (ret < 0) break;
      while (avcodec_receive_frame(ctx, frame) >= 0) {
        uint8_t* dst[4] = {rgb.data(), nullptr, nullptr, nullptr};
        int linesize[4] = {width * 3, 0, 0, 0};
        sws_scale(sws, frame->data, frame->linesize, 0, height, dst, linesize);
        std::string path = out_dir + "/frame_" + std::to_string(i + 1) + ".jpg";
        if (write_rgb_jpeg(path, rgb.data(), width, height)) out.push_back(path);
        av_frame_unref(frame);
        got = true;
        break;
      }
      if (got) break;
    }
    if (!got) break;
  }

  av_packet_free(&pkt);
  av_frame_free(&frame);
  sws_freeContext(sws);
  avcodec_free_context(&ctx);
  avformat_close_input(&fmt);
  return out;
}

}  // namespace bili

#else

#include <vector>

namespace bili {

std::vector<std::string> extract_frames_direct(const std::string&, const std::string&, int) {
  return {};
}

}  // namespace bili

#endif
