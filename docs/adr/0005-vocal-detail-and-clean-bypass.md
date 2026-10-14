# Preserve accepted Vocal detail and isolate OFF from model processing

The user confirmed Music suppression was satisfactory on 2026-10-14 and
asked for more natural Vocal plus a fix for clicks/crackling even when OFF.

Keep the default DPDFNet model and its input conversion unchanged. A longer
output FIR compensates the converter's roll-off around consonants. Restore
small aligned waveform differences only when residual energy is below 2.5%
of the model's accepted Vocal energy, independently per channel. There is no
volume threshold. Restoration withdraws immediately on rejected frames and
ramps up slowly. This narrowly revises ADR-0004's fully processed ON policy
in response to the user's new quality request; failures still mute ON.

The output FIR adds 1 ms: DPDFNet pipeline delay is now 63 ms. Full-band
DPDFNet2 was evaluated but rejected: sequential stereo exceeded the 10 ms
deadline and parallel execution left insufficient CPU headroom. Phase-only
restoration worsened paired-mixture quality and was also rejected.

OFF must not invoke neural processing. Suspend the processor after the
toggle ramp, and reset it on the audio thread before resuming ON so stale
audio does not return. Equal-rate OFF samples remain bit-perfect at the
engine seam. Device-rate conversion necessarily changes sample values.

Use a four-block-capacity frame ring for independent WASAPI endpoints,
with two-block priming and rebuffering after starvation. Only discontinuities
receive a 2 ms fade; regular playback is copied unchanged. This contains
clicks from missing/discarded audio while bounding delay. It cannot eliminate
Windows scheduling failures or reconstruct lost frames. Polyphase sinc
conversion replaces linear interpolation at the device boundaries; include
its actual filter delay in diagnostics, and exclude neural delay when OFF.
