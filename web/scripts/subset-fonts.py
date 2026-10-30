# /// script
# requires-python = ">=3.12"
# dependencies = ["fonttools[woff]==4.60.1"]
# ///
"""Subset the landing page fonts to what the built site renders.

Run from web/ after `pnpm build`:  uv run scripts/subset-fonts.py

Writes src/fonts/. Rerun it and commit the output whenever pages, components
or styles add characters or turn on OpenType features, and whenever FACES or
the pinned sources change.
"""

from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import unicodedata
import urllib.request

from fontTools import subset  # ty: ignore[unresolved-import] - PEP 723 script dependency
from fontTools.ttLib import TTFont  # ty: ignore[unresolved-import]

WEB = Path(__file__).resolve().parent.parent
OUT = WEB / "src" / "fonts"
UPSTREAM = "https://raw.githubusercontent.com/google/fonts/6157dfaa640ca5738b4d1a7070fe389c3036d7fc/ofl/"
ASCII = set(range(0x20, 0x7F))
LATIN_1_AND_EXTENDED_A = set(range(0xA0, 0x180))
TYPOGRAPHY = {0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2026}
# Default-on features that the replaced fontsource files contained; no style enables more.
SANS_FEATURES = ("ccmp", "kern", "liga", "locl", "mark", "mkmk", "rvrn")
MONO_FEATURES = ("ccmp", "mark")
LICENSES = {
    "montserrat/OFL.txt": "8b7141c03fa4f8d44e6345d5d4931709290f0f67875e452e95ac1fd3a027802e",
    "ibmplexmono/OFL.txt": "7e6b2818edbd8f6a01ae80641cc8f16a51080d08fb4e532be3a0b6f74adb07da",
}


@dataclass(frozen=True)
class Face:
    family: str
    weight: str
    stem: str
    source: str
    sha256: str
    fontsource_css: str
    features: tuple[str, ...]
    rename: tuple[str, str] | None = None


FACES = [
    Face(
        "Montserrat Variable",
        "100 900",
        "sans",
        "montserrat/Montserrat%5Bwght%5D.ttf",
        "0f7b311b2f3279e4eef9b2f968bcdbab6e28f4daeb1f049f4f278a902bcd82f7",
        "@fontsource-variable/montserrat/index.css",
        SANS_FEATURES,
    ),
    *(
        Face(
            "IBM Plex Mono",
            str(weight),
            f"mono-{weight}",
            f"ibmplexmono/IBMPlexMono-{style}.ttf",
            sha256,
            f"@fontsource/ibm-plex-mono/{weight}.css",
            MONO_FEATURES,
            # OFL Reserved Font Name "Plex": modified versions must not use it.
            ("IBM Plex Mono", "Agent Dump Mono"),
        )
        for weight, style, sha256 in [
            (300, "Light", "780bcf65509d72a35ec114b57bcbe220dc6b77d8ea2e9b25e294be3c570c5025"),
            (400, "Regular", "6a3412f058c7d8dfd9170c41e85ade48e5156ecb89356110ca57a0a27734af46"),
            (500, "Medium", "a9b4c49bb299e05b5f6c481e7fb5e78943d2793249a0c8874ab574a2d1ea6755"),
            (600, "SemiBold", "d3c38e55c78f5b0f28009fddba4834ec503278936a5986032424c9bd2d23aa46"),
        ]
    ),
]


def download(path: str, sha256: str) -> bytes:
    with urllib.request.urlopen(UPSTREAM + path) as response:  # noqa: S310 - fixed HTTPS google/fonts origin
        data = response.read()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise SystemExit(f"{path}: SHA-256 mismatch")
    return data


def parse_ranges(value: str) -> set[int]:
    chars: set[int] = set()
    for part in value.split(","):
        start, _, end = part.strip().removeprefix("U+").partition("-")
        chars.update(range(int(start, 16), int(end or start, 16) + 1))
    return chars


def format_ranges(chars: set[int]) -> str:
    runs: list[list[int]] = []
    for char in sorted(chars):
        if runs and runs[-1][1] == char - 1:
            runs[-1][1] = char
        else:
            runs.append([char, char])
    return ",".join(f"U+{start:X}" if start == end else f"U+{start:X}-{end:X}" for start, end in runs)


def previously_served(face: Face) -> set[int]:
    """Characters the fontsource faces this replaces rendered, so fallback stays put."""
    css = WEB / "node_modules" / face.fontsource_css
    chars: set[int] = set()
    for block in re.findall(r"@font-face\s*{([^}]*)}", css.read_text()):
        file = re.search(r"url\(\./([^)]+\.woff2)\)", block)
        ranges = re.search(r"unicode-range:\s*([^;]+);", block)
        if not file or not ranges:
            raise SystemExit(f"{css}: unexpected @font-face")
        cmap = TTFont(css.parent / file[1]).getBestCmap()
        chars |= parse_ranges(ranges[1]) & cmap.keys()
    return chars


def build(face: Face, source: bytes, chars: set[int]) -> TTFont:
    # A tighter recalculated head bbox clips small glyphs in Chrome on macOS.
    font = TTFont(io.BytesIO(source), recalcTimestamp=False, recalcBBoxes=False)
    options = subset.Options()
    options.layout_features = list(face.features)
    options.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14]
    options.drop_tables += ["meta"]
    # Otherwise "›" silently pulls "‹" into cmap; the site has no RTL text to mirror.
    options.bidi_closure = False
    # A format 3 post table changes how Chrome on macOS rasterizes small text.
    options.glyph_names = True
    subsetter = subset.Subsetter(options)
    # Chrome on macOS rasterizes differently depending on the glyph set; without "X",
    # Latin-1 no longer matches the fontsource latin files pixel for pixel.
    subsetter.populate(unicodes=chars | {ord("X")})
    subsetter.subset(font)
    if ord("X") not in chars:
        for table in font["cmap"].tables:
            table.cmap.pop(ord("X"), None)
        font["OS/2"].updateFirstAndLastCharIndex(font)
    if face.rename:
        old, new = face.rename
        for record in font["name"].names:
            text = record.toUnicode()
            text = text.replace(old, new)
            text = text.replace(old.replace(" ", ""), new.replace(" ", ""))
            record.string = text
    font.flavor = "woff2"
    return font


def check(face: Face, font: TTFont, chars: set[int]) -> None:
    if set(font.getBestCmap()) != chars:
        raise SystemExit(f"{face.stem}: cmap differs")
    tags = {
        record.FeatureTag
        for table in ("GSUB", "GPOS")
        if table in font
        for record in font[table].table.FeatureList.FeatureRecord
    }
    if not tags <= set(face.features):
        raise SystemExit(f"{face.stem}: unexpected features {tags}")
    if face.rename:
        names = " ".join(record.toUnicode() for record in font["name"].names)
        if "Plex" in names:
            raise SystemExit(f"{face.stem}: reserved name left")


def css_rule(face: Face, font: TTFont, file: str, chars: set[int]) -> str:
    font_format = "woff2-variations" if "fvar" in font else "woff2"
    return f"""@font-face {{
  font-family: "{face.family}";
  font-style: normal;
  font-display: swap;
  font-weight: {face.weight};
  src: url("./{file}") format("{font_format}");
  unicode-range: {format_ranges(chars)};
}}
"""


def main() -> None:
    usage = json.loads(
        subprocess.run(  # noqa: S603
            ["node", "scripts/font-usage.mjs"],  # noqa: S607
            cwd=WEB,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    for family, entry in usage["families"].items():
        if entry["features"]:
            raise SystemExit(f"{family}: map {entry['features']} to OpenType tags")

    sources = {face: download(face.source, face.sha256) for face in FACES}
    licenses = {path.split("/")[0]: download(path, sha256) for path, sha256 in LICENSES.items()}
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.woff2"):
        old.unlink()
    rules = []
    rows = []
    for face in FACES:
        entry = usage["families"][face.family]
        used = {ord(char) for char in entry["chars"] + usage["scriptChars"]}
        symbols = {char for char in used if unicodedata.category(chr(char))[0] not in ("L", "C")}
        served = previously_served(face)
        core = served & (ASCII | TYPOGRAPHY | symbols)
        extension = served & (LATIN_1_AND_EXTENDED_A | used) - core
        for part, chars in (("core", core), ("ext", extension)):
            font = build(face, sources[face], chars)
            check(face, font, chars)
            file = f"{face.stem}-{part}.woff2"
            font.save(OUT / file)
            rules.append(css_rule(face, font, file, chars))
            rows.append(f"{file:20} {len(chars):4} chars {(OUT / file).stat().st_size:7} B")

    for name, text in licenses.items():
        (OUT / f"OFL-{name}.txt").write_bytes(text)
    (OUT / "fonts.css").write_text(
        "/* Generated by scripts/subset-fonts.py from dist/. Do not edit. */\n" + "\n".join(rules)
    )
    print("\n".join(rows))


if __name__ == "__main__":
    main()
