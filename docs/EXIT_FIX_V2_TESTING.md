# Exit freeze v2 hardware test

Branch: `fix/exit-freeze-v2`

v1 removed the permanent exit hang on a New 2DS XL and isolated the remaining ~60 second delay inside `mvdstdExit()`.

v2 keeps the MVD service initialized for the lifetime of the Moonlight process, while still releasing per-stream decoder buffers. It also keeps the v1 RTP receive-thread shutdown fix and audio linear-buffer ownership fix.

## Required hardware test

1. Start a stream and run it for at least 30 seconds with video and audio.
2. Exit the stream and measure whether the server list returns within a few seconds.
3. Without closing Moonlight, start a second stream.
4. Confirm video, audio and controls still work.
5. Exit again and confirm the second exit is also quick.
6. Repeat once more (3 stream/exit cycles total).
7. Finally close Moonlight normally from the 3DS HOME menu and verify the console remains responsive.

Do not merge v2 until repeated-stream reuse is verified on hardware.
