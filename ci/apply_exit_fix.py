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

# 2) Add visible diagnostics around the MVD hardware decoder teardown.
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
    printf(\"[exitfix] MVD cleanup: y2rExit begin\\n\");
    y2rExit();
    printf(\"[exitfix] MVD cleanup: y2rExit complete\\n\");
    printf(\"[exitfix] MVD cleanup: mvdstdExit begin\\n\");
    mvdstdExit();
    printf(\"[exitfix] MVD cleanup: mvdstdExit complete\\n\");
    linearFree(nal_unit_buffer);
    linearFree(rgb_img_buffer);
    printf(\"[exitfix] Video decoder shutdown successfully\\n\");
}""",
)

# 3) On 3DS, wake a receive thread that may be stuck around recvfrom()/poll by
# closing the RTP socket after the ping thread has stopped but before joining the
# receive thread. Also print each teardown stage so a hardware photo identifies
# the exact blocking call if this first workaround is not sufficient.
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
    printf("[exitfix] stopVideoStream begin\n");
    printf("[exitfix] video callback stop begin\n");
#endif
    VideoCallbacks.stop();
#ifdef __3DS__
    printf("[exitfix] video callback stop complete\n");
    printf("[exitfix] depacketizer stop begin\n");
#endif

    // Wake up client code that may be waiting on the decode unit queue
    stopVideoDepacketizer();
#ifdef __3DS__
    printf("[exitfix] depacketizer stop complete\n");
#endif

    PltInterruptThread(&udpPingThread);
    PltInterruptThread(&receiveThread);
    if ((VideoCallbacks.capabilities & (CAPABILITY_DIRECT_SUBMIT | CAPABILITY_PULL_RENDERER)) == 0) {
        PltInterruptThread(&decoderThread);
    }

    if (firstFrameSocket != INVALID_SOCKET) {
        shutdownTcpSocket(firstFrameSocket);
    }

#ifdef __3DS__
    printf("[exitfix] joining video ping thread\n");
#endif
    PltJoinThread(&udpPingThread);
#ifdef __3DS__
    printf("[exitfix] video ping thread joined\n");

    // 3DS has no SO_RCVTIMEO support. If the receive thread slips from poll()
    // into recvfrom() just as teardown starts, the original infinite join can
    // wait forever. Closing the UDP socket here wakes that path deterministically.
    if (rtpSocket != INVALID_SOCKET) {
        printf("[exitfix] closing video RTP socket\n");
        closeSocket(rtpSocket);
        rtpSocket = INVALID_SOCKET;
        printf("[exitfix] video RTP socket closed\n");
    }
    printf("[exitfix] joining video receive thread\n");
#endif
    PltJoinThread(&receiveThread);
#ifdef __3DS__
    printf("[exitfix] video receive thread joined\n");
#endif

    if ((VideoCallbacks.capabilities & (CAPABILITY_DIRECT_SUBMIT | CAPABILITY_PULL_RENDERER)) == 0) {
#ifdef __3DS__
        printf("[exitfix] joining video decoder thread\n");
#endif
        PltJoinThread(&decoderThread);
#ifdef __3DS__
        printf("[exitfix] video decoder thread joined\n");
#endif
    }

    if (firstFrameSocket != INVALID_SOCKET) {
        closeSocket(firstFrameSocket);
        firstFrameSocket = INVALID_SOCKET;
    }
    if (rtpSocket != INVALID_SOCKET) {
        closeSocket(rtpSocket);
        rtpSocket = INVALID_SOCKET;
    }

#ifdef __3DS__
    printf("[exitfix] video callback cleanup begin\n");
#endif
    VideoCallbacks.cleanup();
#ifdef __3DS__
    printf("[exitfix] video callback cleanup complete\n");
    printf("[exitfix] stopVideoStream complete\n");
#endif
}'''

video_text = video_text[:start] + replacement + video_text[end:]
video_path.write_text(video_text)
print(f"patched {video_path}")
