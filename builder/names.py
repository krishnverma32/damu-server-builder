"""Compatibility helpers for role colours and Unicode name styles."""
import logging
from typing import Any
import discord

log = logging.getLogger(__name__)

_NAMED_COLOURS: dict[str, int] = {
    "red": 0xE74C3C, "dark_red": 0x992D22, "crimson": 0xDC143C,
    "orange": 0xE67E22, "dark_orange": 0xA84300,
    "yellow": 0xF1C40F, "gold": 0xFFD700, "amber": 0xFFBF00,
    "green": 0x2ECC71, "dark_green": 0x1F8B4C, "lime": 0x00FF00, "emerald": 0x50C878,
    "teal": 0x1ABC9C, "dark_teal": 0x11806A, "cyan": 0x00FFFF, "aqua": 0x00FFFF,
    "blue": 0x3498DB, "dark_blue": 0x206694, "navy": 0x000080, "royal_blue": 0x4169E1,
    "purple": 0x9B59B6, "dark_purple": 0x71368A, "violet": 0x8B00FF, "indigo": 0x4B0082,
    "magenta": 0xE91E63, "pink": 0xFFC0CB, "hot_pink": 0xFF69B4, "fuchsia": 0xFF00FF,
    "white": 0xFFFFFF, "light_grey": 0x95A5A6, "grey": 0x7F8C8D, "dark_grey": 0x546E7A,
    "black": 0x010101, "blurple": 0x5865F2, "greyple": 0x99AAB5,
}

_FONT_OFFSETS: dict[str, dict[str, int]] = {
    "bold": {"upper": 0x1D400, "lower": 0x1D41A, "digit": 0x1D7CE},
    "italic": {"upper": 0x1D434, "lower": 0x1D44E},
    "bold_italic": {"upper": 0x1D468, "lower": 0x1D482},
    "script": {"upper": 0x1D49C, "lower": 0x1D4B6},
    "bold_script": {"upper": 0x1D4D0, "lower": 0x1D4EA},
    "fraktur": {"upper": 0x1D504, "lower": 0x1D51E},
    "double_struck": {"upper": 0x1D538, "lower": 0x1D552, "digit": 0x1D7D8},
    "monospace": {"upper": 0x1D670, "lower": 0x1D68A, "digit": 0x1D7F6},
}

_SCRIPT_EXCEPTIONS = {
    "B": "\u212c", "E": "\u2130", "F": "\u2131", "H": "\u210b", "I": "\u2110",
    "L": "\u2112", "M": "\u2133", "R": "\u211b", "e": "\u212f", "g": "\u210a",
    "o": "\u2134",
}
_FRAKTUR_EXCEPTIONS = {
    "C": "\u212d", "H": "\u210c", "I": "\u2111", "R": "\u211c", "Z": "\u2128",
}
_DOUBLE_STRUCK_EXCEPTIONS = {
    "C": "\u2102", "H": "\u210d", "N": "\u2115", "P": "\u2119", "Q": "\u211a",
    "R": "\u211d", "Z": "\u2124",
}
_SMALL_CAPS = str.maketrans({
    "a": "\u1d00", "b": "\u0299", "c": "\u1d04", "d": "\u1d05", "e": "\u1d07",
    "f": "\ua730", "g": "\u0262", "h": "\u029c", "i": "\u026a", "j": "\u1d0a",
    "k": "\u1d0b", "l": "\u029f", "m": "\u1d0d", "n": "\u0274", "o": "\u1d0f",
    "p": "\u1d18", "q": "q", "r": "\u0280", "s": "s", "t": "\u1d1b",
    "u": "\u1d1c", "v": "\u1d20", "w": "\u1d21", "x": "x", "y": "\u028f",
    "z": "\u1d22",
})


def _parse_colour(colour_str: str | None) -> discord.Colour:
    """Parse a colour from hex (#FF0000) or named colour (red, gold, blurple, etc.)."""
    if not colour_str:
        return discord.Colour.default()
    cleaned = colour_str.strip().lower().replace(" ", "_").replace("-", "_")
    # Check named colours first
    if cleaned in _NAMED_COLOURS:
        return discord.Colour(_NAMED_COLOURS[cleaned])
    # Then try hex
    try:
        return discord.Colour(int(cleaned.lstrip("#"), 16))
    except ValueError:
        log.warning("Unknown colour: %s — using default", colour_str)
        return discord.Colour.default()


def _style_text(text: str, style: str | None) -> str:
    """Apply a Unicode text style. Discord does not support installable fonts."""
    if not style:
        return text

    normalized = style.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized == "small_caps":
        return text.lower().translate(_SMALL_CAPS)

    offsets = _FONT_OFFSETS.get(normalized)
    if not offsets:
        return text

    exceptions: dict[str, str] = {}
    if normalized in {"script", "bold_script"}:
        exceptions = _SCRIPT_EXCEPTIONS
    elif normalized == "fraktur":
        exceptions = _FRAKTUR_EXCEPTIONS
    elif normalized == "double_struck":
        exceptions = _DOUBLE_STRUCK_EXCEPTIONS

    styled: list[str] = []
    for char in text:
        if char in exceptions:
            styled.append(exceptions[char])
        elif "A" <= char <= "Z" and "upper" in offsets:
            styled.append(chr(offsets["upper"] + ord(char) - ord("A")))
        elif "a" <= char <= "z" and "lower" in offsets:
            styled.append(chr(offsets["lower"] + ord(char) - ord("a")))
        elif "0" <= char <= "9" and "digit" in offsets:
            styled.append(chr(offsets["digit"] + ord(char) - ord("0")))
        else:
            styled.append(char)

    return "".join(styled)


def _styled_name(data: dict[str, Any], fallback_style: str | None = None) -> str:
    style = data.get("font") or data.get("name_font") or data.get("name_style") or fallback_style
    return _style_text(data["name"], style)


