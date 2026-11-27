"""
End-to-end pipeline (Sapphire-safe — we never modify the Sapphire plugin):

  audio + avatar reference -> head box -> crop -> FlashHead HTTP client
         -> composite head back -> mux frames+audio -> MP4

The FlashHead server runs in Sapphire's flashhead plugin (untouched) on
http://127.0.0.1:5017. We start it standalone if it isn't already running.
"""
import cv2
import logging
import os
import subprocess
import time
from pathlib import Path

from face_detector import FaceDetector
from flashhead_inference import FlashHeadClient, DEFAULT_SERVER
from compositor import composite_head
from muxer import mux_frames_with_audio
from trim import detect_speech_frames, trim_frames

logger = logging.getLogger("pipeline")

FLASHHEAD_PLUGIN_DIR = Path(
    "C:/Users/mosas.ASUS-GAMING/sapphire/user/plugins/flashhead"
)
FLASHHEAD_ENV_PYTHON = (
    "C:/Users/mosas.ASUS-GAMING/miniconda3/envs/sapphire-plugin-flashhead/python.exe"
)


def extract_first_frame(video_path):
    """Extract the first frame of a video as a BGR numpy array."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        logger.error("Cannot open video: %s", video_path)
        return None
    ret, frame = cap.read()
    cap.release()
    if not ret:
        logger.error("Cannot read first frame from: %s", video_path)
        return None
    return frame


def _start_flashhead_server():
    """Start the FlashHead server standalone (from Sapphire's plugin folder)
    if it isn't already reachable. Returns the subprocess or None."""
    client = FlashHeadClient(DEFAULT_SERVER)
    if client.health() and client.health().get("status") == "ready":
        logger.info("FlashHead server already running at %s", DEFAULT_SERVER)
        return None

    logger.info("Starting FlashHead server from %s", FLASHHEAD_PLUGIN_DIR)
    server_py = FLASHHEAD_PLUGIN_DIR / "server.py"
    if not server_py.exists():
        raise FileNotFoundError("server.py not found in FlashHead plugin: %s" % server_py)

    env = os.environ.copy()
    env["SAPPHIRE_ROOT"] = str(FLASHHEAD_PLUGIN_DIR.parent.parent.parent)  # the sapphire install
    env["SAPPHIRE_SERVICE_PORT"] = "5017"
    env["PYTHONUTF8"] = "1"

    proc = subprocess.Popen(
        [str(FLASHHEAD_ENV_PYTHON), str(server_py)],
        cwd=str(FLASHHEAD_PLUGIN_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    logger.info("FlashHead server PID %d starting...", proc.pid)
    return proc


def _wait_for_server(proc, timeout=180):
    """Wait for the FlashHead server to become ready."""
    client = FlashHeadClient(DEFAULT_SERVER)
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        # If the process died, report why
        if proc is not None and proc.poll() is not None:
            out, _ = proc.communicate()
            raise RuntimeError(
                "FlashHead server exited early (code %d). Output:\n%s"
                % (proc.returncode, (out or "")[-2000:])
            )
        h = client.health()
        if h and h.get("status") == "ready":
            logger.info("FlashHead server ready: %s", h)
            return client
        if h and h.get("status") == "error":
            raise RuntimeError("FlashHead server error: %s" % h.get("error"))
        if h:
            logger.info("Server status: %s (progress: %s)", h.get("status"), h.get("progress"))
        time.sleep(3)
    raise TimeoutError("FlashHead server did not become ready within %ds" % timeout)


def run_pipeline(
    audio_path,
    avatar_source,
    output_path,
    cascade_path="C:/AvatarProject/avatar_grid/haarcascade_frontalface_default.xml",
    fps=25,
    preset="smallest",
    stub=False,
    start_server=True,
    chest_pad=0.55,
    audio_delay=0.0,
):
    """
    Full pipeline. Returns the final MP4 path.

    preset: FlashHead video memory preset ("full" | "lean" | "smallest").
    stub: use placeholder frames instead of real FlashHead.
    start_server: if True, start the FlashHead server standalone when needed.
    chest_pad: extra downward padding for chest area (better neck seam).
    """
    audio_path = Path(audio_path)
    avatar_source = Path(avatar_source)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    frames_dir = output_path.parent / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load avatar reference (image or first frame of video)
    if avatar_source.suffix.lower() in (".mp4", ".mov", ".avi", ".mkv"):
        logger.info("Extracting first frame from video: %s", avatar_source)
        reference_frame = extract_first_frame(avatar_source)
        if reference_frame is None:
            raise RuntimeError("Failed to extract frame from %s" % avatar_source)
    else:
        reference_frame = cv2.imread(str(avatar_source))
        if reference_frame is None:
            raise FileNotFoundError("Cannot read image: %s" % avatar_source)

    # 2. Detect head box (chest to above head)
    detector = FaceDetector(cascade_path)
    box = detector.detect_head_box(reference_frame)
    if box is None:
        raise RuntimeError("No face/head detected in avatar source")
    logger.info("Head box detected: %s", box)

    # Save cropped head for FlashHead reference
    x, y, w, h = box
    head_crop = reference_frame[y : y + h, x : x + w]
    head_crop_resized = cv2.resize(head_crop, (512, 512), interpolation=cv2.INTER_AREA)
    head_ref_path = frames_dir / "head_reference.png"
    cv2.imwrite(str(head_ref_path), head_crop_resized)
    logger.info("Saved head reference: %s", head_ref_path)

    # 3. FlashHead: set face + render audio to frames (via HTTP client)
    client = None
    if stub:
        from flashhead_inference import FlashHeadEngine
        engine = FlashHeadEngine(stub=True)
        engine.load()
        generated_frames_dir = engine.generate(
            reference_image_path=head_ref_path,
            audio_path=audio_path,
            output_dir=frames_dir / "flashhead_raw",
            fps=fps,
        )
    else:
        # Start server if needed
        proc = None
        if start_server:
            proc = _start_flashhead_server()
        client = _wait_for_server(proc)

        # Set the face on the server
        client.set_face(head_ref_path)

        # Render audio -> frames
        generated_frames_dir = frames_dir / "flashhead_raw"
        client.render_audio_to_frames(audio_path, generated_frames_dir, fps=fps)

    # Trim trailing idle frames AFTER speech ends (keep leading idle frames
    # so video starts at t=0, in sync with audio start)
    logger.info("Trimming trailing idle frames after speech ends...")
    start_idx, end_idx = detect_speech_frames(
        generated_frames_dir,
        head_ref_path,
        fps=fps,
        motion_threshold=3.0,
        min_speech_frames=2,
        pad_frames=2,
    )
    # Keep everything from frame 0 to end_idx (drop trailing idle after speech)
    if end_idx < len(list(generated_frames_dir.glob("*.png"))) - 1:
        trim_frames(generated_frames_dir, 0, end_idx, generated_frames_dir)

    # 4. Composite each generated head back onto the original frame at the box
    generated_frames = sorted(Path(generated_frames_dir).glob("*.png"))
    if not generated_frames:
        raise RuntimeError("No frames produced by FlashHead in %s" % generated_frames_dir)

    logger.info("Compositing %d frames...", len(generated_frames))
    for i, gf in enumerate(generated_frames):
        head_frame = cv2.imread(str(gf))
        if head_frame is None:
            continue
        comp = composite_head(reference_frame, head_frame, box)
        cv2.imwrite(str(generated_frames_dir / ("lip_frame_%06d.png" % i)), comp)

    # 4b. Pad/trim frames so video duration exactly matches audio duration
    #     (guarantees frame-accurate lip-sync, no drift, audio and video start together)
    import soundfile as sf
    info = sf.info(str(audio_path))
    audio_dur = info.duration
    target_frames = int(round(audio_dur * fps))
    current_frames = len(generated_frames)

    if current_frames < target_frames:
        # Pad with the last frame
        last_frame = cv2.imread(str(generated_frames[-1]))
        pad_needed = target_frames - current_frames
        logger.info("Padding %d frames to match audio duration (%.2fs @ %dfps = %d frames)",
                    pad_needed, audio_dur, fps, target_frames)
        for i in range(current_frames, target_frames):
            cv2.imwrite(str(generated_frames_dir / ("lip_frame_%06d.png" % i)), last_frame)
    elif current_frames > target_frames:
        # Trim excess frames from the end
        logger.info("Trimming %d excess frames (target %d, have %d)",
                    current_frames - target_frames, target_frames, current_frames)
        for i in range(target_frames, current_frames):
            p = generated_frames_dir / ("lip_frame_%06d.png" % i)
            if p.exists():
                p.unlink()

    # 5. Mux frames + audio -> MP4
    final_mp4 = mux_frames_with_audio(generated_frames_dir, audio_path, output_path, fps=fps, audio_delay=audio_delay)
    logger.info("Pipeline complete: %s", final_mp4)

    # Realtime speed stats from the server
    if not stub and client:
        h = client.health()
        if h:
            g = h.get("gpu", {})
            speed = g.get("speed")
            preset_name = g.get("preset", "?")
            took_gb = g.get("took_gb")
            free_gb = g.get("free_gb")
            print("\n" + "=" * 50)
            print("FLASHHEAD REALTIME STATS")
            print("=" * 50)
            print("  GPU:       %s" % g.get("name", "?"))
            print("  Preset:    %s" % preset_name)
            print("  Speed:     %.1fx real time" % speed if speed else "  Speed:     unknown")
            print("  VRAM used: %.1f GB" % took_gb if took_gb else "  VRAM used: unknown")
            print("  VRAM free: %.1f GB" % free_gb if free_gb else "  VRAM free: unknown")
            if speed and speed < 1.0:
                print("  WARNING:  Below 1.0x real time — consider 'smallest' preset")
            elif speed and speed < 1.2:
                print("  NOTICE:   Near 1.0x real time — monitor for drift")
            print("=" * 50 + "\n")

    return final_mp4
