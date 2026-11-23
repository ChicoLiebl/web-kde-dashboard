"""The kind of work a Claude session does (firmware, pcb, software, cad) and the kitty background
that goes with it. Used by kddash for the crabs' hats and for tinting kitty tabs."""
import json
import os
import re
import subprocess
from pathlib import Path

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kddash"


# The kind of work a session does (its crab's hat and tools on the dashboard): from its folder's
# path, else from files in the folder, else from the session's name. ~/.config/kddash/kinds.json,
# {"/path/prefix": "pcb", ...}, overrides all of that.
KINDS = ("firmware", "pcb", "software", "cad")
KIND_SEGMENTS = [
    (re.compile(r"^(\d+-)?(firmwares?|fw)([-_].*)?$"), "firmware"),
    (re.compile(r"^(\d+-)?(hardware|pcbs?|kicad|electronics)([-_].*)?$"), "pcb"),
    (re.compile(r"^(\d+-)?(mechanical|mechanics|cad|3d-print(ing|s)?|enclosures?)([-_].*)?$"), "cad"),
    (re.compile(r"^(\d+-)?(software|apps?|web)$"), "software"),
]
KIND_FILES = [
    (re.compile(r".*\.kicad_(pro|pcb|sch)$"), "pcb"),
    (re.compile(r"^(sdkconfig.*|platformio\.ini|idf_component\.yml)$"), "firmware"),
    (re.compile(r".*\.(fcstd|step|stp|scad|3mf|stl|f3d)$"), "cad"),
]
KIND_NAMES = [(re.compile(r"^(fw|firmware)[-_]"), "firmware"), (re.compile(r"^(pcb|hw)[-_]"), "pcb"),
              (re.compile(r"^(cad|mech)[-_]"), "cad")]
_kinds: dict[tuple, str] = {}


def kind_overrides():
    try:
        data = json.loads((CONFIG / "kinds.json").read_text())
        return {str(Path(k).expanduser()): v for k, v in data.items() if v in KINDS}
    except (OSError, ValueError, AttributeError):
        return {}


def session_kind(cwd, name=""):
    key = (cwd, name)
    if key in _kinds:
        return _kinds[key]
    kind = None
    for prefix, k in sorted(kind_overrides().items(), key=lambda kv: -len(kv[0])):
        if cwd == prefix or cwd.startswith(prefix.rstrip("/") + "/"):
            kind = k
            break
    # The deepest folder that says what it is wins (…/03-software/pcb-tool is a pcb tool).
    for part in reversed(Path(cwd).parts if not kind else ()):
        kind = next((k for rx, k in KIND_SEGMENTS if rx.match(part.lower())), None)
        if kind:
            break
    if not kind:
        try:
            files = [e.name.lower() for e in os.scandir(cwd)]
        except OSError:
            files = []
        kind = next((k for rx, k in KIND_FILES if any(rx.match(f) for f in files)), None)
        if not kind and "cmakelists.txt" in files and "main" in files:  # an ESP-IDF project
            kind = "firmware"
    if not kind:
        kind = next((k for rx, k in KIND_NAMES if rx.match((name or "").lower())), "software")
    _kinds[key] = kind
    return kind


# Kitty background per kind: a pattern drawn in the kind's colour on the theme's own background
# (patterns.py), set as the kitty window's background image. Colours for dark and light themes;
# ~/.config/kddash/backgrounds.json overrides them ({"pcb": "#5a4070", "pcb-light": "#e0cce9"}, a kind
# set to null gets no pattern) and turns the patterns off with {"enabled": false}.
BACKGROUNDS_FILE = CONFIG / "backgrounds.json"
PATTERN = {"pcb": "pin-grid", "firmware": "hex-dump", "software": "icon-graph", "cad": "iso-blocks"}
BACKGROUNDS = {
    "pcb": "#4a3560", "pcb-light": "#d9c3e6",
    "firmware": "#2f5a3c", "firmware-light": "#bfdcc4",
    "software": "#33476b", "software-light": "#c2d1ec",
    "cad": "#5c4a22", "cad-light": "#e8d39a",
}
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "kddash" / "patterns"


def background_settings():
    try:
        data = json.loads(BACKGROUNDS_FILE.read_text())
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    colors = dict(BACKGROUNDS)
    for k, v in data.items():
        if k in colors and (v is None or (isinstance(v, str) and COLOR.match(v))):
            colors[k] = v
    return {"enabled": data.get("enabled", True) is not False, "colors": colors, "patterns": PATTERN}


def set_backgrounds_enabled(on):
    try:
        data = json.loads(BACKGROUNDS_FILE.read_text())
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data["enabled"] = bool(on)
    BACKGROUNDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = BACKGROUNDS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(BACKGROUNDS_FILE)


def is_light(color):
    """True for a light background colour like #faf3d9 (relative luminance above one half)."""
    try:
        r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    except (TypeError, ValueError, IndexError):
        return False
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.5


def background(kind, light=False, colors=None):
    colors = colors or background_settings()["colors"]
    return colors.get(f"{kind}-light" if light else kind)


def pattern_image(kind, base, colors):
    """PNG tile for a kind on a kitty whose background is `base`, rendered once into the cache
    (again when patterns.py changes). None when the kind has no colour or rsvg-convert is missing."""
    import patterns  # only needed here; it imports nothing heavy
    light = is_light(base)
    color = background(kind, light, colors)
    name = PATTERN.get(kind)
    if not color or not name or not COLOR.match(base):
        return None
    png = CACHE / f"{name}-{color[1:]}-on-{base[1:]}.png"
    src = Path(patterns.__file__)
    if png.exists() and png.stat().st_mtime >= src.stat().st_mtime:
        return png
    CACHE.mkdir(parents=True, exist_ok=True)
    svg = png.with_suffix(".svg")
    svg.write_text(patterns.DRAW[name](color, base, light))
    tmp = png.with_suffix(".tmp.png")
    subprocess.run(["rsvg-convert", "-o", str(tmp), str(svg)], check=True, capture_output=True, timeout=60)
    tmp.replace(png)
    svg.unlink()
    return png
