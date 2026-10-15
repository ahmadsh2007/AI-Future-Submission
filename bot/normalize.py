"""Arabic text normalization helpers used by deterministic routing."""

import unicodedata


_CHAR_MAP = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ة": "ه",
        "ؤ": "و",
        "ئ": "ي",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
    }
)


def normalize(text):
    """Return a stable, comparison-friendly representation of *text*.

    Diacritics and tatweel are removed, common Arabic letter variants and
    digits are unified, Latin text is lower-cased, and punctuation/symbols are
    converted to spaces. The function is deliberately lossier than display
    normalization because its output is only used for matching.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)

    text = unicodedata.normalize("NFKD", text).translate(_CHAR_MAP).lower()
    output = []
    for char in text:
        if char == "ـ" or unicodedata.category(char).startswith("M"):
            continue
        category = unicodedata.category(char)
        if category.startswith("P") or category.startswith("S") or char.isspace():
            output.append(" ")
        elif char.isalnum():
            output.append(char)
        else:
            output.append(" ")
    return " ".join("".join(output).split())


def tokens(text):
    """Return normalized non-empty whitespace-delimited tokens."""
    value = normalize(text)
    return value.split() if value else []
