from opencc import OpenCC


_TRADITIONAL_TO_SIMPLIFIED = OpenCC("tw2sp")


def to_simplified(text: str) -> str:
    """Convert Traditional Chinese text to Simplified Chinese."""
    return _TRADITIONAL_TO_SIMPLIFIED.convert(text)
