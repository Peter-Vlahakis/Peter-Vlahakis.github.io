#!/usr/bin/env python3
"""Cut and encode the site's background clips from Swingarm City.mov.

    .venv\\Scripts\\python tools\\build_hero.py [--clip hero|projects|baja|all] [--source PATH]
                                              [--start S] [--end S] [--xfade S] [--og-only]

Clips (see CLIPS below; --start/--end/--xfade override the chosen clip's defaults):
  hero      Home hero, 1:10-1:33. Writes assets/video/hero-1080.mp4, hero-720.mp4 and
            hero-poster.webp, plus the Open Graph image assets/img/og.jpg (cut from the poster,
            with the name drawn on it as the hero shows it). --og-only rebuilds just og.jpg.
  projects  Projects page side column, 0:35-0:50. A tall 912 x 2160 slice of the 4K frame
            whose center follows the ridge, then the rider. Writes side-projects.mp4 + poster.
  baja      Baja page side column, 6:15-6:35. A fixed slice centered on the ridge.
            Writes side-baja.mp4 + poster.
  The two side-column clips were removed from the site on 2026-10-29 (Revision 2). Their presets
  stay here, tuned, in case they come back; "in_use": False keeps them out of --clip all.
The source is only read.

Brightness: each clip is lifted in the encode (a gamma lift on luma plus a matching
chroma gain, so the colors keep their saturation). It runs in the source's 10-bit
precision and is dithered to 8-bit afterwards, which avoids banding in lifted shadows.

Size rule: start at CRF 23 (preset slow) and raise one step at a time until the file
meets its target, stopping at CRF 28. A CRF 28 file over target but under the hard cap
is kept. If CRF 28 is over the hard cap, that file steps down to the next height in its
ladder. The clip is never shortened.

Loop seam: the last --xfade seconds dissolve into the footage just before --start,
so the jump back to the first frame is continuous. Use --xfade 0 for a hard cut.
"""
from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SITE = Path(__file__).resolve().parent.parent
VIDEO_DIR = SITE / "assets" / "video"
OG_PATH = SITE / "assets" / "img" / "og.jpg"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# The name on the Open Graph image, set like the hero's (.hero__name in css/home.css): Inter 700,
# tracking -0.035em, the two words 0.26em apart, in --text with the --hero-text-halo shadows behind.
# 114 px is the hero name's size in a 1200 px wide window (--fs-hero is 9.5vw there).
OG_NAME = ("Peter", "Vlahakis")
OG_FONT = SITE / "assets" / "fonts" / "inter-latin-wght-normal.woff2"
OG_SIZE, OG_WEIGHT, OG_TRACKING, OG_WORD_GAP = 114, 700, -0.035, 0.26
OG_HALO = [(0, 1, 0.70), (0, 4, 0.55), (2, 20, 0.40)]  # --hero-text-halo: (y offset px, blur px, opacity)
TOKENS = SITE / "css" / "tokens.css"

MB = 1_000_000
KB = 1_000
CRF_START, CRF_MAX = 23, 28
MAX_FPS = 30.0
HDR_TRANSFERS = ("smpte2084", "arib-std-b67")
BT709 = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv"]
# HDR (HLG or PQ) to SDR BT.709. Also used by build_media.py for clips.
TONEMAP = ["zscale=t=linear:npl=100", "format=gbrpf32le", "zscale=p=bt709",
           "tonemap=tonemap=hable:desat=0", "zscale=t=bt709:m=bt709:r=tv"]
SIDE_WIDTH = 912  # about 0.42 x 2160: the widest shape the side columns take; CSS cover trims narrower ones

# outputs: (file name, heights to try in order, target bytes, hard cap bytes).
# lift: (gamma, chroma gain); gamma > 1 brightens. crop: None, or keyframes of the slice
# center as (seconds into the source, x in source pixels), eased between keyframes.
CLIPS = {
    "hero": {
        "start": 70.0, "end": 93.0, "xfade": 0.5,
        "lift": (1.18, 1.22),
        "crop": None,
        "outputs": [("hero-1080.mp4", (1080, 720), 8 * MB, 12 * MB),
                    ("hero-720.mp4", (720, 540), 4 * MB, 6 * MB)],
        "poster": ("hero-poster.webp", 1920, 200 * KB, 300 * KB),
        "og": True,
    },
    "projects": {
        "start": 35.0, "end": 50.0, "xfade": 0.5,
        "lift": (1.35, 1.55),
        # The ridge first; the rider comes down its left face from 0:42 at x 1750-1810,
        # then rides right to about x 2030 by 0:50 (checked every 0.5 s).
        "crop": [(35.0, 1920), (41.0, 1920), (42.5, 1860), (48.0, 1860), (50.0, 2010)],
        "outputs": [("side-projects.mp4", (2160, 1440, 1080), 8 * MB, 12 * MB)],
        "poster": ("side-projects-poster.webp", SIDE_WIDTH, 250 * KB, 400 * KB),
        "og": False,
        "in_use": False,
    },
    "baja": {
        "start": 375.0, "end": 395.0, "xfade": 0.5,
        "lift": (1.35, 1.55),
        # The fin spans about x 1400-2320 for the whole clip, peak near 2130 (checked every 1 s).
        "crop": [(375.0, 1900)],
        "outputs": [("side-baja.mp4", (2160, 1440, 1080), 8 * MB, 12 * MB)],
        "poster": ("side-baja-poster.webp", SIDE_WIDTH, 250 * KB, 400 * KB),
        "og": False,
        "in_use": False,
    },
}


def run(args: list[str], capture: bool = False) -> subprocess.CompletedProcess:
    proc = subprocess.run([FFMPEG, "-hide_banner", "-nostdin", *args], capture_output=True)
    if proc.returncode and not capture:
        sys.exit("ffmpeg failed:\n" + proc.stderr.decode("utf-8", "replace")[-3000:])
    return proc


def probe(src: Path) -> dict:
    """There is no ffprobe in the bundle, so read stream info from `ffmpeg -i`."""
    text = run(["-i", str(src)], capture=True).stderr.decode("utf-8", "replace")
    line = next((ln for ln in text.splitlines() if "Video:" in ln), "")
    size = re.search(r",\s*(\d{2,5})x(\d{2,5})[\s,\[]", line)
    fps = re.search(r"([\d.]+)\s*fps", line)
    if not (size and fps):
        sys.exit(f"could not read a video stream from {src}\n{text}")
    rotation = re.search(r"rotation of (-?[\d.]+) degrees", text)
    duration = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", text)
    return {
        "width": int(size.group(1)),
        "height": int(size.group(2)),
        "fps": float(fps.group(1)),
        "codec": (re.search(r"Video:\s*([^,]+)", line) or [None, "?"])[1].strip(),
        "pix_fmt": (re.search(r"(yuvj?\d{3}p\w*|gbrp\w*|p01\dle)", line) or [None, "?"])[1],
        "color": (re.search(r"p\w*\(([^)]*)\)", line) or [None, "untagged"])[1],
        "rotation": float(rotation.group(1)) if rotation else 0.0,
        "hdr": any(t in line for t in HDR_TRANSFERS),
        "audio": "Audio:" in text,
        "duration": sum(float(x) * m for x, m in zip(duration.groups(), (3600, 60, 1))) if duration else 0.0,
    }


def fps_fraction(fps: float) -> str:
    for num, den in ((24000, 1001), (30000, 1001), (24, 1), (25, 1), (30, 1)):
        if abs(fps - num / den) < 0.01:
            return f"{num}/{den}"
    return f"{min(fps, MAX_FPS):.3f}"


def lift_filter(gamma: float, gain: float) -> str:
    """Gamma lift on luma and a chroma gain around neutral, at the input's bit depth."""
    mid = "(minval+maxval)/2"
    chroma = f"'clip((val-{mid})*{gain}+{mid},minval,maxval)'"
    return f"lutyuv=y='gammaval({1 / gamma:.4f})':u={chroma}:v={chroma}"


def crop_filter(keys: list[tuple[float, float]], offset: float, width: int, height: int) -> str:
    """Crop a width x height slice whose center eases (smoothstep) between keyframes.

    `t` in the filter counts from the first decoded frame, which is `offset` seconds into the source.
    """
    def x_at(i: int) -> str:
        (t0, x0), (t1, x1) = keys[i], keys[i + 1]
        u = f"clip((T-{t0})/{t1 - t0},0,1)"
        return f"{x0}+({x1 - x0})*({u}*{u}*(3-2*{u}))"

    expr = str(keys[-1][1])
    for i in range(len(keys) - 2, -1, -1):
        expr = f"if(lt(T,{keys[i + 1][0]}),{x_at(i)},{expr})"
    expr = expr.replace("T", f"(t+{offset:.4f})")
    return f"crop={width}:{height}:'clip({expr}-{width / 2},0,iw-{width})':0"


def make_mezzanine(src: Path, info: dict, clip: dict, height: int, out: Path) -> tuple[str, int]:
    """Lossless working copy at the top output height: cropped, lifted, loop dissolve applied."""
    start, end, xfade = clip["start"], clip["end"], clip["xfade"]
    rate = fps_fraction(min(info["fps"], MAX_FPS))
    fps = float(Fraction(rate))
    total = round((end - start) * fps)
    n_x = min(round(xfade * fps), int(start * fps), total // 4)
    seek = start - n_x / fps
    chain = []
    if info["hdr"]:
        print("  HDR source: tone-mapping to SDR BT.709 (zscale + tonemap)")
        chain += TONEMAP
    chain.append(f"fps={rate}")
    if clip["crop"]:
        chain.append(crop_filter(clip["crop"], seek, SIDE_WIDTH, info["height"]))
    if clip["lift"]:
        chain.append(lift_filter(*clip["lift"]))
    chain += [f"scale=-2:{height}:flags=lanczos", "format=yuv420p"]
    pre = ",".join(chain)
    if n_x:
        graph = (
            f"[0:v]{pre},split=3[a][b][c];"
            f"[a]trim=start_frame={n_x}:end_frame={total},setpts=PTS-STARTPTS[head];"
            f"[b]trim=start_frame={total}:end_frame={total + n_x},setpts=PTS-STARTPTS[tail];"
            f"[c]trim=start_frame=0:end_frame={n_x},setpts=PTS-STARTPTS[lead];"
            f"[tail][lead]blend=all_expr='A*(1-(N+1)/{n_x + 1})+B*(N+1)/{n_x + 1}'[mix];"
            f"[head][mix]concat=n=2:v=1:a=0[out]"
        )
    else:
        graph = f"[0:v]{pre},trim=end_frame={total},setpts=PTS-STARTPTS[out]"
    run(["-y", "-ss", f"{seek:.4f}", "-t", f"{(total + n_x + 4) / fps:.4f}", "-i", str(src),
         "-filter_complex", graph, "-map", "[out]", "-an",
         "-c:v", "libx264", "-qp", "0", "-preset", "ultrafast", "-pix_fmt", "yuv420p", *BT709, str(out)])
    return rate, n_x


def encode(mezz: Path, out: Path, height: int, crf: int, rate: str) -> int:
    run(["-y", "-i", str(mezz), "-vf", f"scale=-2:{height}:flags=lanczos", "-an", "-map_metadata", "-1",
         "-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-profile:v", "high", "-pix_fmt", "yuv420p",
         "-r", rate, *BT709, "-movflags", "+faststart", str(out)])
    return out.stat().st_size


def encode_to_budget(mezz: Path, out: Path, heights: tuple[int, ...], target: int, cap: int, rate: str) -> dict:
    for height in heights:
        for crf in range(CRF_START, CRF_MAX + 1):
            size = encode(mezz, out, height, crf, rate)
            print(f"  {out.name}: {height}p crf {crf} -> {size / MB:.2f} MB")
            if size <= target:
                break
        if size <= cap:
            break
        print(f"  {out.name}: CRF {CRF_MAX} is over the hard cap at {height}p, stepping down")
    return {"file": out.name, "height": height, "crf": crf, "bytes": size, "within_target": size <= target, "within_cap": size <= cap}


def first_frame(mezz: Path) -> Image.Image:
    png = run(["-i", str(mezz), "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-"], capture=True).stdout
    return Image.open(io.BytesIO(png)).convert("RGB")


def source_first_frame(src: Path, info: dict, clip: dict, height: int) -> Image.Image:
    """The clip's first frame for --og-only, made the way the full build makes it: a plain seek to
    --start lands a frame away, because the mezzanine starts early for the loop dissolve. A few
    seconds of mezzanine are enough (the dissolve length is capped at a quarter of the clip)."""
    short = dict(clip, end=min(clip["end"], clip["start"] + 4 * clip["xfade"] + 1))
    with tempfile.TemporaryDirectory() as tmp:
        mezz = Path(tmp) / "mezzanine.mkv"
        make_mezzanine(src, info, short, height, mezz)
        return first_frame(mezz)


def save_poster(frame: Image.Image, out: Path, max_width: int, target: int) -> tuple[int, int]:
    if frame.width > max_width:
        frame = frame.resize((max_width, round(frame.height * max_width / frame.width)), Image.LANCZOS)
    for q in range(84, 38, -4):
        buf = io.BytesIO()
        frame.save(buf, "WEBP", quality=q, method=6)
        if buf.tell() <= target:
            break
    out.write_bytes(buf.getvalue())
    return buf.tell(), q


def token_color(name: str) -> tuple[int, int, int]:
    """A #rrggbb color token from css/tokens.css, so the palette stays in that one file."""
    m = re.search(rf"--{name}:\s*#([0-9a-fA-F]{{6}})\s*;", TOKENS.read_text(encoding="utf-8"))
    if not m:
        sys.exit(f"css/tokens.css has no #rrggbb value for --{name}")
    return tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4))


def draw_name(og: Image.Image) -> Image.Image:
    """The name, centered on the image, with the halo under it."""
    font = ImageFont.truetype(str(OG_FONT), OG_SIZE)
    font.set_variation_by_axes([OG_WEIGHT])
    track, glyphs, x = OG_TRACKING * OG_SIZE, [], 0.0
    for n, word in enumerate(OG_NAME):
        if n:
            x += OG_WORD_GAP * OG_SIZE
        for i, ch in enumerate(word):
            # The pen position before ch, kerned against the letter before it, plus the tracking so far
            glyphs.append((x + font.getlength(word[:i + 1]) - font.getlength(ch) + i * track, ch))
        x += font.getlength(word) + len(word) * track

    def text_mask(dx: float, dy: float) -> Image.Image:
        mask = Image.new("L", og.size, 0)
        pen = ImageDraw.Draw(mask)
        for gx, ch in glyphs:
            pen.text((dx + gx, dy), ch, font=font, fill=255, anchor="ls")
        return mask

    # Center the letters themselves, not the line box (the name has capitals and ascenders, no descenders)
    left, top, right, bottom = text_mask(0, OG_SIZE).getbbox()
    mask = text_mask((og.width - (right - left)) / 2 - left, (og.height - (bottom - top)) / 2 - top + OG_SIZE)

    out = og.copy()
    shade = Image.new("RGB", og.size, token_color("hero-scrim-color"))
    for dy, blur, opacity in OG_HALO:
        halo = mask.transform(og.size, Image.AFFINE, (1, 0, 0, 0, 1, -dy)).filter(ImageFilter.GaussianBlur(blur / 2))
        out = Image.composite(shade, out, halo.point(lambda v: round(v * opacity)))
    return Image.composite(Image.new("RGB", og.size, token_color("text")), out, mask)


def save_og(frame: Image.Image, out: Path) -> int:
    w, h = frame.size
    crop_h = min(h, round(w * 630 / 1200))
    crop_w = round(crop_h * 1200 / 630)
    left, top = (w - crop_w) // 2, (h - crop_h) // 2
    og = frame.crop((left, top, left + crop_w, top + crop_h)).resize((1200, 630), Image.LANCZOS)
    og = draw_name(og)
    out.parent.mkdir(parents=True, exist_ok=True)
    og.save(out, "JPEG", quality=84, optimize=True, progressive=True)
    return out.stat().st_size


def build(name: str, clip: dict, src: Path, info: dict) -> bool:
    if not 0 <= clip["start"] < clip["end"] <= (info["duration"] or clip["end"]):
        sys.exit(f"{name}: --start/--end are outside the source")
    print(f"\n{name}: {clip['start']:g}s to {clip['end']:g}s, lift gamma {clip['lift'][0]} chroma x{clip['lift'][1]}")
    top = min(max(h for _, heights, _, _ in clip["outputs"] for h in heights), info["height"])
    with tempfile.TemporaryDirectory() as tmp:
        mezz = Path(tmp) / "mezzanine.mkv"
        rate, n_x = make_mezzanine(src, info, clip, top, mezz)
        print(f"  {rate} fps, loop dissolve {n_x} frames")
        results = [encode_to_budget(mezz, VIDEO_DIR / out, tuple(min(h, top) for h in heights), target, cap, rate)
                   for out, heights, target, cap in clip["outputs"]]
        frame = first_frame(mezz)
        poster_name, poster_width, poster_target, poster_cap = clip["poster"]
        poster_bytes, poster_q = save_poster(frame, VIDEO_DIR / poster_name, poster_width, poster_target)
        og_bytes = save_og(frame, OG_PATH) if clip["og"] else 0

    for r in results:
        state = "within target" if r["within_target"] else ("over target, within hard cap" if r["within_cap"] else "OVER HARD CAP")
        print(f"  result {r['file']}: {r['height']}p  crf {r['crf']}  {r['bytes'] / MB:.2f} MB  ({state})")
    poster_state = "within target" if poster_bytes <= poster_target else ("within hard cap" if poster_bytes <= poster_cap else "OVER HARD CAP")
    print(f"  result {poster_name}: {min(frame.width, poster_width)} wide  q{poster_q}  {poster_bytes / KB:.0f} KB  ({poster_state})")
    if og_bytes:
        print(f"  result og.jpg: 1200x630  {og_bytes / KB:.0f} KB")
    return all(r["within_cap"] for r in results) and poster_bytes <= poster_cap


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--clip", choices=[*CLIPS, "all"], default="hero")
    ap.add_argument("--source", default=str(SITE.parent / "Swingarm City.mov"))
    ap.add_argument("--start", type=float, help="clip start in seconds (overrides the clip's default)")
    ap.add_argument("--end", type=float, help="clip end in seconds (overrides the clip's default)")
    ap.add_argument("--xfade", type=float, help="loop dissolve in seconds; 0 for a hard cut")
    ap.add_argument("--og-only", action="store_true", help="rebuild only assets/img/og.jpg, without the video")
    args = ap.parse_args()
    src = Path(args.source).resolve()
    if SITE in src.parents:
        sys.exit("the source video must stay outside the site repo")
    names = [n for n in CLIPS if CLIPS[n].get("in_use", True)] if args.clip == "all" else [args.clip]
    if not CLIPS[names[0]].get("in_use", True):
        print(f"note: no page uses the {names[0]} clip; check_site.py has no budget for its files")
    if len(names) > 1 and any(v is not None for v in (args.start, args.end, args.xfade)):
        sys.exit("--start/--end/--xfade apply to one clip at a time")

    info = probe(src)
    print(f"source: {info['width']}x{info['height']}  {info['fps']} fps  {info['codec']}  {info['pix_fmt']} ({info['color']})"
          f"  rotation {info['rotation']:g}  {'HDR' if info['hdr'] else 'SDR'}  audio {'yes' if info['audio'] else 'no'}"
          f"  duration {info['duration']:.2f}s")
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    ok = True
    for name in names:
        clip = dict(CLIPS[name])
        for key in ("start", "end", "xfade"):
            if getattr(args, key) is not None:
                clip[key] = getattr(args, key)
        if args.og_only:
            if not clip["og"]:
                sys.exit(f"{name}: this clip makes no Open Graph image")
            top = min(max(h for _, heights, _, _ in clip["outputs"] for h in heights), info["height"])
            og_bytes = save_og(source_first_frame(src, info, clip, top), OG_PATH)
            print(f"  result og.jpg: 1200x630  {og_bytes / KB:.0f} KB")
            continue
        if clip["crop"] and info["width"] < SIDE_WIDTH:
            sys.exit(f"{name}: the source is narrower than the {SIDE_WIDTH} px slice")
        ok = build(name, clip, src, info) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
