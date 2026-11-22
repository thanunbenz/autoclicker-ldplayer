"""Application name and version."""

__version__ = "1.0.13"

APP_NAME = "LDPlayer Auto Clicker"
AUTHOR = "thanunbenz"

def as_tuple(text: str = "") -> tuple:
    parts = (text or __version__).strip().split(".")[:3]
    out = []
    for p in parts:
        digits = ""
        for c in p.strip().lstrip("vV"):
            if not c.isdigit():
                break
            digits += c
        out.append(int(digits) if digits else 0)
    return tuple(out + [0] * (3 - len(out)))

def is_newer(other: str) -> bool:
    return as_tuple(other) > as_tuple(__version__)

def title(suffix: str = "") -> str:
    bits = [APP_NAME, __version__]
    if suffix:
        bits.append(suffix)
    return " ".join(bits) + f" by {AUTHOR}"
