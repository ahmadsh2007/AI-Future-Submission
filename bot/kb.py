# -*- coding: utf-8 -*-
"""Knowledge base: parse + clean the 12 raw service files in data/.

Public API
----------
load_kb(data_dir=None) -> dict
    service_id -> {
        "id", "doc", "situation", "name_ar", "title_raw", "title_raw_alt",
        "fields": {field_key: [item, ...]}     # every schema.FIELD_KEYS key present
    }
    Parses the raw files on every call (they are tiny). Deterministic.

get_kb() -> dict
    Module-level cached load_kb() (loaded once, on first use).

field_items(service_id, field_key, kb=None) -> list[str]

context_string(service_id, field_key, items=None, kb=None) -> str
    "<name_ar> - <Arabic label>: <items joined>"
    Numbered items ("1. ...") are joined with a single space, unnumbered
    items (fees / locations / partners ...) are joined with "؛ " so the
    pieces stay distinguishable for the model.

Running `python3 -m bot.kb` from the project folder writes
    kb/services.json, kb/services_clean.txt, kb/cleaning_log.txt
and prints a verification report.

Python 3.9 standard library only.
"""
import json
import os
import re
import sys

try:
    from . import schema
except ImportError:  # pragma: no cover - direct script use
    import schema  # type: ignore

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(HERE)
DEFAULT_DATA_DIR = os.path.join(PROJECT_DIR, "data")
KB_OUT_DIR = os.path.join(PROJECT_DIR, "kb")

# --------------------------------------------------------------------------- #
# Raw file vocabulary
# --------------------------------------------------------------------------- #
MENU_LINES = {"الرئيسية", "الخدمات", "دليل الخدمات", "شارك"}

# raw label text (stripped) -> field key
LABEL_TO_KEY = {
    "الفئة المستفيدة": "beneficiaries",
    "أماكن تقديم الخدمة": "locations",
    "شروط تقديم الخدمة": "conditions",
    "الوثائق المطلوبة للحصول على الخدمة": "documents",
    "الوثائق المطلوبة": "documents",
    "إجراءات تقديم الخدمة": "procedure",
    "الزمن المستغرق لتقديم الخدمة": "time",
    "شركاء الخدمة": "partners",
    "ملاحظات": "notes",
    "الرسوم": "fees",
}

# Fields whose items are "logical points" (numbered lists in the raw files).
LIST_FIELDS = ("conditions", "documents", "procedure", "notes")

# numbering prefix inside LIST_FIELDS only: "1. ", "1-", "4.. ", " 2. ", "8تحويل"
NUMBERING_RE = re.compile(r"^\s*(\d{1,2})\s*(?:[.\-–]+\s*|(?=[\u0600-\u06FF]))")
BULLET_RE = re.compile(r"^\s*[-–•]\s*")

ARABIC_INDIC = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}
ARABIC_INDIC.update({ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")})

# Spelling fixes applied ONLY where the meaning is unambiguous. Never touches
# numbers, amounts, ages, durations, conditions or exceptions.
TYPO_FIXES = [
    ("دنانبر", "دنانير"),
    ("بطافات", "بطاقات"),
    ("فسم الطباعة", "قسم الطباعة"),
    ("الوئيفة", "الوثيقة"),
    ("الوئيقة", "الوثيقة"),
    ("إ\u2018حصاءات", "إحصاءات"),
    ("مكاتب ]دائرة", "مكاتب دائرة"),
    ("تتسليم", "تسليم"),
    ("اختصاصة", "اختصاصه"),
    ("؟أمين", "أمين"),
    ("االدفترلمتلقي", "الدفتر لمتلقي"),
    ("لمتلفي الخدمة", "لمتلقي الخدمة"),
    ("الأصولوسحب", "الأصول وسحب"),
    ("الصندوقلاستيفاء", "الصندوق لاستيفاء"),
    ("التأكدمن", "التأكد من"),
    ("أخذالتوقيع", "أخذ التوقيع"),
    ("لإعلامهبجاهزية", "لإعلامه بجاهزية"),
    ("والرسال امر", "وإرسال امر"),
    ("الكترونياإلى", "الكترونيا إلى"),
    ("مشرحات", "مشروحات"),
    ("الامرالاب", "الامر الاب"),
    ("قراءته الياً", "قراءته آلياً"),
    ("للعسكرين", "للعسكريين"),
    ("إفراد الأسرة", "أفراد الأسرة"),
    ("انهاء خدمة العمل", "انهاء خدمة العلم"),
]

# Amount / duration written in words -> append the digits in parentheses.
# The words are kept; the regex is idempotent (skips if digits already follow).
WORD_NUMBERS = [
    # (regex, replacement, human label for the log)
    (re.compile(r"ثلاثة أشهر(?!\s*\(\d+\))"), "ثلاثة أشهر (3)", "ثلاثة أشهر -> (3)"),
    (re.compile(r"(ال)?ثلاث سنوات(?!\s*\(\d+\))"), r"\g<0> (3)", "ثلاث سنوات -> (3)"),
    (re.compile(r"أسبوعين(?!\s*\(\d+\))"), "أسبوعين (2)", "أسبوعين -> (2)"),
    (re.compile(r"عشرة دنانير(?!\s*\(\d+\))"), "عشرة دنانير (10)", "عشرة دنانير -> (10)"),
    (re.compile(r"دينارين(?!\s*\(\d+\))"), "دينارين (2)", "دينارين -> (2)"),
    (re.compile(r"ثلاثة دنانير(?!\s*\(\d+\))"), "ثلاثة دنانير (3)", "ثلاثة دنانير -> (3)"),
    (re.compile(r"الثامنة عشر(?!\s*\(\d+\))"), "الثامنة عشر (18)", "الثامنة عشر -> (18)"),
    (re.compile(r"السادسة عشر(?!\s*\(\d+\))"), "السادسة عشر (16)", "السادسة عشر -> (16)"),
]

_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #
def ascii_digits(text):
    """Arabic-Indic / Persian digits -> ASCII digits."""
    return text.translate(ARABIC_INDIC)


def norm_ws(text):
    """Whitespace / punctuation-spacing normalization only (no fact change)."""
    t = text.replace("\t", " ")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\(\s+", "(", t)
    t = re.sub(r"\s+\)", ")", t)
    t = re.sub(r"\s+([.،:؛])", r"\1", t)
    t = re.sub(r"\s*/\s*", "/", t)
    # "45دقيقة", "10دنانير", "250دينار" -> put a space between digit and letter
    t = re.sub(r"(\d)([\u0600-\u06FF])", r"\1 \2", t)
    # "الطلب(رب" -> "الطلب (رب", "والصورة)ويتم" -> "والصورة) ويتم", "،ادخال" -> "، ادخال"
    t = re.sub(r"([\u0600-\u06FF\d])\(", r"\1 (", t)
    t = re.sub(r"\)([\u0600-\u06FF])", r") \1", t)
    t = re.sub(r"،([\u0600-\u06FF])", r"، \1", t)
    t = re.sub(r"\s*\+\s*", " + ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def norm_compare(text):
    """Aggressive normalization used only for comparisons (dedup, checks)."""
    t = ascii_digits(text)
    t = _DIACRITICS_RE.sub("", t)
    t = re.sub(r"[أإآٱ]", "ا", t)
    t = t.replace("ة", "ه").replace("ى", "ي")
    t = _PUNCT_RE.sub(" ", t)
    return t.lower()


def words(text):
    return [w for w in norm_compare(text).split() if w]


def strip_numbering(text):
    return re.sub(r"^\s*\d{1,2}\.\s*", "", text)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def _label_key(line):
    """Return field key if `line` starts a new field, else None."""
    if not line.strip():
        return None
    # continuation marker: whitespace + TAB at the start of the line
    if re.match(r"^[ \u00a0]+\t", line):
        return None
    head = line.split("\t", 1)[0].strip()
    return LABEL_TO_KEY.get(head)


def _parse_raw(text):
    """Split a raw file into (title_lines, {field_key: [raw_line, ...]})."""
    text = ascii_digits(text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = text.split("\n")
    title_lines = []
    raw_fields = {k: [] for k in schema.FIELD_KEYS}
    current = None
    for line in lines:
        key = _label_key(line)
        if key is not None:
            current = key
            rest = line.split("\t", 1)[1] if "\t" in line else ""
            if rest.strip():
                raw_fields[key].append(rest)
            continue
        if not line.strip():
            continue
        if current is None:
            s = line.strip()
            if s in MENU_LINES:
                continue
            title_lines.append(s)
        else:
            raw_fields[current].append(line)
    return title_lines, raw_fields


def _build_items(key, raw_lines):
    """Turn the raw lines of one field into logical items (uncleaned text)."""
    items = []
    if key in LIST_FIELDS:
        numbered_seen = False
        for line in raw_lines:
            s = norm_ws(line)
            if not s:
                continue
            m = NUMBERING_RE.match(s)
            if m:
                numbered_seen = True
                items.append(s[m.end():].strip())
                continue
            if BULLET_RE.match(s):
                if numbered_seen and items:
                    # sub-item of the previous numbered item: merge, keep the dash
                    items[-1] = items[-1] + " - " + BULLET_RE.sub("", s)
                else:
                    items.append(BULLET_RE.sub("", s))
                continue
            if numbered_seen and items:
                items[-1] = items[-1] + " " + s  # wrapped continuation line
            else:
                items.append(s)
    else:
        for line in raw_lines:
            s = norm_ws(line)
            if s:
                items.append(s)
    return [i for i in items if i]


def _clean_item(text, log, sid, key):
    t = ascii_digits(text)
    for bad, good in TYPO_FIXES:
        if bad in t:
            t = t.replace(bad, good)
            log.append((sid, key, "TYPO", "'%s' -> '%s'" % (bad, good), text))
    t = norm_ws(t)
    for rx, repl, label in WORD_NUMBERS:
        new = rx.sub(repl, t)
        if new != t:
            log.append((sid, key, "DIGITS", "appended digits: %s" % label, new))
            t = new
    return t


def _dedup(items, log, sid, key):
    """Remove exact duplicates and items fully contained in another item."""
    out = []
    sets = []
    for it in items:
        ws = set(words(strip_numbering(it)))
        dup = False
        for j, other in enumerate(sets):
            if ws == other:
                log.append((sid, key, "DUP", "removed exact duplicate", it))
                dup = True
                break
            if len(ws) >= 5 and ws < other:
                log.append((sid, key, "DUP", "removed near-duplicate (subset of: %s)" % out[j], it))
                dup = True
                break
        if dup:
            continue
        # a later, more complete item may swallow an earlier shorter one
        for j, other in enumerate(sets):
            if len(other) >= 5 and other < ws:
                log.append((sid, key, "DUP", "removed near-duplicate (subset of: %s)" % it, out[j]))
                out[j] = None
                sets[j] = set()
        out.append(it)
        sets.append(ws)
    return [i for i in out if i is not None]


def _renumber(key, items, raw_lines):
    if key not in LIST_FIELDS:
        return items
    raw_numbered = any(NUMBERING_RE.match(norm_ws(l)) for l in raw_lines)
    if raw_numbered or len(items) >= 2:
        return ["%d. %s" % (i, it) for i, it in enumerate(items, 1)]
    return items


def _parse_service(sid, path, log):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    title_lines, raw_fields = _parse_raw(text)
    doc, situation, name_ar = schema.SERVICES[sid]
    titles = [norm_ws(t).strip("()").strip() for t in title_lines]
    title_raw = titles[-1] if titles else name_ar
    alts = [t for t in titles if t != title_raw]
    fields = {}
    for key in schema.FIELD_KEYS:
        items = _build_items(key, raw_fields[key])
        items = [_clean_item(it, log, sid, key) for it in items]
        items = _dedup(items, log, sid, key)
        items = _renumber(key, items, raw_fields[key])
        fields[key] = items
    return {
        "id": sid,
        "doc": doc,
        "situation": situation,
        "name_ar": name_ar,
        "title_raw": title_raw,
        "title_raw_alt": alts[0] if alts else "",
        "fields": fields,
    }


def load_kb(data_dir=None, _log=None):
    """Parse all 12 raw files. Returns service_id -> service dict."""
    data_dir = data_dir or DEFAULT_DATA_DIR
    log = _log if _log is not None else []
    kb = {}
    for sid in schema.SERVICES:
        path = os.path.join(data_dir, sid + ".txt")
        kb[sid] = _parse_service(sid, path, log)
    return kb


_KB_CACHE = None


def get_kb():
    global _KB_CACHE
    if _KB_CACHE is None:
        _KB_CACHE = load_kb()
    return _KB_CACHE


def field_items(service_id, field_key, kb=None):
    kb = kb if kb is not None else get_kb()
    return list(kb[service_id]["fields"][field_key])


def _join_items(items):
    if not items:
        return ""
    numbered = all(re.match(r"^\d+\.\s", it) for it in items)
    return (" " if numbered else "؛ ").join(items)


def context_string(service_id, field_key, items=None, kb=None):
    """'<name_ar> - <Arabic label>: <items>' (items default to the whole field)."""
    kb = kb if kb is not None else get_kb()
    if items is None:
        items = kb[service_id]["fields"][field_key]
    name_ar = schema.SERVICES[service_id][2]
    label = schema.FIELD_LABELS[field_key]
    return "%s - %s: %s" % (name_ar, label, _join_items(list(items)))


def service_text(service_id, kb=None, fields=None):
    """All fields of one service as context strings (one per field)."""
    kb = kb if kb is not None else get_kb()
    keys = fields or schema.FIELD_KEYS
    return [context_string(service_id, k, kb=kb) for k in keys if kb[service_id]["fields"][k]]


# --------------------------------------------------------------------------- #
# Verification (run by `python3 -m bot.kb`)
# --------------------------------------------------------------------------- #
def _raw_content_lines(path):
    """Non-menu raw lines, label part removed, numbering stripped -> list[str]."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    title_lines, raw_fields = _parse_raw(text)
    out = [(None, t) for t in title_lines]
    for key in schema.FIELD_KEYS:
        for line in raw_fields[key]:
            s = norm_ws(line)
            if not s:
                continue
            if key in LIST_FIELDS:
                m = NUMBERING_RE.match(s)
                if m:
                    s = s[m.end():].strip()
                s = BULLET_RE.sub("", s)
            out.append((key, s))
    return out


def _service_clean_text(svc):
    parts = [svc["title_raw"], svc["title_raw_alt"]]
    for key in schema.FIELD_KEYS:
        parts.extend(strip_numbering(it) for it in svc["fields"][key])
    return " ".join(p for p in parts if p)


def _typo_explains(word):
    for bad, _good in TYPO_FIXES:
        if word in words(bad):
            return bad
    return None


def verify(kb, data_dir=None, out=print):
    data_dir = data_dir or DEFAULT_DATA_DIR
    problems = 0

    out("=== (a) number coverage: every raw number appears in the cleaned service ===")
    for sid, svc in kb.items():
        raw_nums = set()
        for _key, line in _raw_content_lines(os.path.join(data_dir, sid + ".txt")):
            raw_nums.update(re.findall(r"\d+", line))
        clean_nums = set(re.findall(r"\d+", _service_clean_text(svc)))
        missing = sorted(raw_nums - clean_nums, key=int)
        status = "OK " if not missing else "FAIL"
        if missing:
            problems += 1
        out("  %s %-26s raw numbers=%-3d missing=%s" % (status, sid, len(raw_nums), missing))

    out("\n=== (b) word coverage: raw line words present in cleaned service (>10% missing flagged) ===")
    flagged = 0
    for sid, svc in kb.items():
        clean_words = set(words(_service_clean_text(svc)))
        for key, line in _raw_content_lines(os.path.join(data_dir, sid + ".txt")):
            ws = words(line)
            if not ws:
                continue
            missing = [w for w in ws if w not in clean_words]
            if len(missing) / float(len(ws)) > 0.10:
                flagged += 1
                explained = {w: _typo_explains(w) for w in missing}
                unexplained = [w for w, e in explained.items() if e is None]
                if unexplained:
                    problems += 1
                out("  %s %s/%s: missing %s of %d words -> %s" % (
                    "FAIL" if unexplained else "ok  ", sid, key, missing, len(ws),
                    "explained by typo fixes %s" % sorted(set(e for e in explained.values() if e))
                    if not unexplained else "UNEXPLAINED %s | line: %s" % (unexplained, line)))
    out("  lines flagged: %d" % flagged)

    out("\n=== (c) item counts per field (required non-empty: beneficiaries, locations, documents, procedure, time, fees) ===")
    required = ("beneficiaries", "locations", "documents", "procedure", "time", "fees")
    header = "%-26s" % "service" + "".join("%6s" % k[:5] for k in schema.FIELD_KEYS)
    out("  " + header)
    for sid, svc in kb.items():
        counts = [len(svc["fields"][k]) for k in schema.FIELD_KEYS]
        empty_required = [k for k in required if not svc["fields"][k]]
        if empty_required:
            problems += 1
        out("  %-26s%s%s" % (sid, "".join("%6d" % c for c in counts),
                            "  FAIL empty: %s" % empty_required if empty_required else ""))

    out("\n=== (d) spot checks ===")
    checks = [
        ("passport_renewal", "fees", ["180", "16"], 6),
        ("passport_lost", "fees", ["125", "250", "5"], None),
        ("id_card_lost", "notes", ["10", "50", "أسبوعين"], 4),
        ("family_book_first_issue", "notes", ["أكبر الأبناء", "ثلاثة أشهر", "30"], None),
        ("family_book_first_issue", "fees", ["2", "10", "90"], None),
        ("family_book_damaged", "fees", ["3 دنانير", "استيفاء قيمة التعهد"], 2),
    ]
    for sid, key, needles, count in checks:
        items = kb[sid]["fields"][key]
        text = " ".join(items)
        ok = all(n in text for n in needles) and (count is None or len(items) == count)
        if not ok:
            problems += 1
        out("  %s %s/%s (%d items)%s" % ("OK " if ok else "FAIL", sid, key, len(items),
                                         "" if count is None else " expected %d" % count))
        for it in items:
            out("        " + it)
    out("\nVERIFICATION %s (%d problem(s))" % ("PASSED" if problems == 0 else "FAILED", problems))
    return problems


def _write_outputs(kb, log):
    os.makedirs(KB_OUT_DIR, exist_ok=True)
    with open(os.path.join(KB_OUT_DIR, "services.json"), "w", encoding="utf-8") as fh:
        json.dump(kb, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    lines = []
    for sid, svc in kb.items():
        lines.append("=" * 78)
        lines.append("%s  |  %s  |  title: %s%s" % (
            sid, svc["name_ar"], svc["title_raw"],
            " (menu: %s)" % svc["title_raw_alt"] if svc["title_raw_alt"] else ""))
        lines.append("=" * 78)
        for key in schema.FIELD_KEYS:
            lines.append("[%s] %s  (%d)" % (key, schema.FIELD_LABELS[key], len(svc["fields"][key])))
            for it in svc["fields"][key]:
                lines.append("    " + it)
        lines.append("")
    with open(os.path.join(KB_OUT_DIR, "services_clean.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    with open(os.path.join(KB_OUT_DIR, "cleaning_log.txt"), "w", encoding="utf-8") as fh:
        fh.write("Cleaning log: every change beyond whitespace/numbering, per service.\n")
        fh.write("Types: TYPO (spelling fix), DUP (removed duplicate), DIGITS (digits appended to words)\n\n")
        for sid in kb:
            entries = [e for e in log if e[0] == sid]
            fh.write("## %s (%d changes)\n" % (sid, len(entries)))
            for _sid, key, typ, what, item in entries:
                fh.write("- [%s] %s: %s\n    item: %s\n" % (key, typ, what, item))
            fh.write("\n")
    return log


def main():
    log = []
    kb = load_kb(_log=log)
    _write_outputs(kb, log)
    print("wrote kb/services.json, kb/services_clean.txt, kb/cleaning_log.txt (%d logged changes)\n" % len(log))
    problems = verify(kb)
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
