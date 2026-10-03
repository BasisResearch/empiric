"""Build the site's images, videos and code listings.

Usage:
    python3 tools/build.py [--paper DIR] [--logs DIR] [--ffmpeg PATH]

Sources:
- Figures and robot photos from the paper repository (--paper).
- One recorded EMPIRIC run per domain from the agent logs (--logs): the
  runs behind the paper's trajectory figures. Each run directory holds
  run.mp4, the harness's recording of every environment step, and
  agent/sandbox/simulator.py, the program the agent wrote. The hero
  player shows the scene of each run's test task, cut from its video.

- The real-robot Fan-Domino run (exp_20260922_134142) from the robot's
  logs (--real-robot): casc_explore.mp4 holds its two experiments and
  casc_test.mp4 its test, both cameras side by side.
- The hero player's story videos (--stories): each run from its
  experiments, through the program the agent writes and its plan in its
  own model, to the solved test, composed from the same Cycles renders.

Outputs go under assets/. The code listings are written into index.html
between the <!-- code:NAME --> and <!-- /code:NAME --> markers, so the
rest of index.html stays hand-edited.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

# PIL must load before pymupdf on this cluster, or its libstdc++ clashes.
from PIL import Image  # pylint: disable=import-error
import pymupdf  # pylint: disable=import-error,wrong-import-order
from pygments import highlight  # pylint: disable=import-error
from pygments.formatters import HtmlFormatter  # pylint: disable=import-error
from pygments.lexers import PythonLexer  # pylint: disable=import-error

SITE = Path(__file__).resolve().parents[1]
PAPER = Path("/orcd/home/002/ycliang/sim-predicator-paper")
LOGS = Path("/orcd/home/002/ycliang/predicators/logs/agent_continual")
REAL_ROBOT = Path(
    "/orcd/home/002/ycliang/predicators/logs/real_robot/fan_domino_drive")

# Domain -> recorded run, in the order the page shows them.
RUNS = {
    "domino": "domino_high_friction_turn-mb_opus_gate_r1/seed0/run_20260917_082017",
    "bridge": "bridge-mb_opus_benchmark_r2/seed3/run_20260919_124955",
    "balloons": "balloons-mb_opus_benchmark_r2/seed3/run_20260919_124956",
    "boil": "boil-mb_opus_gate_preflight_two_jug_tight_r1/seed1/run_20260917_082805",
    "fan": "fan_ramp-mb_opus_ramp_skill_repair_r1/seed2/run_20260921_090827",
}
# Every run video is rendered with Blender Cycles from the run's recorded
# states, as the paper figures are, with the harness panel beside it:
# predicators' scripts/paper_figures/export_run_video_scenes.py,
# render_cycles_frames.py and compose_cycles_video.py write
# <domain>/<domain>.mp4 here. The harness's own run.mp4 uses PyBullet's
# renderer, and Balloons and Fan have moved to new layouts since.
CYCLES = Path("/orcd/home/002/ycliang/predicators/logs/paper_run_videos_cycles")
# The story videos, one per domain: make_story.py in ~/claude_sbatch/story
# writes <domain>.mp4 (1080x1080, 20 fps, captions burned in).
STORIES = Path("/home/ycliang/claude_sbatch/story/out")
# Each recording is 1520x900: the 900x900 scene, then the harness panel.
SCENE_CROP = "crop=900:900:0:0"
END_TRIM = 0.3  # the last frames repeat the final state
# The hero player shows each run's test task, the run's last level. The
# panel opens every level with a banner, a coloured box at its foot
# (predicators' continual_video.render_panel); this patch samples it.
BANNER_PATCH = (8, 6, 928, 864)  # width, height, x, y
PANEL_COLORS = {
    "level": (110, 170, 255),  # a level opens
    "won": (90, 200, 120),
    "over": (235, 90, 90),
    "reset": (245, 180, 70),
    "none": (24, 24, 30),  # the panel background: no banner
}

FIGURES = {
    "fig1_residual.pdf": "teaser",
    "fig2_method.pdf": "method",
    "paper-results-opus.pdf": "results",
    "fig3_trajectories.pdf": "runs",
    "figA_trajectories.pdf": "runs-appendix",
}
ROBOT = [
    "fan_cascade/01_green_probe_before.jpg",
    "fan_cascade/02_green_probe_held_upright.jpg",
    "fan_cascade/03_gray_probe_before.jpg",
    "fan_cascade/05_gray_probe_held_flat.jpg",
    "fan_cascade/06_target_relocated.jpg",
    "fan_cascade/07_green_placed_first.jpg",
    "fan_cascade/08_gray_placed_second.jpg",
    "fan_cascade/09_test_button_press.jpg",
    "fan_cascade/10_gray_toppling_toward_green.jpg",
    "fan_cascade/11_gray_reaches_green.jpg",
    "fan_cascade/12_green_toppling.jpg",
    "fan_cascade/13_green_in_new_target.jpg",
]
# The real-robot clips: (source, start, end) in seconds, end None for the
# source's end. Experiment 2 opens at 55.3 s, where the run's captioned cut
# (casc_captioned.mp4, 3.5 s later after its title card) starts the
# "episode 2 / park" caption.
ROBOT_CLIPS = {
    "robot-experiment-1": ("casc_explore.mp4", 0.0, 55.3),
    "robot-experiment-2": ("casc_explore.mp4", 55.3, None),
    "robot-test": ("casc_test.mp4", 0.0, None),
}
# The hero player's real-robot clip: the test from the side camera (the
# left half of casc_test.mp4), cropped square around the blocks, the
# patch and the arm.
ROBOT_HERO_CROP = "crop=540:540:120:0"
# Bridge program excerpts: (first line, last line), 1-based and inclusive.
EXCERPT = [(1, 21), (112, 139), (210, 241)]


def ffmpeg_path(given):
    """The ffmpeg binary: --ffmpeg, $FFMPEG, or imageio-ffmpeg's."""
    if given:
        return given
    if os.environ.get("FFMPEG"):
        return os.environ["FFMPEG"]
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg  # pylint: disable=import-outside-toplevel,import-error
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(cmd):
    subprocess.run(cmd, check=True)


def duration(ff, video):
    """Length of a video in seconds, read from ffmpeg's banner."""
    out = subprocess.run([ff, "-hide_banner", "-i", str(video)],
                         capture_output=True, text=True, check=False).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def build_figures(paper, out):
    """Rasterize each paper figure at 2200 px wide."""
    out.mkdir(parents=True, exist_ok=True)
    for pdf, name in FIGURES.items():
        with pymupdf.open(paper / "figures" / pdf) as doc:
            page = doc[0]
            zoom = 2200 / page.rect.width
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        image.save(out / f"{name}.webp", quality=90, method=6)
        if name == "teaser":
            # Link previews want a JPEG about 1200 px wide.
            preview = image.copy()
            preview.thumbnail((1200, 1200))
            preview.save(out / "og.jpg", quality=85)
        print(f"figure {name}: {image.width}x{image.height}")


def build_robot(paper, out):
    """Resize the robot photos to 960 px wide."""
    out.mkdir(parents=True, exist_ok=True)
    for rel in ROBOT:
        image = Image.open(paper / "figures" / "real_robot" / rel).convert("RGB")
        image.thumbnail((960, 960 * image.height // image.width))
        image.save(out / (Path(rel).stem + ".webp"), quality=82, method=6)
    print(f"robot: {len(ROBOT)} photos")


def banner_runs(ff, video):
    """Each run of banner frames in a run video as (kind, first, last),
    with the video's frame count."""
    w, h, x, y = BANNER_PATCH
    raw = subprocess.run([ff, "-v", "error", "-i", str(video), "-vf",
                          f"crop={w}:{h}:{x}:{y}", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    size = w * h * 3
    kinds = []
    for k in range(0, len(raw), size):
        patch = raw[k:k + size]
        mean = [sum(patch[c::3]) / (w * h) for c in range(3)]
        kinds.append(min(PANEL_COLORS, key=lambda kind, m=mean: sum(
            abs(a - b) for a, b in zip(m, PANEL_COLORS[kind]))))
    runs = []
    start = 0
    for i in range(1, len(kinds) + 1):
        if i == len(kinds) or kinds[i] != kinds[start]:
            if kinds[start] != "none":
                runs.append((kinds[start], start, i - 1))
            start = i
    return runs, len(kinds)


def test_task_start(ff, video, run_dir):
    """The frame where a run video's test task opens (its last level's
    banner), checked against the run's scorecard."""
    card = json.loads((run_dir / "scorecard.json").read_text())
    levels = [level for level in card["levels"] if level["attempted"]]
    runs, total = banner_runs(ff, video)
    starts = [first for kind, first, _ in runs if kind == "level"]
    assert len(starts) == len(levels), (video, runs)
    assert levels[-1]["split"] == "test", run_dir
    return starts[-1], total


def video_source(cycles, name):
    """The run video the page shows for a domain."""
    return cycles / name / f"{name}.mp4"


def build_videos(ff, logs, cycles, out):
    """Copy each run video for streaming, with a poster, and cut its test
    task's scene for the hero player."""
    out.mkdir(parents=True, exist_ok=True)
    for name in RUNS:
        src = video_source(cycles, name)
        length = duration(ff, src)
        # A stream copy keeps the recording as it is; faststart lets
        # browsers begin playback before the whole file arrives.
        run([ff, "-v", "error", "-y", "-i", str(src), "-c", "copy", "-an",
             "-movflags", "+faststart", str(out / f"{name}.mp4")])
        run([ff, "-v", "error", "-y", "-ss", f"{length - END_TRIM:.2f}",
             "-i", str(src), "-frames:v", "1", str(out / f"{name}.png")])
        poster = Image.open(out / f"{name}.png").convert("RGB")
        poster.save(out / f"{name}.webp", quality=80, method=6)
        (out / f"{name}.png").unlink()
        first, total = test_task_start(ff, src, logs / RUNS[name])
        clip = out / f"test-{name}.mp4"
        run([ff, "-v", "error", "-y", "-i", str(src), "-vf",
             f"trim=start_frame={first},setpts=PTS-STARTPTS,{SCENE_CROP},"
             "fps=20",
             "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "26",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(clip)])
        run([ff, "-v", "error", "-y", "-i", str(clip), "-frames:v", "1",
             str(out / f"test-{name}.png")])
        poster = Image.open(out / f"test-{name}.png").convert("RGB")
        poster.save(out / f"test-{name}.webp", quality=80, method=6)
        (out / f"test-{name}.png").unlink()
        print(f"video {name}: {length:.1f} s, test task from frame {first} "
              f"of {total} ({(total - first) / 20:.1f} s)")


def build_stories(ff, stories, out):
    """Copy each domain's story video for streaming, with its title card as
    the poster."""
    out.mkdir(parents=True, exist_ok=True)
    for name in [*RUNS, "robot"]:
        src = stories / f"{name}.mp4"
        clip = out / f"story-{name}.mp4"
        run([ff, "-v", "error", "-y", "-i", str(src), "-c", "copy", "-an",
             "-movflags", "+faststart", str(clip)])
        run([ff, "-v", "error", "-y", "-ss", "1", "-i", str(clip),
             "-frames:v", "1", str(out / f"story-{name}.png")])
        poster = Image.open(out / f"story-{name}.png").convert("RGB")
        poster.save(out / f"story-{name}.webp", quality=82, method=6)
        (out / f"story-{name}.png").unlink()
        print(f"story {name}: {duration(ff, clip):.1f} s, "
              f"{clip.stat().st_size / 1e6:.1f} MB")


def build_robot_videos(ff, real_robot, out):
    """Cut the real-robot run into its experiments and test, with posters,
    and the test's square clip for the hero player."""
    out.mkdir(parents=True, exist_ok=True)
    for name, (source, start, end) in ROBOT_CLIPS.items():
        src = real_robot / source
        stop = duration(ff, src) if end is None else end
        clip = out / f"{name}.mp4"
        run([ff, "-v", "error", "-y", "-ss", f"{start:.2f}", "-i", str(src),
             "-t", f"{stop - start:.2f}", "-an", "-c:v", "libx264",
             "-preset", "slow", "-crf", "27", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", str(clip)])
        run([ff, "-v", "error", "-y", "-i", str(clip), "-frames:v", "1",
             str(out / f"{name}.png")])
        poster = Image.open(out / f"{name}.png").convert("RGB")
        poster.save(out / f"{name}.webp", quality=80, method=6)
        (out / f"{name}.png").unlink()
        print(f"robot video {name}: {stop - start:.1f} s")
    clip = out / "test-robot.mp4"
    run([ff, "-v", "error", "-y", "-i", str(real_robot / "casc_test.mp4"),
         "-vf", ROBOT_HERO_CROP, "-an", "-c:v", "libx264", "-preset", "slow",
         "-crf", "24", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         str(clip)])
    run([ff, "-v", "error", "-y", "-i", str(clip), "-frames:v", "1",
         str(out / "test-robot.png")])
    poster = Image.open(out / "test-robot.png").convert("RGB")
    poster.save(out / "test-robot.webp", quality=80, method=6)
    (out / "test-robot.png").unlink()
    print(f"robot video test-robot: {duration(ff, clip):.1f} s")


def code_html(lines, start):
    """Highlight lines of Python with line numbers from `start`."""
    formatter = HtmlFormatter(nowrap=True)
    body = highlight("".join(lines), PythonLexer(), formatter)
    rows = body.split("\n")
    if rows and rows[-1] == "":
        rows.pop()
    numbered = [
        f'<span class="ln">{start + k}</span>{row}' for k, row in enumerate(rows)
    ]
    return "\n".join(numbered)


def build_code(logs, index):
    """Write the Bridge program's excerpt and full listing into index.html."""
    program = logs / RUNS["bridge"] / "agent" / "sandbox" / "simulator.py"
    lines = program.read_text().splitlines(keepends=True)
    gap = '<span class="gap">⋮</span>'
    excerpt = f"\n{gap}\n".join(
        code_html(lines[a - 1:b], a) for a, b in EXCERPT)
    full = code_html(lines, 1)
    text = index.read_text()
    for name, html in (("excerpt", excerpt), ("full", full)):
        pattern = re.compile(
            rf"(<!-- code:{name} -->).*?(<!-- /code:{name} -->)", re.S)
        assert pattern.search(text), f"missing code:{name} markers"
        text = pattern.sub(lambda m, h=html: m.group(1) + h + m.group(2),
                           text)
    index.write_text(text)
    (SITE / "assets" / "code").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(program, SITE / "assets" / "code" / "bridge_simulator.py")
    print(f"code: {len(lines)} lines")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--paper", type=Path, default=PAPER)
    parser.add_argument("--logs", type=Path, default=LOGS)
    parser.add_argument("--cycles", type=Path, default=CYCLES)
    parser.add_argument("--real-robot", type=Path, default=REAL_ROBOT)
    parser.add_argument("--stories", type=Path, default=STORIES)
    parser.add_argument("--ffmpeg")
    parser.add_argument("--only", choices=["figures", "robot", "videos",
                                           "stories", "robot-videos", "code"])
    args = parser.parse_args()
    steps = {
        "figures": lambda: build_figures(args.paper, SITE / "assets" / "img"),
        "robot": lambda: build_robot(args.paper, SITE / "assets" / "img" / "robot"),
        "videos": lambda: build_videos(ffmpeg_path(args.ffmpeg), args.logs,
                                       args.cycles,
                                       SITE / "assets" / "video"),
        "stories": lambda: build_stories(ffmpeg_path(args.ffmpeg),
                                         args.stories,
                                         SITE / "assets" / "video"),
        "robot-videos": lambda: build_robot_videos(
            ffmpeg_path(args.ffmpeg), args.real_robot,
            SITE / "assets" / "video"),
        "code": lambda: build_code(args.logs, SITE / "index.html"),
    }
    for name, step in steps.items():
        if args.only in (None, name):
            step()


if __name__ == "__main__":
    main()
