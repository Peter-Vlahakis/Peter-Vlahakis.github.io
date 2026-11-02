#!/usr/bin/env python3
"""Checks to run before every commit and before publishing.

    python tools/check_site.py          exits 0 when the site is clean, 1 on any error

Errors (exit 1):
  * a local href / src / srcset / url() / fetched path that does not exist with exact letter case
    (GitHub Pages is case-sensitive; Windows is not);
  * a root-absolute or drive-letter path, or a reference that leaves this folder;
  * a URL to another host, except the LinkedIn link, the mailto link, the photographer credit link,
    the Longhorn Baja Racing site, and the site's own live URL inside <meta> and <link rel="canonical">;
  * a color literal in CSS, HTML or JS outside css/tokens.css (favicon.svg is exempt);
  * invalid JSON, a manifest entry whose file is missing, an image id that is not in the manifest;
  * an <img> without alt, width or height;
  * a competition photo by George Lawrence without his credit, an animation or video without a poster,
    or a data/*.json media id that is missing from the manifest or of the wrong type;
  * a file over a size budget or hard cap (images 600 KB; expanded-view stills 2 MB; the hero
    clips and poster each have their own, in HERO);
  * any path containing "YashSS", any source .mov, or the private commit email anywhere.

Warnings (never fail the run): every TBD spec, every draft text, every pending item,
and every animation, clip, or expanded-view still over its soft size target.
Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

SITE = Path(__file__).resolve().parent.parent
LIVE = "https://petervlahakis.com/"
MAILTO = "mailto:pvlahakis@utexas.edu"
LINKEDIN = "https://www.linkedin.com/in/peter-vlahakis-40aa31334"
LBR_SITE = "https://longhornbajaracing.com/"  # the team website, linked from the Baja SAE page
PHOTO_CREDIT = "@glawrence_photography"  # owner decision 2026-10-27: the handle only
MEDIA_KEYS = ("image", "opening", "headshot", "gallery", "images", "photos", "video")  # data values that are media ids
# The private git identity, stored only as a SHA-256 hash so this public file does not reveal it.
PRIVATE_EMAIL_SHA256 = "ee1bbeefd865168b4d5ea0f730659f1d96d698afd97563fe6d0e31694dffa967"
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
IGNORED = {".git", ".venv", ".claude", "__pycache__", "INSTRUCTIONS.md"}  # not part of the repo
SPEC_ROLE = "Design + CAM + Fabrication"
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")  # project ids are page addresses (?project=<id>)
# Retired page addresses (renamed 2026-10-27 and 2026-10-29); image ids keep their original names.
OLD_PROJECT_IDS = ("bed-delete-bracket", "longhorn-coaster", "ox-plaque", "gas-adapter", "aluminum-coaster-set")

KB, MB = 1000, 1000 * 1000
BUDGET_IMAGE = 600 * KB
# Soft target for files that data/manifest.json marks "animated": true: a warning, not an error.
# They still fall under the 25 MB per-file limit; their posters are images and stay at 600 KB.
TARGET_ANIMATION = 1500 * KB
TARGET_CLIP = 5 * MB  # soft target for clips in assets/video/clips/ (warning only)
# Expanded-view stills (a manifest entry's "large", 2560 px wide): their own target and hard cap.
TARGET_LARGE, CAP_LARGE = 1200 * KB, 2 * MB
BUDGET_FILE = 25 * MB
BUDGET_REPO = 150 * MB
BUDGET_CODE = 150 * KB
BUDGET_HOME = 1 * MB
HERO = {  # file: (target, hard cap). Made by tools/build_hero.py.
    "assets/video/hero-1080.mp4": (8 * MB, 12 * MB),
    "assets/video/hero-720.mp4": (4 * MB, 6 * MB),
    "assets/video/hero-poster.webp": (200 * KB, 300 * KB),
}

URL_ATTRS = {"href", "src", "poster", "data", "action", "data-src", "data-src-large", "data-src-small"}
PATH_EXT = r"(?:html|css|js|json|webp|jpg|jpeg|png|svg|mp4|pdf|woff2|glb|txt|md)"
PATH_RE = re.compile(rf"^[A-Za-z0-9_./-]+\.{PATH_EXT}(?:[?#].*)?$")
HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![0-9A-Za-z_-])")
COLOR_FN_RE = re.compile(r"\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(", re.I)
IDENT_RE = re.compile(r"[A-Za-z_-][A-Za-z0-9_-]*")
NAMED_COLORS = set("""
aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown burlywood
cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod darkgray
darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen
darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue
firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew
hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan
lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray
lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine mediumblue
mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred
midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid
palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple
rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue
slateblue slategray slategrey snow springgreen steelblue tan teal thistle tomato transparent turquoise violet wheat
white whitesmoke yellow yellowgreen
""".split())

errors: list[str] = []
warnings: list[str] = []


def err(where: str, message: str) -> None:
    errors.append(f"{where}: {message}")


def rel(path: Path) -> str:
    return path.relative_to(SITE).as_posix()


def repo_files() -> list[Path]:
    out = []
    for p in SITE.rglob("*"):
        if p.is_file() and not any(part in IGNORED for part in p.relative_to(SITE).parts):
            out.append(p)
    return sorted(out)


def exact_file(posix_path: str) -> bool:
    """True if the site-relative path exists with exactly this letter case."""
    cur = SITE
    for part in PurePosixPath(posix_path).parts:
        if not cur.is_dir() or part not in {p.name for p in cur.iterdir()}:
            return False
        cur = cur / part
    return cur.is_file()


def check_url(where: str, url: str, base_dir: str, *, in_meta: bool = False, external_ok: bool = False) -> None:
    """Validate one URL found in a site file. base_dir is site-relative ('' for the root)."""
    url = url.strip()
    if not url or url.startswith("#") or url.startswith("data:"):
        return
    if url.lower().startswith("mailto:"):
        if url != MAILTO:
            err(where, f"unexpected mailto link {url!r}")
        return
    if re.match(r"^[A-Za-z]:[\\/]", url) or url.startswith("\\"):
        err(where, f"drive-letter or backslash path {url!r}")
        return
    parts = urlsplit(url)
    if parts.scheme or url.startswith("//"):
        if url == LINKEDIN or external_ok:
            return
        if in_meta and url.startswith(LIVE):
            target = unquote(urlsplit(url).path).lstrip("/") or "index.html"
            if not exact_file(target):
                err(where, f"live URL points at a missing file: {url}")
            return
        err(where, f"URL to another host: {url}")
        return
    if url.startswith("/"):
        err(where, f"root-absolute path {url!r} (use a relative path)")
        return
    path = unquote(parts.path)
    joined = PurePosixPath(base_dir, path) if path else None
    if joined is None:
        return
    resolved: list[str] = []
    for part in joined.parts:
        if part == "..":
            if not resolved:
                err(where, f"reference leaves the site folder: {url!r}")
                return
            resolved.pop()
        elif part != ".":
            resolved.append(part)
    target = "/".join(resolved)
    if not exact_file(target):
        err(where, f"missing file (check spelling and letter case): {url!r}")
        return
    if parts.fragment and target.endswith(".html") and parts.fragment not in html_ids(target):
        err(where, f"no element with id {parts.fragment!r} in {target}")


_ids_cache: dict[str, set[str]] = {}


def html_ids(target: str) -> set[str]:
    if target not in _ids_cache:
        text = (SITE / target).read_text(encoding="utf-8")
        _ids_cache[target] = set(re.findall(r'\bid="([^"]+)"', text))
    return _ids_cache[target]


def strip_css_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", lambda m: " " * len(m.group()), text, flags=re.S)


def color_literals_css(text: str) -> list[str]:
    """Color literals in CSS text: hex, color functions, named colors used as values."""
    text = strip_css_comments(text)
    text = re.sub(r"url\([^)]*\)", "url()", text)
    text = re.sub(r"\"[^\"]*\"|'[^']*'", '""', text)
    found = HEX_RE.findall(text) + [m.group().rstrip("(") + "()" for m in COLOR_FN_RE.finditer(text)]
    for decl in re.finditer(r":([^;{}]+)[;}]", text):  # values only, never selectors or property names
        for ident in IDENT_RE.findall(decl.group(1)):
            if ident.lower() in NAMED_COLORS:
                found.append(ident)
    return found


def split_js(text: str) -> tuple[str, list[str]]:
    """Return (code with comments and strings blanked, list of string literal contents)."""
    out, strings, i, n = [], [], 0, len(text)
    while i < n:
        ch, nxt = text[i], text[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif ch == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif ch in "\"'`":
            j = i + 1
            while j < n and text[j] != ch:
                j += 2 if text[j] == "\\" else 1
            strings.append(text[i + 1:j])
            out.append('""')
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out), strings


def check_js(where: str, text: str, base_dir: str = "") -> None:
    code, strings = split_js(text)
    for s in strings:
        if HEX_RE.fullmatch(s.strip()) or COLOR_FN_RE.match(s.strip()) or s.strip().lower() in NAMED_COLORS:
            err(where, f"color literal {s!r} (colors belong in css/tokens.css)")
        if re.match(r"^(?:https?:)?//", s.strip()):
            err(where, f"URL to another host: {s!r}")
        elif s.startswith("/") and PATH_RE.match(s[1:]):
            err(where, f"root-absolute path {s!r}")
        elif PATH_RE.match(s):
            check_url(where, s, base_dir)
    for m in COLOR_FN_RE.finditer(code):
        err(where, f"color function {m.group()}...) (colors belong in css/tokens.css)")


class PageParser(HTMLParser):
    def __init__(self, name: str) -> None:
        super().__init__(convert_charrefs=True)
        self.name = name
        self.lang = None
        self.title = ""
        self.description = None
        self.has_skip = self.has_favicon = self.has_og = False
        self._in: str | None = None
        self._buf: list[str] = []
        self.inline_scripts: list[str] = []
        self.inline_styles: list[str] = []

    def handle_starttag(self, tag: str, attrs_list: list) -> None:
        attrs = {k: (v or "") for k, v in attrs_list}
        where = f"{self.name} <{tag}>"
        if tag == "html":
            self.lang = attrs.get("lang")
        if tag == "meta":
            if attrs.get("name") == "description":
                self.description = attrs.get("content", "")
            if attrs.get("name") == "theme-color":
                err(where, "theme-color is set from the --bg token by js/nav.js; remove the literal")
            if attrs.get("property", "").startswith("og:"):
                self.has_og = True
                if attrs["property"] in ("og:image", "og:url"):
                    check_url(where, attrs.get("content", ""), "", in_meta=True)
        if tag == "link":
            rels = attrs.get("rel", "").split()
            if "icon" in rels:
                self.has_favicon = True
            check_url(where, attrs.get("href", ""), "", in_meta="canonical" in rels)
        elif tag == "a" and "skip-link" in attrs.get("class", ""):
            self.has_skip = True
        if tag != "link":
            for key in URL_ATTRS & attrs.keys():
                check_url(where, attrs[key], "")
        if "srcset" in attrs:
            for candidate in attrs["srcset"].split(","):
                if candidate.strip():
                    check_url(where, candidate.strip().split()[0], "")
        if tag == "img":
            for needed in ("alt", "width", "height"):
                if needed not in attrs:
                    err(where, f"<img> without {needed} ({attrs.get('src', '?')})")
        if "style" in attrs:
            for lit in color_literals_css("x{" + attrs["style"] + "}"):
                err(where, f"color literal {lit!r} in a style attribute")
        for key in ("color", "bgcolor", "fill", "stroke"):
            if key in attrs:
                err(where, f"presentational color attribute {key}={attrs[key]!r}")
        if tag in ("script", "style") and "src" not in attrs:
            self._in, self._buf = tag, []

    def handle_data(self, data: str) -> None:
        if self._in:
            self._buf.append(data)
        elif self.lasttag == "title":
            self.title += data

    def handle_endtag(self, tag: str) -> None:
        if tag == self._in:
            (self.inline_scripts if tag == "script" else self.inline_styles).append("".join(self._buf))
            self._in = None


def check_html(files: list[Path]) -> dict[str, PageParser]:
    pages, titles = {}, {}
    for path in files:
        name = rel(path)
        parser = PageParser(name)
        parser.feed(path.read_text(encoding="utf-8"))
        pages[name] = parser
        title = " ".join(parser.title.split())
        if not parser.lang:
            err(name, "missing lang on <html>")
        if not title:
            err(name, "missing <title>")
        elif title in titles:
            err(name, f"<title> duplicates {titles[title]}")
        titles[title] = name
        if not parser.description:
            err(name, "missing meta description")
        for flag, label in ((parser.has_skip, "skip link"), (parser.has_favicon, "favicon link"), (parser.has_og, "Open Graph tags")):
            if not flag:
                err(name, f"missing {label}")
        for script in parser.inline_scripts:
            check_js(f"{name} inline script", script)
        for style in parser.inline_styles:
            for lit in color_literals_css(style):
                err(f"{name} <style>", f"color literal {lit!r}")
    return pages


def check_css(files: list[Path]) -> None:
    for path in files:
        name = rel(path)
        text = path.read_text(encoding="utf-8")
        base = PurePosixPath(name).parent.as_posix()
        # Inline data: URIs (the grit textures) may contain url(#id) references of their own; skip them whole.
        scan = re.sub(r"url\(\s*([\"'])data:.*?\1\s*\)", "url()", strip_css_comments(text))
        for m in re.finditer(r"url\(\s*([\"']?)([^\"')]+)\1\s*\)", scan):
            check_url(name, m.group(2), "" if base == "." else base)
        if name != "css/tokens.css":
            for lit in color_literals_css(text):
                err(name, f"color literal {lit!r} (colors belong in css/tokens.css)")


def walk(node, path=()):
    """Yield (path, value) for every leaf in parsed JSON, skipping _readme notes."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key != "_readme":
                yield from walk(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, path + (index,))
    else:
        yield path, node


def label(data, path) -> str:
    """Readable location: list positions become [id] where the item has one."""
    parts, node = [], data
    for step in path:
        node = node[step]
        if isinstance(step, int):
            parts.append(f"[{node['id']}]" if isinstance(node, dict) and "id" in node else f"[{step}]")
        else:
            parts.append(("." if parts else "") + str(step))
    return "".join(parts)


def check_data(files: list[Path]) -> None:
    parsed: dict[str, object] = {}
    for path in files:
        try:
            parsed[rel(path)] = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            err(rel(path), f"invalid JSON: {exc}")

    manifest = parsed.get("data/manifest.json")
    if not isinstance(manifest, dict):
        err("data/manifest.json", "missing or not an object (run tools/build_media.py)")
        manifest = {}
    for image_id, entry in manifest.items():
        where = f"data/manifest.json [{image_id}]"
        candidates = [entry.get("src", "")] + [c.strip().split()[0] for c in entry.get("srcset", "").split(",") if c.strip()]
        if entry.get("large"):
            candidates.append(entry["large"].get("src", ""))
        for candidate in candidates:
            if not exact_file(candidate):
                err(where, f"missing file {candidate!r}")
        if not (isinstance(entry.get("width"), int) and isinstance(entry.get("height"), int)):
            err(where, "width and height must be whole numbers")
        if not entry.get("alt"):
            err(where, "empty alt text")
        if (entry.get("animated") or entry.get("video")) and not (entry.get("poster") or {}).get("src"):
            err(where, "animated or video entry without a poster")
        poster = entry.get("poster") or {}
        for candidate in [poster.get("src", "")] + [c.strip().split()[0] for c in poster.get("srcset", "").split(",") if c.strip()]:
            if candidate and not exact_file(candidate):
                err(where, f"missing poster file {candidate!r}")

    # Competition photos by George Lawrence carry his credit wherever they appear. The importer copies a
    # map entry's "credit" into the manifest and the pages print it, so the map is the place to check.
    for entry in (parsed.get("tools/media_map.json") or {}).get("images", []):
        name = PurePosixPath(entry.get("src", "")).name
        if ("glawrence" in entry.get("src", "").lower() or re.match(r"DSC0\d+\.", name)) and PHOTO_CREDIT not in entry.get("credit", ""):
            err(f"tools/media_map.json [{entry.get('id')}]", f"George Lawrence photo without the credit {PHOTO_CREDIT!r}")
        elif entry.get("credit") and manifest.get(entry["id"], {}).get("credit") != entry["credit"]:
            err(f"data/manifest.json [{entry.get('id')}]", "credit missing from the manifest (run tools/build_media.py)")

    for name in ("data/site.json", "data/projects.json", "data/baja.json"):
        data = parsed.get(name)
        if data is None:
            if not (SITE / name).is_file():
                err(name, "missing")
            continue
        model_on = name == "data/baja.json" and data.get("model", {}).get("enabled")
        for path, value in walk(data):
            where = f"{name} {label(data, path)}"
            key = path[-1] if not isinstance(path[-1], int) else path[-2]
            if isinstance(value, str):
                if key in MEDIA_KEYS and value not in manifest:
                    err(where, f"media id {value!r} is not in data/manifest.json")
                if key == "video" and value in manifest and not manifest[value].get("video"):
                    err(where, f"{value!r} is not a video in data/manifest.json")
                if re.match(r"^(?:https?:)?//", value):
                    if not (value in (LINKEDIN, LBR_SITE) or path[-2:] == ("credit", "url")):
                        err(where, f"URL to another host: {value}")
                elif PATH_RE.match(value) and "/" in value and key not in MEDIA_KEYS:
                    if path[0] == "model" and not model_on:
                        continue  # the 3D files are not expected until the viewer is enabled
                    check_url(where, value, "")
                if value == "TBD":
                    warnings.append(f"TBD      {where}")
            if path[-1] == "draft" and value is True:
                parent = data
                for step in path[:-1]:
                    parent = parent[step]
                text = parent.get("text") or " / ".join(parent.get("lines", []))
                warnings.append(f"draft    {name} {label(data, path[:-1])}: {text[:70]}")

    # The Projects page shows only rows that apply: no TBD, and the role once, in the spec table.
    projects = parsed.get("data/projects.json") or {}
    for project in projects.get("projects", []):
        where = f"data/projects.json [{project.get('id')}]"
        specs = project.get("specs", {})
        if specs.get("Role") != SPEC_ROLE:
            err(where, f"the Role row must be {SPEC_ROLE!r}")
        for key, value in specs.items():
            if value == "TBD":
                err(where, f"specs.{key} is TBD; leave the row out instead")
        if not ID_RE.match(project.get("id", "")):
            err(where, "the id is the page address: lowercase letters, digits, and '-' only")

    baja = parsed.get("data/baja.json") or {}
    for group in baja.get("groups", []):
        for section in group.get("sections", []):
            if section.get("model") and not baja.get("model", {}).get("enabled"):
                warnings.append(f"pending  data/baja.json [{section.get('id')}]: interactive 3D chassis model "
                                "(add assets/models/chassis.glb and the model-viewer script, then set model.enabled)")
    if baja.get("model", {}).get("enabled"):
        for key in ("src", "script"):
            if not exact_file(baja["model"].get(key, "")):
                err("data/baja.json model", f"viewer is enabled but {baja['model'].get(key)!r} does not exist")


def animated_files() -> set[str]:
    """Files listed (src or srcset) by manifest entries marked "animated": true. Posters are not included."""
    try:
        manifest = json.loads((SITE / "data" / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()  # reported by check_data
    found = set()
    for entry in manifest.values() if isinstance(manifest, dict) else []:
        if isinstance(entry, dict) and entry.get("animated"):
            found.add(entry.get("src", ""))
            found |= {c.strip().split()[0] for c in entry.get("srcset", "").split(",") if c.strip()}
    return found


def large_files() -> set[str]:
    """Expanded-view stills: the "large" src of each manifest entry."""
    try:
        manifest = json.loads((SITE / "data" / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()  # reported by check_data
    return {e["large"]["src"] for e in manifest.values() if isinstance(e, dict) and isinstance(e.get("large"), dict)}


def check_budgets(files: list[Path], pages: dict[str, PageParser]) -> list[str]:
    sizes = {rel(p): p.stat().st_size for p in files}
    animated = animated_files()
    large = large_files()
    report = []
    total = sum(sizes.values())
    for name, size in sizes.items():
        low = name.lower()
        if "yashss" in low:
            err(name, "YashSS files must never be in the site")
        if low.endswith(".mov"):
            err(name, "source video does not belong in the repo")
        if size > BUDGET_FILE:
            err(name, f"{size / MB:.1f} MB is over the 25 MB per-file limit")
        if name in animated:
            if size > TARGET_ANIMATION:
                warnings.append(f"budget   {name} is {size / MB:.2f} MB, over the {TARGET_ANIMATION / MB:.1f} MB animation target")
        elif name in large:
            if size > CAP_LARGE:
                err(name, f"{size / MB:.2f} MB is over the {CAP_LARGE / MB:.0f} MB expanded-view cap")
            elif size > TARGET_LARGE:
                warnings.append(f"budget   {name} is {size / MB:.2f} MB, over the {TARGET_LARGE / MB:.1f} MB expanded-view target")
        elif name.startswith("assets/img/") and size > BUDGET_IMAGE:
            err(name, f"{size / KB:.0f} KB is over the 600 KB image budget")
    if total > BUDGET_REPO:
        err("repo", f"{total / MB:.1f} MB is over the 150 MB limit")
    for name, (target, cap) in HERO.items():
        size = sizes.get(name)
        if size is None:
            err(name, "missing (run tools/build_hero.py)")
        elif size > cap:
            err(name, f"{size / MB:.2f} MB is over its hard cap of {cap / MB:.1f} MB")
        elif size > target:
            warnings.append(f"budget   {name} is {size / MB:.2f} MB, over its {target / MB:.1f} MB target (under the hard cap)")
    for name, size in sizes.items():
        if name.startswith("assets/video/clips/") and size > TARGET_CLIP:
            warnings.append(f"budget   {name} is {size / MB:.2f} MB, over the {TARGET_CLIP / MB:.0f} MB clip target")
    code = sum(s for n, s in sizes.items() if (n.startswith("css/") and n.endswith(".css")) or (n.startswith("js/") and n.endswith(".js")))
    if code > BUDGET_CODE:
        err("css + js", f"{code / KB:.0f} KB is over the 150 KB budget")

    # Home first load, hero video excluded: the page, what it links, the fonts, the poster, and the JSON it fetches.
    home_text = (SITE / "index.html").read_text(encoding="utf-8") if (SITE / "index.html").is_file() else ""
    home = {"index.html", "favicon.svg", "assets/video/hero-poster.webp", "data/site.json", "data/manifest.json"}
    home |= set(re.findall(r'(?:href|src)="((?:css|js)/[^"]+)"', home_text))
    home |= {n for n in sizes if n.startswith("assets/fonts/") and n.endswith(".woff2")}
    first_load = sum(sizes.get(n, 0) for n in home)
    if first_load > BUDGET_HOME:
        err("home first load", f"{first_load / KB:.0f} KB is over the 1 MB budget")

    images = [s for n, s in sizes.items() if n.startswith("assets/img/") and n not in animated and n not in large]
    larges = [s for n, s in sizes.items() if n in large]
    anims = [s for n, s in sizes.items() if n in animated]
    report.append(f"repo (without .venv/.git): {total / MB:.1f} MB in {len(sizes)} files; largest {max(sizes.values()) / MB:.2f} MB")
    report.append(f"content images: {len(images)} files, {sum(images) / MB:.1f} MB, largest {max(images) / KB:.0f} KB")
    if anims:
        report.append(f"animations: {len(anims)} files, {sum(anims) / MB:.1f} MB, largest {max(anims) / KB:.0f} KB")
    if larges:
        report.append(f"expanded-view stills: {len(larges)} files, {sum(larges) / MB:.1f} MB, largest {max(larges) / KB:.0f} KB")
    report.append("video: " + ", ".join(f"{PurePosixPath(n).name} {sizes.get(n, 0) / MB:.2f} MB" for n in HERO))
    report.append(f"css + js: {code / KB:.1f} KB    home first load (no video): {first_load / KB:.0f} KB")
    return report


def check_private(files: list[Path]) -> None:
    for path in files:
        if path.suffix.lower() in {".html", ".css", ".js", ".json", ".md", ".txt", ".svg", ".py"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            for address in set(EMAIL_RE.findall(text)):
                if hashlib.sha256(address.lower().encode()).hexdigest() == PRIVATE_EMAIL_SHA256:
                    err(rel(path), "contains the private commit email")
            if "yashss" in text.lower() and rel(path) not in ("tools/check_site.py", "tools/build_media.py", "CLAUDE.md", "README.md"):
                err(rel(path), "mentions a YashSS file")
            if path.suffix.lower() in {".html", ".js", ".json"}:
                for old in OLD_PROJECT_IDS:
                    if re.search(rf"project=(?:{old})\b", text) or re.search(rf'"id":\s*"{old}"', text):
                        err(rel(path), f"uses the old project address {old!r}")


def main() -> int:
    files = repo_files()
    pages = check_html([p for p in files if p.suffix == ".html" and p.parent == SITE])
    check_css([p for p in files if p.suffix == ".css"])
    for path in files:
        if path.suffix == ".js":
            check_js(rel(path), path.read_text(encoding="utf-8"))
    check_data([p for p in files if p.suffix == ".json" and rel(p).split("/")[0] in ("data", "tools")])
    report = check_budgets(files, pages)
    check_private(files)

    for line in report:
        print(line)
    print(f"\n{len(warnings)} open items (not errors):")
    for line in sorted(warnings):
        print("  " + line)
    if errors:
        print(f"\n{len(errors)} ERRORS:")
        for line in errors:
            print("  " + line)
        return 1
    print("\ncheck_site: OK")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    sys.exit(main())
