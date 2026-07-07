"""Generate AARTH's ringtone -> res/raw/aarth_ring.wav.
A warm two-tone 'ring ... ring ...' that repeats for ~7s, so a closed-app
notification actually rings like an incoming call (not a single ding)."""
import math
import os
import struct
import wave

SR = 44100
raw_dir = os.path.join("android", "app", "src", "main", "res", "raw")
os.makedirs(raw_dir, exist_ok=True)
out = os.path.join(raw_dir, "aarth_ring.wav")

# One "ring" = two pleasant tones together, ~1s, with a gentle pulse envelope,
# then a gap. Repeat ~4 times → ~7s.
ring_tones = [587.33, 880.0]   # D5 + A5, bright but not harsh
ring_dur = 1.0
gap_dur = 0.7
reps = 4

total = int((ring_dur + gap_dur) * reps * SR)
samples = [0.0] * total
for r in range(reps):
    start = int(r * (ring_dur + gap_dur) * SR)
    n = int(ring_dur * SR)
    for k in range(n):
        idx = start + k
        if idx >= total:
            break
        t = k / SR
        # amplitude pulses ~5x/sec so it "trills" like a ring
        pulse = 0.55 + 0.45 * abs(math.sin(2 * math.pi * 5 * t))
        atk = min(1.0, t / 0.01) * min(1.0, (ring_dur - t) / 0.05)
        s = sum(math.sin(2 * math.pi * f * t) for f in ring_tones) / len(ring_tones)
        samples[idx] += 0.7 * pulse * atk * s

peak = max(1e-9, max(abs(x) for x in samples))
scale = 0.9 / peak
with wave.open(out, "w") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(b"".join(
        struct.pack("<h", int(max(-1, min(1, x * scale)) * 32767)) for x in samples))
print("wrote", out, "-", round(total / SR, 2), "s")
