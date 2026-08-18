# Exit freeze hardware test

Branch: `fix/exit-freeze-v2-review`

Purpose: fix the New 3DS / New 2DS XL freeze and long delay when leaving a Moonlight stream.

## Hardware results

### v1 — PASS (freeze removed)

Real New 2DS XL hardware testing confirmed that the original permanent hang was removed. Shutdown progressed through the Moonlight video teardown and returned to the server list instead of requiring a forced power-off. Diagnostics isolated the remaining delay inside `mvdstdExit()`.

Observed shutdown sequence reached:

- video callback stop complete
- depacketizer stop complete
- video ping thread joined
- video RTP socket closed
- video receive thread joined
- MVD cleanup / `mvdstdExit()`

The remaining wait was approximately one minute inside `mvdstdExit()`.

### v2 — HARDWARE PASS

v2 keeps the MVD service initialized for the lifetime of the Moonlight process instead of calling `mvdstdExit()` after each stream. Per-stream decoder/output buffers are still released, and the v1 RTP receive-thread wakeup and audio linear-buffer ownership fixes are retained.

Verified on a real New 2DS XL on 2026-08-18:

1. Start stream: PASS.
2. Exit stream: PASS, returns to server list in less than 5 seconds.
3. Reconnect without closing Moonlight: PASS.
4. Repeat stream/exit multiple times: PASS.
5. Audio/video/controls after reconnect: PASS.
6. Exit Moonlight completely to the 2DS HOME menu: PASS, console remains responsive.

This changes the observed behavior from an indefinite/forced-reboot exit to repeated clean exits in under 5 seconds. This is a hardware-verified fix candidate for issue #116; wider testing on additional New 3DS family devices is still desirable before an upstream release.
