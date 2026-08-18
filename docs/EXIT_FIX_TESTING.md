# Exit freeze hardware test

Branch: `fix/exit-freeze-v1`

Purpose: diagnose and fix the New 3DS / New 2DS XL freeze when leaving a Moonlight stream.

The test build adds shutdown diagnostics, closes the 3DS video RTP socket before joining the video receive thread, and fixes the local audio linear buffer ownership/free mismatch.

## Hardware test

1. Install the CIA produced by this branch.
2. Start a normal stream and let it run for at least 30 seconds with audio and video active.
3. Exit the stream using the normal Moonlight exit action.
4. If the app returns to its menu or exits normally, repeat the test 3 times.
5. If it freezes, photograph the last `[exitfix]` line visible on screen.

Do not merge this branch until the shutdown path is verified on real hardware.
