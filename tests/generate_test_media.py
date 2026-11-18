"""Generates synthetic test media for verifying the GTA VI Clipping MVP pipeline.
Creates:
1. Visual-only stunt video with no dialogue (scene changes, motion, impact peak).
2. Gameplay with spoken dialogue and streamer reaction.
3. Media placed in folders with spaces and Unicode characters.
"""

from __future__ import annotations
import math
from pathlib import Path
import struct
import subprocess
import sys
import wave

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gta_clipper.config import StorageConfig


def create_synthetic_audio_wav(output_wav: Path, duration_sec: float, event_time: float) -> bool:
    """Creates a 16kHz mono WAV with ambient sound and a loud impact spike."""
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    framerate = 16000
    total_frames = int(duration_sec * framerate)

    with wave.open(str(output_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(framerate)

        samples = []
        for i in range(total_frames):
            t = i / framerate
            # Ambient background hum (~ -32 dB)
            sample = int(1000 * math.sin(2 * math.pi * 120 * t))

            # Loud impact/explosion crash at event_time for 1.2s (~ 0 dB)
            if event_time <= t <= event_time + 1.2:
                decay = math.exp(-(t - event_time) * 3)
                impact = int(28000 * decay * math.sin(2 * math.pi * 65 * t))
                sample = max(-32767, min(32767, sample + impact))

            samples.append(sample)

        raw_bytes = struct.pack(f"<{len(samples)}h", *samples)
        wf.writeframes(raw_bytes)

    return output_wav.is_file()


def create_speech_audio_wav(output_wav: Path, duration_sec: float = 35.0) -> bool:
    """Generates synthetic spoken dialogue audio."""
    output_wav.parent.mkdir(parents=True, exist_ok=True)

    # PowerShell script to invoke System.Speech
    ps_cmd = (
        f"Add-Type -AssemblyName System.Speech; "
        f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{output_wav.as_posix()}'); "
        f"$s.Speak('Wait, watch this car jump! No way bro, he actually survived that!'); "
        f"$s.Dispose()"
    )
    res = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if res.returncode == 0 and output_wav.is_file() and output_wav.stat().st_size > 1000:
        return True

    # Fallback to simulated speech pattern bursts
    framerate = 16000
    total_frames = int(duration_sec * framerate)
    with wave.open(str(output_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(framerate)
        samples = []
        for i in range(total_frames):
            t = i / framerate
            sample = 0
            if (3.0 <= t <= 8.0) or (16.0 <= t <= 22.0):
                f1 = math.sin(2 * math.pi * 260 * t)
                f2 = math.sin(2 * math.pi * 950 * t)
                sample = int(16000 * (f1 + 0.4 * f2))
            samples.append(sample)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    return output_wav.is_file()


def build_synthetic_visual_video(output_mp4: Path, duration: int = 40, impact_time: float = 20.0) -> bool:
    """Builds a 1920x1080 30fps MP4 video with distinct scene transitions and motion."""
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    wav_temp = output_mp4.with_suffix(".tmp.wav")
    create_synthetic_audio_wav(wav_temp, duration, impact_time)

    # 3 distinct scenes:
    # Scene 1: 0 - 12s (dark green, moving yellow vehicle)
    # Scene 2: 12 - 25s (dark red, fast moving orange vehicle, impact at 20s)
    # Scene 3: 25 - 40s (dark blue, stationary cyan box, aftermath)
    d1, d2, d3 = 12, 13, duration - 25

    filter_complex = (
        f"[0:v]drawbox=x='mod(t*220,1600)':y=450:w=320:h=180:color=yellow:t=fill[v0];"
        f"[1:v]drawbox=x='1600-mod(t*340,1600)':y=450:w=320:h=180:color=orange:t=fill[v1];"
        f"[2:v]drawbox=x=800:y=450:w=320:h=180:color=cyan:t=fill[v2];"
        f"[v0][v1][v2]concat=n=3:v=1:a=0[vcat]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x1e3a1e:s=1920x1080:r=30:d={d1}",
        "-f", "lavfi", "-i", f"color=c=0x661111:s=1920x1080:r=30:d={d2}",
        "-f", "lavfi", "-i", f"color=c=0x112266:s=1920x1080:r=30:d={d3}",
        "-i", str(wav_temp),
        "-filter_complex", filter_complex,
        "-map", "[vcat]",
        "-map", "3:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-t", str(duration),
        str(output_mp4)
    ]

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=90)
    if res.returncode != 0:
        print("Speech video FFmpeg error:", res.stderr[-500:])
    if wav_temp.is_file():
        wav_temp.unlink()
    return res.returncode == 0 and output_mp4.is_file()


def build_synthetic_speech_video(output_mp4: Path, duration: int = 35) -> bool:
    """Builds a 1920x1080 video with spoken audio and facecam overlay."""
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    wav_temp = output_mp4.with_suffix(".tmp.wav")
    create_speech_audio_wav(wav_temp, duration)

    filter_complex = (
        f"[0:v]drawbox=x='mod(t*200,1500)':y=500:w=300:h=160:color=lime:t=fill[bg];"
        f"[bg][1:v]overlay=1380:60[v_out]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x111827:s=1920x1080:r=30:d={duration}",
        "-f", "lavfi", "-i", f"color=c=0xef4444:s=480x360:r=30:d={duration}",
        "-i", str(wav_temp),
        "-filter_complex", filter_complex,
        "-map", "[v_out]",
        "-map", "2:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-t", str(duration),
        str(output_mp4)
    ]

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=90)
    if res.returncode != 0:
        print("Speech video FFmpeg error:", res.stderr[-500:])
    if wav_temp.is_file():
        wav_temp.unlink()
    return res.returncode == 0 and output_mp4.is_file()


def build_multitrack_recording(output_mp4: Path, duration: int = 35) -> bool:
    """Builds a 1920x1080 video with two separate audio streams:
    Track 0: Game Audio (engine noise & ambient hum)
    Track 1: Streamer Mic Audio (spoken commentary & reaction)
    """
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    game_wav = output_mp4.with_suffix(".game.tmp.wav")
    mic_wav = output_mp4.with_suffix(".mic.tmp.wav")

    # Generate game ambient sound (rumble & car engine sound)
    create_synthetic_audio_wav(game_wav, duration, event_time=20.0)
    # Generate streamer voice
    create_speech_audio_wav(mic_wav, duration)

    filter_complex = (
        f"[0:v]drawbox=x='mod(t*220,1500)':y=450:w=320:h=180:color=orange:t=fill[bg];"
        f"[bg][1:v]overlay=1380:60[v_out]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=0x0f172a:s=1920x1080:r=30:d={duration}",
        "-f", "lavfi", "-i", f"color=c=0xd97706:s=480x360:r=30:d={duration}",
        "-i", str(game_wav),
        "-i", str(mic_wav),
        "-filter_complex", filter_complex,
        "-map", "[v_out]",
        "-map", "2:a",  # Track 0: Game Audio
        "-map", "3:a",  # Track 1: Streamer Mic
        "-metadata:s:a:0", "title=Game Audio",
        "-metadata:s:a:1", "title=Streamer Mic",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-t", str(duration),
        str(output_mp4)
    ]

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=90)
    if game_wav.is_file():
        game_wav.unlink()
    if mic_wav.is_file():
        mic_wav.unlink()
    return res.returncode == 0 and output_mp4.is_file()


def generate_all_test_media(storage: StorageConfig) -> dict[str, Path]:
    """Generates all synthetic sources inside the local data dir outside OneDrive."""
    sources_dir = storage.root / "test_sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    v1 = sources_dir / "synthetic_visual_only.mp4"
    if not v1.is_file():
        print(f"[*] Generating {v1.name} (40s, visual-only, no speech)...")
        build_synthetic_visual_video(v1, duration=40, impact_time=20.0)

    v2 = sources_dir / "synthetic_speech_reaction.mp4"
    if not v2.is_file():
        print(f"[*] Generating {v2.name} (35s, with speech/audio)...")
        build_synthetic_speech_video(v2, duration=35)

    # Unicode & spaces test file
    unicode_dir = sources_dir / "Streamer Recordings [GTA VI 🎮]"
    unicode_dir.mkdir(parents=True, exist_ok=True)
    v3 = unicode_dir / "Lucia & Jason 🚗 vídéo test.mp4"
    if not v3.is_file() and v1.is_file():
        print(f"[*] Creating Unicode/spaces test source: {v3.name}...")
        cmd = [
            "ffmpeg", "-y",
            "-i", str(v1),
            "-t", "20",
            "-c", "copy",
            str(v3)
        ]
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    v4 = sources_dir / "synthetic_multitrack.mp4"
    if not v4.is_file():
        print(f"[*] Generating {v4.name} (35s, multi-track audio: game + mic)...")
        build_multitrack_recording(v4, duration=35)

    return {
        "visual_only": v1,
        "speech_reaction": v2,
        "unicode_path": v3,
        "multitrack": v4,
    }


if __name__ == "__main__":
    storage = StorageConfig()
    media = generate_all_test_media(storage)
    for k, p in media.items():
        print(f"  {k}: {p} (exists={p.is_file()})")
