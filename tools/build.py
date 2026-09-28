"""Build the site's images, videos and code listings.

Usage:
    python3 tools/build.py [--paper DIR] [--logs DIR] [--ffmpeg PATH]

Sources:
- Figures and robot photos from the paper repository (--paper).
- One recorded EMPIRIC run per domain from the agent logs (--logs): the
  runs behind the paper's trajectory figures. Each run directory holds
  run.mp4, the harness's recording of every environment step, and
  agent/sandbox/simulator.py, the program the agent wrote.

Outputs go under assets/. The code listings are written into index.html
between the <!-- code:NAME --> and <!-- /code:NAME --> markers, so the
rest of index.html stays hand-edited.
"""
import argparse
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

# Domain -> recorded run, in the order the page shows them.
RUNS = {
    "domino": "domino_high_friction_turn-mb_opus_gate_r1/seed0/run_20260917_082017",
    "bridge": "bridge-mb_opus_benchmark_r2/seed3/run_20260919_124955",
    "balloons": "balloons-mb_opus_benchmark_r2/seed3/run_20260919_124956",
    "boil": "boil-mb_opus_gate_preflight_two_jug_tight_r1/seed1/run_20260917_082805",
    "fan": "fan_ramp-mb_opus_ramp_skill_repair_r1/seed2/run_20260921_090827",
}
# Each recording is 1520x900: the 900x900 scene, then the harness panel.
SCENE_CROP = "crop=900:900:0:0"
HERO_SECONDS = 6.0  # each domain's share of the hero loop
END_TRIM = 0.3  # the last frames repeat the final state

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


def build_videos(ff, logs, out):
    """Copy each run video for streaming, with a poster and a hero clip."""
    out.mkdir(parents=True, exist_ok=True)
    clips = []
    for name, rel in RUNS.items():
        src = logs / rel / "run.mp4"
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
        clip = out / f"hero-{name}.mp4"
        start = length - END_TRIM - HERO_SECONDS
        run([ff, "-v", "error", "-y", "-ss", f"{start:.2f}", "-t",
             f"{HERO_SECONDS}", "-i", str(src), "-vf",
             f"{SCENE_CROP},scale=720:720,fps=20", "-an", "-c:v", "libx264",
             "-preset", "slow", "-crf", "27", "-pix_fmt", "yuv420p",
             str(clip)])
        clips.append(clip)
        print(f"video {name}: {length:.1f} s")
    listing = out / "hero-list.txt"
    listing.write_text("".join(f"file '{c.name}'\n" for c in clips))
    run([ff, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i",
         str(listing), "-c", "copy", "-movflags", "+faststart",
         str(out / "hero.mp4")])
    first = out / "hero-poster.png"
    run([ff, "-v", "error", "-y", "-i", str(clips[0]), "-frames:v", "1",
         str(first)])
    Image.open(first).convert("RGB").save(out / "hero.webp", quality=80,
                                          method=6)
    first.unlink()
    listing.unlink()
    for clip in clips:
        clip.unlink()


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
    parser.add_argument("--ffmpeg")
    parser.add_argument("--only", choices=["figures", "robot", "videos", "code"])
    args = parser.parse_args()
    steps = {
        "figures": lambda: build_figures(args.paper, SITE / "assets" / "img"),
        "robot": lambda: build_robot(args.paper, SITE / "assets" / "img" / "robot"),
        "videos": lambda: build_videos(ffmpeg_path(args.ffmpeg), args.logs,
                                       SITE / "assets" / "video"),
        "code": lambda: build_code(args.logs, SITE / "index.html"),
    }
    for name, step in steps.items():
        if args.only in (None, name):
            step()


if __name__ == "__main__":
    main()
