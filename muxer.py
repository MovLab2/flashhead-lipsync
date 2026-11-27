"""
Mux frame images + audio into a final MP4 using ffmpeg.
FlashHead renders audio-synced frames (0.96s audio -> 24 frames),
so we just mux them together.

audio_delay: Seconds offset for audio (negative = audio starts earlier,
positive = audio starts later). Use to fix sync issues.
"""
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("muxer")


def mux_frames_with_audio(frames_dir, audio_path, output_path, fps=25, crf=18, preset="fast", audio_delay=0.0):
    frames_dir = Path(frames_dir)
    audio_path = Path(audio_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    frames = sorted(frames_dir.glob("*.png"))
    if not frames:
        raise FileNotFoundError("No PNG frames found in %s" % frames_dir)

    input_pattern = str(frames_dir / "lip_frame_%06d.png")

    cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        str(fps),
        "-i",
        input_pattern,
    ]

    # Add audio delay offset before audio input
    # Negative = audio starts earlier, positive = audio starts later
    if audio_delay != 0.0:
        cmd.extend(["-itsoffset", str(audio_delay)])

    cmd.extend([
        "-i",
        str(audio_path),
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-pix_fmt",
        "yuv420p",
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        str(output_path),
    ])

    logger.info("Muxing %d frames + audio -> %s", len(frames), output_path)
    if audio_delay != 0.0:
        logger.info("Audio delay: %s seconds", audio_delay)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("ffmpeg failed: %s", result.stderr[-2000:])
        raise RuntimeError("ffmpeg failed: " + result.stderr[-500:])

    logger.info("Done: %s", output_path)
    return output_path
