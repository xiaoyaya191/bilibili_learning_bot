package com.bililearn.app.network.asr

import android.content.Context
import android.media.AudioFormat
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.net.Uri
import java.nio.ByteOrder

data class PcmSegment(val startSeconds: Double, val samples: FloatArray)

class MediaPcmDecoder(private val context: Context) {
    fun decodeUri(uri: Uri, maxDurationSeconds: Int, onSegment: (PcmSegment) -> Unit): Double =
        decode(maxDurationSeconds, onSegment) { extractor -> extractor.setDataSource(context, uri, emptyMap()) }

    fun decodeUrl(url: String, headers: Map<String, String>, maxDurationSeconds: Int, onSegment: (PcmSegment) -> Unit): Double =
        decode(maxDurationSeconds, onSegment) { extractor -> extractor.setDataSource(url, headers) }

    private fun decode(
        maxDurationSeconds: Int,
        onSegment: (PcmSegment) -> Unit,
        setDataSource: (MediaExtractor) -> Unit
    ): Double {
        val extractor = MediaExtractor()
        var codec: MediaCodec? = null
        try {
            setDataSource(extractor)
            val trackIndex = (0 until extractor.trackCount).firstOrNull { index ->
                extractor.getTrackFormat(index).getString(MediaFormat.KEY_MIME)?.startsWith("audio/") == true
            } ?: error("所选文件不包含可解码音轨")
            val trackFormat = extractor.getTrackFormat(trackIndex)
            val mime = trackFormat.getString(MediaFormat.KEY_MIME) ?: error("音轨格式无效")
            val durationUs = trackFormat.getLongOrDefault(MediaFormat.KEY_DURATION, 0L)
            val durationSeconds = durationUs / 1_000_000.0
            require(durationSeconds <= maxDurationSeconds || durationSeconds <= 0) {
                "音轨时长 ${durationSeconds.toInt()} 秒，超过设置上限 $maxDurationSeconds 秒"
            }
            extractor.selectTrack(trackIndex)
            codec = MediaCodec.createDecoderByType(mime)
            codec.configure(trackFormat, null, null, 0)
            codec.start()

            var outputFormat = trackFormat
            var inputEnded = false
            var outputEnded = false
            var decodedFrames = 0L
            val accumulator = SegmentAccumulator(TARGET_SAMPLE_RATE, SEGMENT_SECONDS, onSegment)
            val info = MediaCodec.BufferInfo()
            while (!outputEnded) {
                if (!inputEnded) {
                    val inputIndex = codec.dequeueInputBuffer(TIMEOUT_US)
                    if (inputIndex >= 0) {
                        val buffer = codec.getInputBuffer(inputIndex) ?: error("无法取得解码输入缓冲区")
                        val size = extractor.readSampleData(buffer, 0)
                        if (size < 0) {
                            codec.queueInputBuffer(inputIndex, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                            inputEnded = true
                        } else {
                            codec.queueInputBuffer(inputIndex, 0, size, extractor.sampleTime.coerceAtLeast(0), 0)
                            extractor.advance()
                        }
                    }
                }

                when (val outputIndex = codec.dequeueOutputBuffer(info, TIMEOUT_US)) {
                    MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> outputFormat = codec.outputFormat
                    MediaCodec.INFO_TRY_AGAIN_LATER -> Unit
                    else -> if (outputIndex >= 0) {
                        if (info.size > 0) {
                            val sampleRate = outputFormat.getIntOrDefault(MediaFormat.KEY_SAMPLE_RATE, TARGET_SAMPLE_RATE)
                            val channels = outputFormat.getIntOrDefault(MediaFormat.KEY_CHANNEL_COUNT, 1).coerceAtLeast(1)
                            val encoding = outputFormat.getIntOrDefault(MediaFormat.KEY_PCM_ENCODING, AudioFormat.ENCODING_PCM_16BIT)
                            val buffer = codec.getOutputBuffer(outputIndex) ?: error("无法取得解码输出缓冲区")
                            buffer.position(info.offset)
                            buffer.limit(info.offset + info.size)
                            val mono = when (encoding) {
                                AudioFormat.ENCODING_PCM_FLOAT -> {
                                    val floats = buffer.order(ByteOrder.nativeOrder()).asFloatBuffer()
                                    val frames = floats.remaining() / channels
                                    FloatArray(frames) { frame ->
                                        var total = 0f
                                        repeat(channels) { channel -> total += floats.get(frame * channels + channel) }
                                        total / channels
                                    }
                                }
                                else -> {
                                    val shorts = buffer.order(ByteOrder.nativeOrder()).asShortBuffer()
                                    val frames = shorts.remaining() / channels
                                    FloatArray(frames) { frame ->
                                        var total = 0f
                                        repeat(channels) { channel -> total += shorts.get(frame * channels + channel) / 32768f }
                                        total / channels
                                    }
                                }
                            }
                            decodedFrames += mono.size
                            accumulator.append(resample(mono, sampleRate, TARGET_SAMPLE_RATE))
                        }
                        outputEnded = info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0
                        codec.releaseOutputBuffer(outputIndex, false)
                    }
                }
            }
            accumulator.flush()
            return if (durationSeconds > 0) durationSeconds else decodedFrames.toDouble() /
                outputFormat.getIntOrDefault(MediaFormat.KEY_SAMPLE_RATE, TARGET_SAMPLE_RATE)
        } finally {
            runCatching { codec?.stop() }
            runCatching { codec?.release() }
            extractor.release()
        }
    }

    private fun resample(input: FloatArray, sourceRate: Int, targetRate: Int): FloatArray {
        if (input.isEmpty() || sourceRate == targetRate) return input
        val outputSize = (input.size.toLong() * targetRate / sourceRate).toInt().coerceAtLeast(1)
        return FloatArray(outputSize) { index ->
            val sourcePosition = index.toDouble() * sourceRate / targetRate
            val left = sourcePosition.toInt().coerceIn(0, input.lastIndex)
            val right = (left + 1).coerceAtMost(input.lastIndex)
            val fraction = (sourcePosition - left).toFloat()
            input[left] * (1f - fraction) + input[right] * fraction
        }
    }

    private class SegmentAccumulator(
        sampleRate: Int,
        seconds: Int,
        private val consumer: (PcmSegment) -> Unit
    ) {
        private val segmentSamples = sampleRate * seconds
        private var buffer = FloatArray(segmentSamples)
        private var size = 0
        private var emittedSamples = 0L

        fun append(samples: FloatArray) {
            var offset = 0
            while (offset < samples.size) {
                val count = minOf(buffer.size - size, samples.size - offset)
                samples.copyInto(buffer, size, offset, offset + count)
                size += count
                offset += count
                if (size == buffer.size) emit(buffer)
            }
        }

        fun flush() {
            if (size > 0) emit(buffer.copyOf(size))
        }

        private fun emit(samples: FloatArray) {
            consumer(PcmSegment(emittedSamples / TARGET_SAMPLE_RATE.toDouble(), samples))
            emittedSamples += samples.size
            buffer = FloatArray(segmentSamples)
            size = 0
        }
    }

    private fun MediaFormat.getIntOrDefault(key: String, default: Int): Int =
        if (containsKey(key)) getInteger(key) else default

    private fun MediaFormat.getLongOrDefault(key: String, default: Long): Long =
        if (containsKey(key)) getLong(key) else default

    companion object {
        const val TARGET_SAMPLE_RATE = 16_000
        private const val SEGMENT_SECONDS = 28
        private const val TIMEOUT_US = 10_000L
    }
}
