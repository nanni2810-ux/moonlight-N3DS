#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly 1 match, found {count}")
    p.write_text(text.replace(old, new, 1))
    print(f"patched {path}")


# 1) Fix ownership of the 3DS linear audio buffer. The original declaration
# shadows the global pointer, then cleanup calls free() on a linearAlloc() buffer.
replace_once(
    "src/audio/n3ds_audio.cpp",
    "    u8 *audioBuffer = (u8 *)linearAlloc(bytes_per_frame * WAVEBUF_SIZE);",
    "    audioBuffer = (u8 *)linearAlloc(bytes_per_frame * WAVEBUF_SIZE);",
)
replace_once(
    "src/audio/n3ds_audio.cpp",
    "        free(audioBuffer);",
    "        linearFree(audioBuffer);",
)

# 2) Hardware testing of v1 isolated the remaining ~60 second delay inside
# libctru's mvdstdExit(). MVD is a process-global service and its work buffer is
# already process-lifetime state, so v2 keeps a single MVD session alive while
# Moonlight itself remains open. Per-stream decode/output buffers are still freed.
# The next stream reuses the service and applies a fresh MVDSTD config.
replace_once(
    "src/video/n3ds_video_mvd.cpp",
    "static std::unique_ptr<MvdDecoder> instance = nullptr;",
    """static std::unique_ptr<MvdDecoder> instance = nullptr;
static bool mvd_service_initialized = false;""",
)

replace_once(
    "src/video/n3ds_video_mvd.cpp",
    """    uint32_t size = 0;
    int status = mvdstdCalculateBufferSize(&config, &size);
    if (status) {
        fprintf(stderr, \"mvdstdCalculateBufferSize failed: %d\\n\", status);
        throw std::runtime_error(\"mvdstdCalculateBufferSize failed\");
    }

    first_frame = true;
    status = mvdstdInit(MVDMODE_VIDEOPROCESSING, MVD_INPUT_H264,
                        MVD_OUTPUT_BGR565, size, NULL);
    if (status) {
        fprintf(stderr, \"mvdstdInit failed: %d\\n\", status);
        mvdstdExit();
        throw std::runtime_error(\"mvdstdInit failed\");
    }""",
    """    uint32_t size = 0;
    int status = 0;

    if (!mvd_service_initialized) {
        status = mvdstdCalculateBufferSize(&config, &size);
        if (status) {
            fprintf(stderr, \"mvdstdCalculateBufferSize failed: %d\\n\", status);
            throw std::runtime_error(\"mvdstdCalculateBufferSize failed\");
        }

        status = mvdstdInit(MVDMODE_VIDEOPROCESSING, MVD_INPUT_H264,
                            MVD_OUTPUT_BGR565, size, NULL);
        if (status) {
            fprintf(stderr, \"mvdstdInit failed: %d\\n\", status);
            throw std::runtime_error(\"mvdstdInit failed\");
        }
        mvd_service_initialized = true;
        printf(\"[exitfix-v2] MVD service initialized\\n\");
    } else {
        printf(\"[exitfix-v2] reusing process-lifetime MVD service\\n\");
    }

    first_frame = true;""",
)

replace_once(
    "src/video/n3ds_video_mvd.cpp",
    """MvdDecoder::~MvdDecoder() {
    y2rExit();
    mvdstdExit();
    linearFree(nal_unit_buffer);
    linearFree(rgb_img_buffer);
    printf(\"Video decoder shutdown successfully\\n\");
}""",
    """MvdDecoder::~MvdDecoder() {
    printf(\"[exitfix-v2] MVD per-stream cleanup begin\\n\");
    y2rExit();

    // Do not call mvdstdExit() here. On affected New 2DS XL hardware the
    // libctru shutdown path can remain BUSY for roughly a minute. Keeping the
    // MVD service alive avoids that stall and is safe for these per-stream
    // buffers because each new decoder submits a fresh MVDSTD configuration.
    // The service/work buffer live until Moonlight's process is closed.
    linearFree(nal_unit_buffer);
    nal_unit_buffer = nullptr;
    linearFree(rgb_img_buffer);
    rgb_img_buffer = nullptr;
    printf(\"[exitfix-v2] MVD service retained; per-stream buffers released\\n\");
}""",
)

# 3) On 3DS, wake a receive thread that may be stuck around recvfrom()/poll by
# closing the RTP socket after the ping thread has stopped but before joining the
# receive thread. Keep concise diagnostics for the v2 hardware test.
video_path = Path("third_party/moonlight-common-c/src/VideoStream.c")
video_text = video_path.read_text()

include_anchor = '#include "Limelight-internal.h"\n'
include_addition = '#include "Limelight-internal.h"\n\n#ifdef __3DS__\n#include <stdio.h>\n#endif\n'
if include_anchor not in video_text:
    raise RuntimeError("VideoStream.c: include anchor not found")
video_text = video_text.replace(include_anchor, include_addition, 1)

start_marker = "void stopVideoStream(void) {"
end_marker = "\n}\n\n// Start the video stream"
start = video_text.find(start_marker)
if start < 0:
    raise RuntimeError("VideoStream.c: stopVideoStream start not found")
end = video_text.find(end_marker, start)
if end < 0:
    raise RuntimeError("VideoStream.c: stopVideoStream end not found")
end += 2

replacement = r'''void stopVideoStream(void) {
    if (!receivedDataFromPeer) {
        Limelog("No video traffic was ever received from the host!\n");
    }

#ifdef __3DS__
    printf("[exitfix-v2] stopVideoStream begin\n");
#endif
    VideoCallbacks.stop();

    // Wake up client code that may be waiting on the decode unit queue
    stopVideoDepacketizer();

    PltInterruptThread(&udpPingThread);
    PltInterruptThread(&receiveThread);
    if ((VideoCallbacks.capabilities & (CAPABILITY_DIRECT_SUBMIT | CAPABILITY_PULL_RENDERER)) == 0) {
        PltInterruptThread(&decoderThread);
    }

    if (firstFrameSocket != INVALID_SOCKET) {
        shutdownTcpSocket(firstFrameSocket);
    }

    PltJoinThread(&udpPingThread);

#ifdef __3DS__
    // 3DS has no SO_RCVTIMEO support. Closing the UDP socket before the join
    // wakes recvfrom() if teardown races with the receive loop.
    if (rtpSocket != INVALID_SOCKET) {
        closeSocket(rtpSocket);
        rtpSocket = INVALID_SOCKET;
    }
#endif

    PltJoinThread(&receiveThread);
    if ((VideoCallbacks.capabilities & (CAPABILITY_DIRECT_SUBMIT | CAPABILITY_PULL_RENDERER)) == 0) {
        PltJoinThread(&decoderThread);
    }

    if (firstFrameSocket != INVALID_SOCKET) {
        closeSocket(firstFrameSocket);
        firstFrameSocket = INVALID_SOCKET;
    }
    if (rtpSocket != INVALID_SOCKET) {
        closeSocket(rtpSocket);
        rtpSocket = INVALID_SOCKET;
    }

    VideoCallbacks.cleanup();
#ifdef __3DS__
    printf("[exitfix-v2] stopVideoStream complete\n");
#endif
}'''

video_text = video_text[:start] + replacement + video_text[end:]
video_path.write_text(video_text)
print(f"patched {video_path}")
