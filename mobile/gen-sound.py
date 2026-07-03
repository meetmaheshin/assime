"""Generate AARTH's signature notification tone -> res/raw/aarth_alert.wav.
A short, bright 4-note arpeggio with a bell-like (2-partial, decaying) timbre —
distinctive enough to recognize instantly, like a messenger app's alert."""
import math
import os
import struct
import wave

SR = 44100
raw_dir = os.path.join("android", "app", "src", "main", "res", "raw")
os.makedirs(raw_dir, exist_ok=True)
out = os.path.join(raw_dir, "aarth_alert.wav")

# A-major arpeggio going up, bright and friendly.
notes = [880.00, 1108.73, 1318.51, 1760.00]  # A5, C#6, E6, A6
note_dur = 0.16      # seconds between note onsets
tail = 0.45          # decay tail of the last note
total = note_dur * (len(notes) - 1) + tail

samples = [0.0] * int(SR * total)
for i, f in enumerate(notes):
    start = int(i * note_dur * SR)
    dur = tail if i == len(notes) - 1 else note_dur + 0.28
    n = int(dur * SR)
    for k in range(n):
        idx = start + k
        if idx >= len(samples):
            break
        t = k / SR
        env = math.exp(-t * 7.0)                     # bell-like decay
        atk = min(1.0, t / 0.004)                    # tiny attack to avoid click
        s = math.sin(2 * math.pi * f * t)            # fundamental
        s += 0.35 * math.sin(2 * math.pi * f * 2 * t)  # 2nd partial (shimmer)
        samples[idx] += 0.55 * atk * env * s

peak = max(1e-9, max(abs(x) for x in samples))
scale = 0.89 / peak
with wave.open(out, "w") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(b"".join(
        struct.pack("<h", int(max(-1, min(1, x * scale)) * 32767)) for x in samples))
print("wrote", out, "-", round(total, 2), "s")
