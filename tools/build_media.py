#!/usr/bin/env python3
"""Import and optimise site media.

Reads tools/media_map.json, pulls each listed source from the media folder
(default: the parent of this repo) and writes metadata-free WebP files to
assets/img/, plus data/manifest.json. Nothing outside the map is imported and
the media folder is only ever read.

Animated sources (GIF, animated WebP, APNG) become animated WebP files at 640 and
1280 wide that keep every frame, each frame's duration, and loop forever, plus a
still poster (<id>-poster-<width>.webp; the first frame unless the map entry sets
"poster_frame"). Their manifest entries carry "animated": true and a "poster".
Size is a soft target: quality is lowered towards it, but no width or frame is dropped.

Baja, Projects, and About gallery images (ids starting "baja/", "projects/", or "about/gallery/")
also get one 2560 px wide still,
<id>-2560.webp, when the source is at least that wide. It is not in any srcset: the page's expanded view loads it on
click, from the manifest entry's "large". Its quality steps down towards LARGE_TARGET_BYTES;
a file still over LARGE_CAP_BYTES at LARGE_MIN_QUALITY is not written and is reported.

    .venv\\Scripts\\python tools\\build_media.py [--source PATH] [--force]

A second run with no changes rewrites nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image, ImageChops, ImageCms, ImageOps, ImageSequence

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HAVE_HEIF = True
except ImportError:  # HEIC sources are skipped and reported
    HAVE_HEIF = False

SITE = Path(__file__).resolve().parent.parent
MAP_PATH = SITE / "tools" / "media_map.json"
STATE_PATH = SITE / "tools" / "media_state.json"
MANIFEST_PATH = SITE / "data" / "manifest.json"
IMG_DIR = SITE / "assets" / "img"

WIDTHS = (640, 1280, 1920)
MAX_BYTES = 600_000  # per-file budget for content images
MIN_QUALITY = 70
SETTINGS_VERSION = 4  # bump to force a rebuild after changing encode settings
ID_RE = re.compile(r"^[a-z0-9]+(?:[-/][a-z0-9]+)*$")
BLOCKED = ("yashss",)  # another person's work; never imported
HEIF_EXTS = {".heic", ".heif"}
PHOTO_QUALITY = {"photo": 80, "render": 86}
TEXT_KINDS = {"screenshot", "plot", "graphic"}  # text must stay crisp
SRGB = ImageCms.createProfile("sRGB")

# Animations. Their settings live outside SETTINGS_VERSION so changing them never re-encodes the stills.
ANIM_WIDTHS = (640, 1280)
# Soft target per animated file: quality steps down from ANIM_QUALITY towards it and stops at
# ANIM_MIN_QUALITY. A file still over the target is kept and reported; nothing is dropped.
ANIM_TARGET_BYTES = 1_500_000
ANIM_QUALITY = 85  # starting quality
ANIM_MIN_QUALITY = 60  # FEA legend text is still readable at 1280 wide here
ANIM_QUALITY_STEP = 5
# Pillow's lossy default puts a key frame every 5 frames, which tripled the size of the FEA
# screen recordings. One every 76-150 frames costs nothing for a short clip that loops.
ANIM_KEYFRAMES = (76, 150)  # kmin, kmax
ANIM_METHOD = 4  # method 6 is several times slower for a few percent
ANIM_SETTINGS_VERSION = 2  # bump to re-encode the animations only

# Expanded-view stills (see the docstring). Settings live outside SETTINGS_VERSION, so changing
# them never re-encodes the page images.
LARGE_PREFIXES = ("baja/", "projects/", "about/gallery/")  # the About headshot does not open, so it gets none
LARGE_WIDTH = 2560
LARGE_TARGET_BYTES = 1_200_000  # soft: quality steps down towards it
LARGE_CAP_BYTES = 2_000_000  # hard: never written above this
LARGE_QUALITY = 80  # starting quality for photos; text kinds start at 88
LARGE_MIN_QUALITY = 60
LARGE_SETTINGS_VERSION = 1

# Short silent clips ("videos" in the map): H.264 MP4 in assets/video/clips/, plus a still poster.
CLIP_DIR = SITE / "assets" / "video" / "clips"
CLIP_HEIGHT = 720  # never above the source
CLIP_CRF = 26  # starting CRF
CLIP_MAX_CRF = 28
CLIP_TARGET_BYTES = 5_000_000  # soft: reported, never enforced
CLIP_SETTINGS_VERSION = 1


def rungs_for(src_w: int) -> list[int]:
    """Standard widths that fit the source, plus its native width. Never upscale."""
    rungs = [w for w in WIDTHS if w <= src_w]
    if src_w < WIDTHS[-1] and src_w not in rungs:
        # Keep the native size as the top rung; drop a rung that is nearly the same.
        rungs = [w for w in rungs if src_w / w >= 1.25] + [src_w]
    return rungs


def load_rgb(path: Path) -> Image.Image:
    """Open, apply EXIF orientation, convert to sRGB, drop a fully opaque alpha."""
    im = Image.open(path)
    im.load()
    icc = im.info.get("icc_profile")
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        if im.getchannel("A").getextrema() == (255, 255):
            im = im.convert("RGB")
    elif im.mode != "RGB":
        im = im.convert("RGB")
    if icc and im.mode == "RGB":
        try:
            im = ImageCms.profileToProfile(im, ImageCms.ImageCmsProfile(io.BytesIO(icc)), SRGB, outputMode="RGB")
        except ImageCms.PyCMSError:
            pass  # unreadable profile: keep the pixels as they are
    return im


def encode(im: Image.Image, kind: str, quality: int | None = None) -> tuple[bytes, str]:
    """Return WebP bytes with no metadata, and a short note on the settings used."""

    def webp(**kw) -> bytes:
        buf = io.BytesIO()
        im.save(buf, "WEBP", method=6, exif=b"", icc_profile=None, xmp=b"", **kw)
        return buf.getvalue()

    if kind in TEXT_KINDS and quality is None:
        lossless = webp(lossless=True, quality=90)
        lossy = webp(quality=92, use_sharp_yuv=True)
        return (lossless, "lossless") if len(lossless) <= len(lossy) else (lossy, "q92")
    q = quality if quality is not None else PHOTO_QUALITY.get(kind, 80)
    return webp(quality=q, use_sharp_yuv=kind != "photo"), f"q{q}"


def encode_to_budget(im: Image.Image, kind: str) -> tuple[bytes, str]:
    """encode(), then lower the quality in steps until the file fits MAX_BYTES or reaches MIN_QUALITY."""
    data, note = encode(im, kind)
    q = 88 if kind in TEXT_KINDS else PHOTO_QUALITY.get(kind, 80)
    while len(data) > MAX_BYTES and q > MIN_QUALITY:
        q = max(MIN_QUALITY, q - 4)
        data, note = encode(im, kind, q)
    return data, note


def is_animation(im: Image.Image) -> bool:
    """True for timed frames. Pillow also reports is_animated for multi-picture JPEGs (MPO, most
    iPhone photos) and multi-image HEIC, whose extra pictures are previews or depth maps."""
    return bool(getattr(im, "is_animated", False)) and "duration" in im.info


def scaled_frames(path: Path, width: int, only: int | None = None) -> tuple[list[Image.Image], list[int]]:
    """Composited frames (or just frame `only`), oriented, in sRGB, without metadata, scaled to `width`.
    One width at a time, so a long clip never sits in memory at full size."""
    with Image.open(path) as im:
        mode = "RGBA" if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info else "RGB"
        icc = im.info.get("icc_profile")
        to_srgb = None
        if icc and mode == "RGB":
            try:
                to_srgb = ImageCms.buildTransform(ImageCms.ImageCmsProfile(io.BytesIO(icc)), SRGB, "RGB", "RGB")
            except ImageCms.PyCMSError:
                pass  # unreadable profile: keep the pixels as they are
        frames, durations = [], []
        for index, frame in enumerate(ImageSequence.Iterator(im)):
            if only is not None and index < only:
                continue
            durations.append(int(frame.info.get("duration", 0)))
            f = ImageOps.exif_transpose(frame.convert(mode))
            if to_srgb is not None:
                f = ImageCms.applyTransform(f, to_srgb)
            if f.width != width:
                f = f.resize((width, round(f.height * width / f.width)), Image.LANCZOS, reducing_gap=3.0)
            f.info = {}
            frames.append(f)
            if only is not None:
                break
    return frames, durations


def keep_every_frame(frames: list[Image.Image], quality: int) -> tuple[list[Image.Image], int]:
    """libwebp drops a frame that is within its lossy tolerance of the frame before it and stretches
    the earlier frame's duration instead (exact repeats at any quality; near repeats at low quality).
    For each such frame, move one corner pixel just past that tolerance so the frame is kept.
    Returns the frames to encode and how many were adjusted."""
    q = (quality / 100) ** 0.5
    tolerance = int(31 * (1 - q) + q + 0.5)  # libwebp's QualityToMaxDiff()
    out, adjusted = [frames[0]], 0
    for frame in frames[1:]:
        prev = out[-1]
        diff = ImageChops.difference(prev.convert("RGB"), frame.convert("RGB"))
        if max(high for _, high in diff.getextrema()) <= tolerance:
            frame = frame.copy()
            pixel = list(frame.getpixel((0, 0)))
            ref = prev.getpixel((0, 0))[2]
            pixel[2] = ref - (tolerance + 1) if ref > tolerance else ref + tolerance + 1
            frame.putpixel((0, 0), tuple(pixel))
            adjusted += 1
        out.append(frame)
    return out, adjusted


def encode_animation(frames: list[Image.Image], durations: list[int], quality: int) -> tuple[bytes, int]:
    frames, adjusted = keep_every_frame(frames, quality)
    buf = io.BytesIO()
    frames[0].save(buf, "WEBP", save_all=True, append_images=frames[1:], duration=durations, loop=0,
                   quality=quality, method=ANIM_METHOD, kmin=ANIM_KEYFRAMES[0], kmax=ANIM_KEYFRAMES[1],
                   background=(0, 0, 0, 0), exif=b"", icc_profile=None, xmp=b"")
    return buf.getvalue(), adjusted


def build_animation(job: dict) -> dict:
    """Animated WebP at 640 and 1280 wide (never upscaled), each with a still poster."""
    src = Path(job["src_path"])
    with Image.open(src) as im:
        n_frames = im.n_frames
        native_w = ImageOps.exif_transpose(im.convert("RGB")).width
    rungs = [w for w in ANIM_WIDTHS if w <= native_w] or [native_w]
    poster_frame = job.get("poster_frame") or 0
    notes = []
    if not 0 <= poster_frame < n_frames:
        notes.append(f"poster_frame {poster_frame} is outside 0-{n_frames - 1}; used frame 0")
        poster_frame = 0
    variants, posters = [], []
    for w in rungs:
        frames, durations = scaled_frames(src, w)
        q = ANIM_QUALITY
        data, adjusted = encode_animation(frames, durations, q)
        while len(data) > ANIM_TARGET_BYTES and q > ANIM_MIN_QUALITY:
            q = max(ANIM_MIN_QUALITY, q - ANIM_QUALITY_STEP)
            data, adjusted = encode_animation(frames, durations, q)
        h = frames[0].height
        del frames
        if len(data) > ANIM_TARGET_BYTES:
            notes.append(f"{w}w is {len(data) / 1e6:.2f} MB at q{q}, over the {ANIM_TARGET_BYTES / 1e6:.1f} MB target (kept)")
        elif q != ANIM_QUALITY:
            notes.append(f"{w}w lowered to q{q} to meet the {ANIM_TARGET_BYTES / 1e6:.1f} MB target")
        poster, _ = scaled_frames(src, w, only=poster_frame)
        poster_data, poster_note = encode_to_budget(poster[0], job["kind"])
        if len(poster_data) > MAX_BYTES:
            notes.append(f"{w}w poster is {len(poster_data) // 1000} KB at {poster_note}, over the image budget")
        variants.append({"w": w, "h": h, "rel": f"assets/img/{job['id']}-{w}.webp", "data": data,
                         "frames": len(durations), "quality": q, "adjusted": adjusted})
        posters.append({"w": w, "h": h, "rel": f"assets/img/{job['id']}-poster-{w}.webp", "data": poster_data,
                        "frame": poster_frame, "quality": poster_note})
    return {"id": job["id"], "animated": True, "variants": variants, "posters": posters, "notes": notes}


def build_large(im: Image.Image, job: dict) -> tuple[dict | None, list[str]]:
    """The expanded-view still: LARGE_WIDTH wide, or nothing if the source is narrower."""
    if im.width < LARGE_WIDTH:
        return None, []
    h = round(im.height * LARGE_WIDTH / im.width)
    scaled = im.resize((LARGE_WIDTH, h), Image.LANCZOS, reducing_gap=3.0)
    q = 88 if job["kind"] in TEXT_KINDS else LARGE_QUALITY
    data, _ = encode(scaled, job["kind"], q)
    while len(data) > LARGE_TARGET_BYTES and q > LARGE_MIN_QUALITY:
        q = max(LARGE_MIN_QUALITY, q - 4)
        data, _ = encode(scaled, job["kind"], q)
    if len(data) > LARGE_CAP_BYTES:
        return None, [f"{LARGE_WIDTH}w is {len(data) / 1e6:.2f} MB at q{q}, over the {LARGE_CAP_BYTES / 1e6:.0f} MB cap (not written)"]
    notes = []
    if len(data) > LARGE_TARGET_BYTES:
        notes.append(f"{LARGE_WIDTH}w is {len(data) / 1e6:.2f} MB at q{q}, over the {LARGE_TARGET_BYTES / 1e6:.1f} MB target (kept)")
    return {"w": LARGE_WIDTH, "h": h, "rel": f"assets/img/{job['id']}-{LARGE_WIDTH}.webp", "data": data, "quality": f"q{q}"}, notes


def build_one(job: dict) -> dict:
    """Encode every rung for one map entry (or only its expanded-view still). Runs in a worker process."""
    src = Path(job["src_path"])
    kind = job["kind"]
    with Image.open(src) as probe:
        if is_animation(probe):
            return build_animation(job)
    im = load_rgb(src)
    if job.get("only_large"):
        large, notes = build_large(im, job)
        return {"id": job["id"], "only_large": True, "large": large, "notes": notes}
    out, notes = [], []
    rungs = rungs_for(im.width)
    # If the top rung has to be dropped, fall back to the next standard width.
    spare = [w for w in WIDTHS if w < im.width and w not in rungs]
    queue = list(rungs)
    while queue:
        w = queue.pop(0)
        h = round(im.height * w / im.width)
        scaled = im if w == im.width else im.resize((w, h), Image.LANCZOS, reducing_gap=3.0)
        data, note = encode_to_budget(scaled, kind)
        if len(data) > MAX_BYTES:
            if w == rungs[-1] and len(rungs) > 1:
                notes.append(f"dropped {w}w ({len(data) // 1000} KB at {note}, over budget)")
                if spare and spare[-1] > rungs[-2]:
                    queue.append(spare[-1])
                continue
            notes.append(f"{w}w is {len(data) // 1000} KB at {note}, over budget")
        elif note not in ("lossless", "q92", f"q{PHOTO_QUALITY.get(kind, 80)}"):
            notes.append(f"{w}w lowered to {note} to meet budget")
        out.append({"w": w, "h": h, "rel": f"assets/img/{job['id']}-{w}.webp", "data": data})
    large = None
    if job.get("large"):
        large, large_notes = build_large(im, job)
        notes += large_notes
    return {"id": job["id"], "variants": out, "large": large, "notes": notes}


def exact_file(root: Path, rel: str) -> Path | None:
    """Resolve rel under root, matching every name exactly (Windows ignores case)."""
    cur = root
    for part in Path(rel).parts:
        if part in ("..", ".") or not cur.is_dir() or part not in {p.name for p in cur.iterdir()}:
            return None
        cur = cur / part
    return cur if cur.is_file() else None


def signature(entry: dict, src: Path) -> str:
    st = src.stat()
    blob = json.dumps([entry["id"], entry["src"], entry.get("kind", "photo"), st.st_size, st.st_mtime_ns,
                       SETTINGS_VERSION, WIDTHS, MAX_BYTES], sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()


def anim_signature(sig: str, entry: dict) -> str:
    """The still signature plus the animation settings, so changing those re-encodes only animations."""
    blob = json.dumps([sig, ANIM_SETTINGS_VERSION, ANIM_WIDTHS, ANIM_TARGET_BYTES, ANIM_QUALITY, ANIM_MIN_QUALITY,
                       ANIM_QUALITY_STEP, ANIM_KEYFRAMES, ANIM_METHOD, MAX_BYTES, entry.get("poster_frame", 0)])
    return hashlib.sha1(blob.encode()).hexdigest()


def wants_large(entry: dict) -> bool:
    return entry["id"].startswith(LARGE_PREFIXES)


def large_signature(sig: str) -> str:
    """The still signature plus the expanded-view settings, so changing those re-encodes only that file."""
    blob = json.dumps([sig, LARGE_SETTINGS_VERSION, LARGE_WIDTH, LARGE_TARGET_BYTES, LARGE_CAP_BYTES,
                       LARGE_QUALITY, LARGE_MIN_QUALITY])
    return hashlib.sha1(blob.encode()).hexdigest()


def srcset_of(variants: list[dict]) -> dict:
    default = max((v for v in variants if v["w"] <= 1280), key=lambda v: v["w"], default=variants[0])
    return {"default": default, "srcset": ", ".join(f"{v['rel']} {v['w']}w" for v in variants)}


def clip_signature(entry: dict, src: Path) -> str:
    st = src.stat()
    blob = json.dumps([entry["id"], entry["src"], entry.get("start"), entry.get("end"), st.st_size, st.st_mtime_ns,
                       CLIP_SETTINGS_VERSION, CLIP_HEIGHT, CLIP_CRF, CLIP_MAX_CRF, CLIP_TARGET_BYTES, ANIM_WIDTHS, MAX_BYTES])
    return hashlib.sha1(blob.encode()).hexdigest()


def build_clip(entry: dict, src: Path) -> dict:
    """Silent H.264 MP4 at most CLIP_HEIGHT tall (never upscaled), all metadata dropped, plus posters
    from its first frame. Uses the ffmpeg bundled with imageio-ffmpeg, through build_hero.py."""
    import subprocess
    import tempfile

    from build_hero import BT709, FFMPEG, MAX_FPS, TONEMAP, fps_fraction, probe

    info = probe(src)
    upright_h = info["height"] if round(info["rotation"]) % 180 == 0 else info["width"]
    rate = fps_fraction(min(info["fps"], MAX_FPS))
    chain = (TONEMAP if info["hdr"] else []) + [f"fps={rate}", f"scale=-2:{min(CLIP_HEIGHT, upright_h)}:flags=lanczos",
                                                "format=yuv420p"]
    trim = (["-ss", str(entry["start"])] if entry.get("start") else []) + (["-to", str(entry["end"])] if entry.get("end") else [])
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "clip.mp4"
        for crf in range(CLIP_CRF, CLIP_MAX_CRF + 1):  # raise CRF one step at a time towards the soft target
            proc = subprocess.run([FFMPEG, "-hide_banner", "-nostdin", "-y", *trim, "-i", str(src), "-map", "0:v:0", "-an",
                                   "-vf", ",".join(chain), "-c:v", "libx264", "-preset", "slow", "-crf", str(crf),
                                   "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", rate, *BT709,
                                   "-map_metadata", "-1", "-map_metadata:s:v", "-1", "-map_chapters", "-1",
                                   "-fflags", "+bitexact", "-flags:v", "+bitexact", "-movflags", "+faststart", str(out)],
                                  capture_output=True)
            if proc.returncode:
                raise RuntimeError(f"ffmpeg failed on {src.name}:\n" + proc.stderr.decode("utf-8", "replace")[-2000:])
            data = out.read_bytes()
            if len(data) <= CLIP_TARGET_BYTES:
                break
        png = subprocess.run([FFMPEG, "-hide_banner", "-nostdin", "-i", str(out), "-frames:v", "1",
                              "-f", "image2pipe", "-c:v", "png", "-"], capture_output=True).stdout
    frame = Image.open(io.BytesIO(png)).convert("RGB")
    notes = []
    if len(data) > CLIP_TARGET_BYTES:
        notes.append(f"{len(data) / 1e6:.2f} MB at crf {crf}, over the {CLIP_TARGET_BYTES / 1e6:.0f} MB target (kept)")
    posters = []
    for w in [w for w in ANIM_WIDTHS if w <= frame.width] or [frame.width]:
        h = round(frame.height * w / frame.width)
        still = frame if w == frame.width else frame.resize((w, h), Image.LANCZOS, reducing_gap=3.0)
        poster_data, poster_note = encode_to_budget(still, "photo")
        posters.append({"w": w, "h": h, "rel": f"assets/img/{entry['id']}-poster-{w}.webp", "data": poster_data,
                        "frame": 0, "quality": poster_note})
    clip = {"w": frame.width, "h": frame.height, "rel": f"{CLIP_DIR.relative_to(SITE).as_posix()}/{entry['id']}.mp4",
            "data": data, "crf": crf, "seconds": round(clip_seconds(info, entry), 2)}
    return {"clip": clip, "posters": posters, "notes": notes}


def clip_seconds(info: dict, entry: dict) -> float:
    """Length of the cut, from the probe and the optional start/end."""
    end = entry.get("end") or info["duration"]
    return max(0.0, float(end) - float(entry.get("start") or 0))


def write_if_changed(path: Path, data: bytes) -> bool:
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", default=str(SITE.parent), help="media folder (default: the parent of this repo)")
    ap.add_argument("--force", action="store_true", help="re-encode everything")
    args = ap.parse_args()
    source = Path(args.source).resolve()

    media_map = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    state = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() and not args.force else {}
    skipped: list[str] = []
    notes: list[str] = []
    jobs, reuse, order, seen = [], {}, [], set()

    for entry in media_map["images"]:
        eid, rel = entry["id"], entry["src"]
        if not ID_RE.match(eid) or eid in seen:
            skipped.append(f"{eid}: invalid or duplicate id")
            continue
        seen.add(eid)
        if any(b in rel.lower() for b in BLOCKED):
            skipped.append(f"{eid}: blocked source ({rel})")
            continue
        src = exact_file(source, rel)
        if src is None:
            skipped.append(f"{eid}: source not found ({rel})")
            continue
        if SITE == src or SITE in src.parents:
            skipped.append(f"{eid}: source is inside the site repo ({rel})")
            continue
        if src.suffix.lower() in HEIF_EXTS and not HAVE_HEIF:
            skipped.append(f"{eid}: HEIC not converted, pillow-heif is not installed ({rel})")
            continue
        order.append(entry)
        sig = signature(entry, src)
        prev = state.get(eid)
        expected_sig = anim_signature(sig, entry) if prev and prev.get("animated") else sig
        outputs = (prev or {}).get("variants", []) + (prev or {}).get("posters", [])
        job = {"id": eid, "src_path": str(src), "kind": entry.get("kind", "photo"), "sig": sig,
               "poster_frame": entry.get("poster_frame"), "large": wants_large(entry)}
        if prev and prev["sig"] == expected_sig and all((SITE / v["rel"]).is_file() for v in outputs):
            reuse[eid] = prev
            if prev.get("animated"):
                continue
            # The expanded-view still is tracked on its own: a missing or outdated one is rebuilt alone,
            # and one that is no longer wanted is dropped.
            if not job["large"]:
                reuse[eid] = {k: v for k, v in prev.items() if k not in ("large", "large_sig")}
            elif prev.get("large_sig") != large_signature(sig) or (
                    prev.get("large") and not (SITE / prev["large"]["rel"]).is_file()):
                jobs.append(dict(job, only_large=True))
        else:
            jobs.append(job)

    written, written_bytes = 0, 0

    def save(outputs: list[dict]) -> list[dict]:
        nonlocal written, written_bytes
        kept = []
        for v in outputs:
            if write_if_changed(SITE / v["rel"], v["data"]):
                written += 1
                written_bytes += len(v["data"])
            rec = {"w": v["w"], "h": v["h"], "rel": v["rel"], "bytes": len(v["data"])}
            rec.update({k: v[k] for k in ("frames", "quality", "adjusted", "frame", "crf", "seconds") if k in v})
            kept.append(rec)
        return kept

    if jobs:
        sigs = {j["id"]: j["sig"] for j in jobs}
        entries = {e["id"]: e for e in order}

        def with_large(rec: dict, res: dict) -> dict:
            rec = {k: v for k, v in rec.items() if k not in ("large", "large_sig")}
            if wants_large(entries[res["id"]]):
                rec["large_sig"] = large_signature(sigs[res["id"]])
                if res.get("large"):
                    rec["large"] = save([res["large"]])[0]
            return rec

        with ProcessPoolExecutor() as pool:
            for res in pool.map(build_one, jobs):
                notes += [f"{res['id']}: {n}" for n in res["notes"]]
                if res.get("only_large"):
                    reuse[res["id"]] = with_large(reuse[res["id"]], res)
                    continue
                variants = save(res["variants"])
                if res.get("animated"):
                    reuse[res["id"]] = {"sig": anim_signature(sigs[res["id"]], entries[res["id"]]), "animated": True,
                                        "variants": variants, "posters": save(res["posters"])}
                elif variants:
                    reuse[res["id"]] = with_large({"sig": sigs[res["id"]], "variants": variants}, res)
                else:
                    skipped.append(f"{res['id']}: no variant fits the budget")

    manifest, new_state, expected = {}, {}, set()
    for entry in order:
        rec = reuse.get(entry["id"])
        if not rec:
            continue
        new_state[entry["id"]] = rec
        variants = rec["variants"]
        expected.update(v["rel"] for v in variants + rec.get("posters", []) + ([rec["large"]] if rec.get("large") else []))
        best = srcset_of(variants)
        manifest[entry["id"]] = {
            "src": best["default"]["rel"],
            "srcset": best["srcset"],
            "width": best["default"]["w"],
            "height": best["default"]["h"],
            "alt": entry["alt"],
        }
        if entry.get("credit"):  # pages print it with the image wherever it is used
            manifest[entry["id"]]["credit"] = entry["credit"]
        if rec.get("large"):  # loaded by the expanded view only
            manifest[entry["id"]]["large"] = {"src": rec["large"]["rel"], "width": rec["large"]["w"],
                                              "height": rec["large"]["h"]}
        if rec.get("animated"):
            poster = srcset_of(rec["posters"])
            manifest[entry["id"]]["animated"] = True
            manifest[entry["id"]]["poster"] = {"src": poster["default"]["rel"], "srcset": poster["srcset"]}

    expected_clips = set()
    for entry in media_map.get("videos", []):
        eid, rel = entry["id"], entry["src"]
        if not ID_RE.match(eid) or eid in seen:
            skipped.append(f"{eid}: invalid or duplicate id")
            continue
        seen.add(eid)
        src = exact_file(source, rel)
        if src is None:
            skipped.append(f"{eid}: source not found ({rel})")
            continue
        sig = clip_signature(entry, src)
        rec = state.get(eid)
        if not (rec and rec.get("clip") and rec["sig"] == sig
                and all((SITE / v["rel"]).is_file() for v in [rec["clip"]] + rec["posters"])):
            res = build_clip(entry, src)
            notes += [f"{eid}: {n}" for n in res["notes"]]
            rec = {"sig": sig, "variants": [], "clip": save([res["clip"]])[0], "posters": save(res["posters"])}
        new_state[eid] = rec
        expected_clips.add(rec["clip"]["rel"])
        expected.update(p["rel"] for p in rec["posters"])
        poster = srcset_of(rec["posters"])
        manifest[eid] = {"src": rec["clip"]["rel"], "type": "video/mp4", "width": rec["clip"]["w"],
                         "height": rec["clip"]["h"], "alt": entry["alt"], "video": True,
                         "poster": {"src": poster["default"]["rel"], "srcset": poster["srcset"]}}
        if entry.get("credit"):
            manifest[eid]["credit"] = entry["credit"]

    pruned = []
    if CLIP_DIR.exists():
        for p in sorted(CLIP_DIR.rglob("*.mp4")):
            if p.relative_to(SITE).as_posix() not in expected_clips:
                p.unlink()
                pruned.append(p.relative_to(SITE).as_posix())
        for d in sorted((d for d in CLIP_DIR.rglob("*") if d.is_dir()), reverse=True):
            if not any(d.iterdir()):
                d.rmdir()
    if IMG_DIR.exists():
        for p in sorted(IMG_DIR.rglob("*.webp")):
            if p.relative_to(SITE).as_posix() not in expected:
                p.unlink()
                pruned.append(p.relative_to(SITE).as_posix())
        for d in sorted((d for d in IMG_DIR.rglob("*") if d.is_dir()), reverse=True):
            if not any(d.iterdir()):
                d.rmdir()

    copied = 0
    for f in media_map.get("files", []):
        src = exact_file(source, f["src"])
        if src is None:
            skipped.append(f"{f['out']}: source not found ({f['src']})")
            continue
        if write_if_changed(SITE / f["out"], src.read_bytes()):
            copied += 1

    def dump(obj) -> bytes:
        return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    manifest_changed = write_if_changed(MANIFEST_PATH, dump(manifest))
    write_if_changed(STATE_PATH, dump(new_state))

    outputs = [v for rec in new_state.values()
               for v in rec["variants"] + rec.get("posters", []) + [rec[k] for k in ("clip", "large") if rec.get(k)]]
    total, count = sum(v["bytes"] for v in outputs), len(outputs)
    print(f"images mapped: {len(media_map['images'])}   imported: {len(manifest)}   files: {count} ({total / 1e6:.1f} MB)")
    print(f"written this run: {written} files ({written_bytes / 1e6:.1f} MB)   unchanged: {count - written}"
          f"   files copied: {copied}   manifest {'updated' if manifest_changed else 'unchanged'}")
    animations = [(eid, rec) for eid, rec in new_state.items() if rec.get("animated")]
    if animations:
        print(f"animations imported: {len(animations)}")
        for eid, rec in animations:
            for v, p in zip(rec["variants"], rec["posters"]):
                print(f"  {v['rel']}: {v['w']}x{v['h']}, {v['frames']} frames ({v.get('adjusted', 0)} with the corner"
                      f" pixel moved to stay separate), q{v['quality']}, {v['bytes'] / 1e6:.2f} MB"
                      f"   poster (frame {p['frame']}, {p['quality']}): {p['bytes'] / 1e3:.0f} KB")
    larges = [rec["large"] for rec in new_state.values() if rec.get("large")]
    if larges:
        print(f"expanded-view stills ({LARGE_WIDTH} px): {len(larges)}, {sum(v['bytes'] for v in larges) / 1e6:.1f} MB,"
              f" largest {max(v['bytes'] for v in larges) / 1e6:.2f} MB")
    clips = [rec["clip"] for rec in new_state.values() if rec.get("clip")]
    if clips:
        print(f"clips imported: {len(clips)}")
        for c in clips:
            print(f"  {c['rel']}: {c['w']}x{c['h']}, {c['seconds']} s, crf {c['crf']}, {c['bytes'] / 1e6:.2f} MB")
    for label, items in (("note", notes), ("pruned", pruned), ("SKIPPED", skipped)):
        for item in items:
            print(f"  {label}: {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
