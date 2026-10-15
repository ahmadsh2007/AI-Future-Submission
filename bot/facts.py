"""Extract the user's personal situation from the question (age, days left, abroad, times lost ...).

The 7B model is weak at arithmetic and at comparing numbers with thresholds, so code does it and
the result is given to the model as plain-Arabic hints, e.g.
    "العمر المذكور: 17 سنة، أي أكبر من 16 سنة وأقل من 18 سنة."
The hints never contain document facts; they only restate what the user said.
"""
import re

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")


def _norm(text):
    t = (text or "").translate(_AR_DIGITS)
    t = _DIACRITICS.sub("", t)
    t = re.sub(r"[أإآٱ]", "ا", t)
    t = t.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip().lower()


# Spoken / written number words (normalized spelling) -> value. Jordanian forms included.
_NUM_WORDS = {
    "واحد": 1, "وحده": 1, "سنه": 1, "اثنين": 2, "اتنين": 2, "ثنتين": 2, "تنتين": 2,
    "ثلاث": 3, "ثلاثه": 3, "تلات": 3, "تلاته": 3, "اربع": 4, "اربعه": 4, "خمس": 5, "خمسه": 5,
    "ست": 6, "سته": 6, "سبع": 7, "سبعه": 7, "ثمان": 8, "ثمانيه": 8, "تمن": 8, "تمانيه": 8, "ثماني": 8,
    "تسع": 9, "تسعه": 9, "عشر": 10, "عشره": 10,
    "احدعش": 11, "احدعشر": 11, "اطنعش": 12, "اثنعش": 12, "اثنا عشر": 12, "اثني عشر": 12,
    "تلطعش": 13, "ثلاثطعش": 13, "ثلاثه عشر": 13, "ثلاث عشره": 13,
    "اربعطعش": 14, "اربعه عشر": 14, "اربع عشره": 14,
    "خمسطعش": 15, "خمسه عشر": 15, "خمس عشره": 15,
    "ستطعش": 16, "سته عشر": 16, "ست عشره": 16, "السادسه عشر": 16, "سادسه عشر": 16,
    "سبعطعش": 17, "سبعه عشر": 17, "سبع عشره": 17,
    "تمنطعش": 18, "ثمنطعش": 18, "ثمانيه عشر": 18, "ثماني عشره": 18, "الثامنه عشر": 18,
    "تسعطعش": 19, "تسعه عشر": 19, "تسع عشره": 19,
    "عشرين": 20, "ثلاثين": 30, "تلاتين": 30, "اربعين": 40, "خمسين": 50, "ستين": 60,
    "سبعين": 70, "ثمانين": 80, "تمانين": 80, "تسعين": 90,
}
_NUM_ALT = "|".join(sorted((re.escape(k) for k in _NUM_WORDS), key=len, reverse=True))
_TENS_ALT = "عشرين|ثلاثين|تلاتين|اربعين|خمسين|ستين|سبعين|ثمانين|تمانين|تسعين"
_UNITS_ALT = "واحد|اثنين|اتنين|ثلاث|ثلاثه|تلات|تلاته|اربع|اربعه|خمس|خمسه|ست|سته|سبع|سبعه|ثمان|ثمانيه|تمن|تمانيه|ثماني|تسع|تسعه"
# "سبعه واربعين" (47) is tried before single words so "سبعه" alone is not taken as the age.
_NUM = r"(\d+(?:\.\d+)?|(?:%s)\s+و\s*(?:%s)|%s)" % (_UNITS_ALT, _TENS_ALT, _NUM_ALT)


def _val(tok):
    if tok is None:
        return None
    if re.match(r"^\d", tok):
        return float(tok) if "." in tok else int(tok)
    m = re.match(r"^(\S+)\s+و\s*(\S+)$", tok)
    if m and m.group(1) in _NUM_WORDS and m.group(2) in _NUM_WORDS:
        return _NUM_WORDS[m.group(1)] + _NUM_WORDS[m.group(2)]
    return _NUM_WORDS.get(tok)


# Who the number belongs to (looked up just before the age expression). An attached و/ف is allowed.
_PERSON_PRE = r"(?:^|(?<=\s))[وف]?"
_PERSON_POST = r"(?=\s|$)"
_PERSONS = [
    (_PERSON_PRE + r"(?:ابني|ابنى|ولدي|الولد|ابن)" + _PERSON_POST, "الابن"),
    (_PERSON_PRE + r"(?:بنتي|ابنتي|البنت|بنت)" + _PERSON_POST, "البنت"),
    (_PERSON_PRE + r"(?:اخوي|اخي|اخو)" + _PERSON_POST, "الأخ"),
    (_PERSON_PRE + r"(?:اختي|اخت)" + _PERSON_POST, "الأخت"),
    (_PERSON_PRE + r"(?:ابوي|ابي|والدي|ابوه)" + _PERSON_POST, "الأب"),
    (_PERSON_PRE + r"(?:امي|والدتي|امه)" + _PERSON_POST, "الأم"),
    (_PERSON_PRE + r"(?:زوجتي|مرتي|مراتي)" + _PERSON_POST, "الزوجة"),
    (_PERSON_PRE + r"(?:زوجي|جوزي)" + _PERSON_POST, "الزوج"),
    (_PERSON_PRE + r"(?:انا|عمري)" + _PERSON_POST, "المستخدم نفسه"),
    (_PERSON_PRE + r"(?:اهلي|اهلنا|اهله|اهلها)" + _PERSON_POST, "الأهل"),
    (_PERSON_PRE + r"(?:الكبير|الكبيره|الاكبر)" + _PERSON_POST, "الكبير"),
    (_PERSON_PRE + r"(?:الوسطاني|الوسطانيه|الاوسط)" + _PERSON_POST, "الأوسط"),
    (_PERSON_PRE + r"(?:الصغير|الصغيره|الاصغر|الزغير)" + _PERSON_POST, "الصغير"),
]


def person_of(text):
    """First person word in the text (normalized or raw), e.g. 'الأخت'; None if none."""
    t = _norm(text)
    best = None
    for rx, name in _PERSONS:
        m = re.search(rx, t)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), name)
    return best[1] if best else None

_AGE_PATTERNS = [
    r"عمر(?:ي|ه|ها|و|هم|نا)?\s+(?:صار\s+|هلا\s+|حاليا\s+)?" + _NUM,
    _NUM + r"\s+(?:سنه|سنين|سنوات|عام|اعوام)\s+(?:عمري|عمره|عمرها|من عمره|من عمرها)",
    r"(?:ابني|ابنى|ولدي|بنتي|ابنتي|اخوي|اخي|اختي|ابوي|امي|زوجتي|زوجي|جوزي|مرتي)\s+(?:عمره|عمرها)?\s*" + _NUM + r"\s*(?:سنه|سنين|سنوات|عام|اعوام)",
    r"(?:طفل|طفله|قاصر)\s+(?:عمره|عمرها)?\s*" + _NUM + r"\s*(?:سنه|سنين|سنوات)",
]

_ABROAD = [
    "برا البلد", "بره البلد", "برا الاردن", "بره الاردن", "خارج الاردن", "خارج البلاد", "خارج البلد",
    "خارج المملكه", "مغترب", "مغتربه", "بالغربه", "في الغربه", "عايش برا", "ساكن برا", "مقيم برا",
    "مقيم في الخارج", "بالخارج", "في الخارج", "من السفاره", "بالسفاره", "في السفاره", "القنصليه",
    "بالسعوديه", "في السعوديه", "بالامارات", "في الامارات", "بدبي", "في دبي", "بقطر", "في قطر",
    "بالكويت", "في الكويت", "بامريكا", "في امريكا", "بالمانيا", "في المانيا", "بتركيا", "في تركيا",
    "بمصر", "في مصر", "بكندا", "في كندا", "ببريطانيا", "في بريطانيا", "بلندن", "بالعراق", "بعمان العاصمه العمانيه",
]
_INSIDE = ["بالاردن", "في الاردن", "داخل الاردن", "داخل البلاد", "جوا البلد", "بعمان", "في عمان", "باربد", "في اربد", "بالزرقا",
           "عالاردن", "ع الاردن", "على الاردن", "من هون", "هون بالبلد", "بالبلد هون", "من عمان", "من الاردن"]

_URGENT = ["مستعجل", "مستعجله", "المستعجل", "المستعجله", "الخدمه المستعجله", "مكتب الخدمه المستعجله", "عاجل", "بسرعه",
           "بنفس اليوم", "ضروري اليوم"]
_MILITARY = ["عسكري", "عسكريه", "بالجيش", "في الجيش", "القوات المسلحه", "الامن العام", "الدفاع المدني",
             "الدرك", "حفظ السلام", "حفظ سلام", "الاجهزه الامنيه", "شرطي", "ضابط"]
_JERUSALEM = ["مقدسي", "مقدسيه", "هويه مقدسيه", "الهويات المقدسيه", "هويه القدس"]
_FULL_PAGES = ["ممتلي", "ممتلئ", "تعبي", "تعبت صفحاته", "خلصت صفحاته", "خلصو الصفحات", "خلصت الصفحات",
               "ما ضل فيه صفحات", "ما في صفحات", "الصفحات خلصت", "صفحاته خلصت", "امتلا", "امتلات", "امتلت", "تعبت",
               "صفحاته امتلت", "مليان", "مليانه", "ما ضل فيه ولا صفحه"]
_EXPIRED = ["منتهي", "منتهيه", "انتهي", "انتهت", "خلص", "خلصت", "مخلص", "انتهت صلاحيته", "صلاحيته منتهيه", "مش ساري", "مو ساري",
            "خلصان", "خلصانه", "خالص", "خالصه", "مخلصه"]
# Still valid (negations of "expired" must win over the expired words they contain).
_VALID = ["ساري", "ساريه", "لسا ساري", "لسه ساري", "ساري المفعول", "صالح", "مش منتهي", "مو منتهي", "غير منتهي",
          "ما خلص", "لسا ما خلص", "ما انتهي", "ما انتهت", "لسا ما انتهي", "مش خالص", "مش مخلص"]
_MARITAL = ["تغيير الحاله الاجتماعيه", "تزوجت", "اتزوجت", "اتجوزت", "تجوزت", "طلقت", "تطلقت", "انطلقت", "ترملت"]
_INTENTIONAL = ["قصدا", "متعمد", "عن قصد", "بقصد", "عمدا", "قطعته", "مزعته بايدي"]

_TIMES = [
    (r"(?:للمره|المره|مره)\s+(?:الثالثه|التالته|ثالثه|تالته)|(?:ثالث|تالت)\s+مره|3\s*مرات|ثلاث مرات|تلات مرات", 3),
    (r"(?:للمره|المره|مره)\s+(?:الثانيه|التانيه|ثانيه|تانيه)|(?:ثاني|تاني)\s+مره|مرتين|2\s*مرات", 2),
    (r"(?:للمره|المره)\s+(?:الاولي|الاوله)|اول\s+مره\s+(?:بضيع|يضيع|ضاع|بفقد|افقد|فقدت|اضيع|ضيعت)|(?:ضاع|ضيعت|فقدت)\S*\s+(?:لاول|اول)\s+مره"
     r"|فاقد\s+(?:لاول|اول)\s+مره|اول\s+مره\s+(?:بيضيع|بتضيع|تضيع|بيصير|يصير|بصير|بنسرق|بينسرق)", 1),
]


def _phrase_rx(p):
    first, _, rest = p.partition(" ")
    if first.startswith("ال"):
        head = r"(?:[وف]?(?:ب|ل)?%s|[وف]?لل%s)" % (re.escape(first), re.escape(first[2:]))
    else:
        head = r"[وفبل]?" + re.escape(first)
    return r"(?:^|\s)" + head + ((r"\s+" + re.escape(rest).replace(r"\ ", r"\s+")) if rest else "") + r"(?=$|\s)"


def _has(t, phrases):
    """Phrase match on word boundaries; the first word may carry an attached و/ف/ب/ل (e.g. 'بالخدمه')."""
    return any(re.search(_phrase_rx(p), t) for p in phrases)


def _last_pos(t, phrases):
    pos = -1
    for p in phrases:
        for m in re.finditer(_phrase_rx(p), t):
            pos = max(pos, m.start())
    return pos


def _duration_days(n, unit):
    if n is None:
        return None
    if unit.startswith("يوم") or unit.startswith("ايام"):
        return n
    if unit.startswith("اسبوع") or unit.startswith("اسابيع"):
        return n * 7
    if unit.startswith("سن") or unit.startswith("عام") or unit.startswith("اعوام"):
        return n * 365
    return n * 30  # months


_UNIT = r"(يوم|ايام|اسبوع|اسابيع|شهر|شهور|اشهر|سنه|سنين|سنوات|عام|اعوام)"
_DUAL = {"شهرين": (2, "شهر"), "يومين": (2, "يوم"), "اسبوعين": (2, "اسبوع"), "سنتين": (2, "سنه"), "عامين": (2, "عام")}
_FILLER = r"(?:(?:بس|فقط|حوالي|تقريبا|شي|يجي|زي|اكثر من|اقل من|ل)\s+)*"
# A duration: "3 شهور", "تلات سنين", "شهرين", "سنه", "سنه ونص", "سنه وتمن شهور", "لسنه ونص" (attached ل allowed)
_DUR = (r"ل?(?:" + _NUM + r"\s*" + _UNIT + r"|(شهرين|يومين|اسبوعين|سنتين|عامين)|(شهر|يوم|اسبوع|سنه|عام))"
        r"(\s+و\s*نص|\s+ونص)?"
        r"(?:\s+و\s*(\d+|" + _UNITS_ALT + r"|عشر|عشره)\s*(شهر|شهور|اشهر|يوم|ايام))?")


def _dur_days(m, base=1):
    """Days from a _DUR match whose groups start at index `base` (num, unit, dual, single, half, +num, +unit)."""
    num, unit, dual, single, half, num2, unit2 = (m.group(base + i) for i in range(7))
    if num is not None:
        n, u = _val(num), unit
    elif dual is not None:
        n, u = _DUAL[dual]
    else:
        n, u = 1, single
    if n is None:
        return None
    if half:
        n = n + 0.5
    days = _duration_days(n, u)
    extra = _val(num2) if num2 else None
    if extra:
        days += _duration_days(extra, unit2)
    return days


def _remaining_days(t):
    """Days left before the document expires, e.g. 'باقي عليه 3 شهور', 'بيخلص بعد شهرين', 'ساري لسنة ونص'."""
    leads = [
        r"(?:باقي|بقي|ضايل|ضل|متبقي|ظل|ضالل)\s+(?:عليه|عليها|له|لها|الو|الها|فيه|فيها|علي|على انتهايه|على صلاحيته)?\s*",
        r"(?:لسا|لسه|لساته|بعده|بعدو)\s+(?:فيه|فيها|عليه|عليها|الو|الها|ساري\s+ل?)\s*",
        r"(?:بيخلص|بخلص|بينتهي|بنتهي|ينتهي|تنتهي|بتنتهي|بتخلص|صلاحيته)\s+(?:بعد|خلال|كمان)\s+",
        r"(?:ساري|ساريه|صالح|صالحه)\s+(?:المفعول\s+)?(?:لمده\s+|لحد\s+|لغايه\s+|كمان\s+)?",
    ]
    for ld in leads:
        m = re.search(ld + _FILLER + _DUR, t)
        if m:
            return _dur_days(m), m.group(0)
    return None, None


def _since_days(t, anchors):
    """Days since an event, e.g. 'تزوجت من 4 شهور', 'ضاع قبل سنتين', 'من شي اربع شهور', 'صار اله سنتين'."""
    conn = r"(?:من|قبل|صرلي|صارلي|صار لي|صار(?:\s+(?:اله|الو|الها|الي|لي|النا|الهم))?|صرلنا|صارلنا|بقاله|الو|اله)"
    for a in anchors:
        m = re.search(a + r"\s+(?:\S+\s+){0,3}?" + conn + r"\s+" + _FILLER + _DUR, t)
        if m:
            return _dur_days(m), m.group(0)
    return None, None


def extract(question):
    """Return a dict of detected situation facts (only keys that were detected)."""
    t = _norm(question)
    out = {}

    ages = []
    for pat in _AGE_PATTERNS:
        for m in re.finditer(pat, t):
            v = _val(m.group(1))
            if v is None or not (0 < v < 120):
                continue
            before = t[max(0, m.start() - 25):m.end()]
            who = "غير محدد"
            for rx, name in _PERSONS:
                if re.search(rx, before):
                    who = name
            if (v, who) not in ages:
                ages.append((v, who))
    if ages:
        out["ages"] = ages

    days, src = _remaining_days(t)
    if days is not None:
        out["days_left"] = days

    if _has(t, _ABROAD) and _has(t, _INSIDE):
        # "كنت عايش برا، رجعت عالأردن" -> the later mention wins
        out["abroad"] = _last_pos(t, _ABROAD) > _last_pos(t, _INSIDE)
    elif _has(t, _ABROAD):
        out["abroad"] = True
    elif _has(t, _INSIDE):
        out["abroad"] = False
    if _has(t, _URGENT):
        out["urgent"] = True
    if _has(t, _MILITARY):
        out["military"] = True
    if _has(t, _JERUSALEM):
        out["jerusalem_id"] = True
    if _has(t, _FULL_PAGES):
        out["full_pages"] = True
    if _has(t, _VALID):
        out["valid"] = True
    elif _has(t, _EXPIRED) and "full_pages" not in out and days is None:
        out["expired"] = True
    if days is not None:
        out["valid"] = True  # a document with days left is not expired
    if _has(t, _MARITAL):
        out["marital_change"] = True
    if _has(t, _INTENTIONAL):
        out["intentional"] = True

    for rx, n in _TIMES:
        if re.search(rx, t):
            out["times_lost"] = n
            break

    d, _ = _since_days(t, [r"(?:تزوجت|اتزوجت|اتجوزت|تجوزت|تزوجنا|اتزوجنا|اتجوزنا|تجوزنا|عقد الزواج|كتبنا الكتاب|كتب كتابي|عرسي|عرسنا|زواجي|زواجنا|متزوجين|متجوزين)"])
    if d is not None:
        out["days_since_marriage"] = d
    d, _ = _since_days(t, [r"(?:ضاع|ضاعت|ضيعت|ضيعته|ضيعتها|فقدت|فقدته|انسرق|انسرقت|سرق|الفقدان|اول مره|المره الاولي|المره الماضيه|اخر مره|اخر جواز|اخر هويه|اخر دفتر"
                           r"|الاولي|الاول|طلعته|طلعتها|طلعناه|طلعناها|اصدرته|اصدرتها|استلمته|استلمتها|عملته|عملتها|جددته|جددتها"
                           r"|مطلع|مطلعه|مطلعها|مطلعه|طالع|طلعت)"])
    if d is not None:
        out["days_since_previous"] = d
    return out


def _cmp(v, thr, unit):
    if v > thr:
        return "أكبر من %s %s" % (thr, unit)
    if v < thr:
        return "أقل من %s %s" % (thr, unit)
    return "يساوي %s %s" % (thr, unit)


def _fmt(v):
    return str(int(v)) if float(v).is_integer() else str(v)


# Which situation facts matter for which document (others are dropped so the model is not distracted).
_KEYS_BY_DOC = {
    "passport": {"ages", "days_left", "expired", "valid", "full_pages", "abroad", "urgent", "military",
                 "jerusalem_id", "marital_change", "intentional", "times_lost", "days_since_previous"},
    "family_book": {"expired", "valid", "abroad", "times_lost", "days_since_previous", "days_since_marriage", "intentional"},
    "id_card": {"ages", "expired", "valid", "abroad", "times_lost", "days_since_previous", "intentional"},
}


def hints(question, docs=None):
    """Arabic hint lines describing the user's situation, with threshold comparisons precomputed.

    docs: optional iterable of doc keys ("passport", "family_book", "id_card"); when given, only
    facts relevant to those documents are returned.
    """
    f = extract(question)
    if docs:
        keep = set()
        for d in docs:
            keep |= _KEYS_BY_DOC.get(d, set())
        f = {k: v for k, v in f.items() if k in keep}
    lines = []
    for v, who in f.get("ages", []):
        lines.append("عمر %s: %s سنة، أي %s و%s." % (who, _fmt(v), _cmp(v, 16, "سنة"), _cmp(v, 18, "سنة")))
    if "days_left" in f:
        d = f["days_left"]
        lines.append("المدة المتبقية على انتهاء صلاحية الوثيقة: حوالي %s يوماً، أي %s (الوثيقة غير منتهية بعد)." % (_fmt(d), _cmp(d, 180, "يوماً")))
    if f.get("expired"):
        lines.append("ذكر المستخدم أن الوثيقة منتهية الصلاحية.")
    elif f.get("valid") and "days_left" not in f:
        lines.append("ذكر المستخدم أن الوثيقة ما زالت سارية (غير منتهية).")
    if f.get("full_pages"):
        lines.append("ذكر المستخدم أن صفحات الجواز ممتلئة.")
    if f.get("abroad") is True:
        lines.append("المستخدم موجود خارج الأردن (خارج البلاد).")
    elif f.get("abroad") is False:
        lines.append("المستخدم موجود داخل الأردن.")
    if f.get("urgent"):
        lines.append("المستخدم يريد الخدمة المستعجلة.")
    if f.get("military"):
        lines.append("المستخدم من العسكريين أو الأجهزة الأمنية.")
    if f.get("jerusalem_id"):
        lines.append("المستخدم يحمل هوية مقدسية.")
    if f.get("marital_change"):
        lines.append("ذكر المستخدم تغييراً في الحالة الاجتماعية.")
    if f.get("intentional"):
        lines.append("ذكر المستخدم أن التلف كان متعمداً.")
    if "times_lost" in f:
        names = {1: "الأولى", 2: "الثانية", 3: "الثالثة"}
        lines.append("هذه المرة %s التي يفقد فيها الوثيقة." % names.get(f["times_lost"], str(f["times_lost"])))
    if "days_since_marriage" in f:
        d = f["days_since_marriage"]
        lines.append("مضى على عقد الزواج حوالي %s يوماً، أي %s." % (_fmt(d), _cmp(d, 90, "يوماً")))
    if "days_since_previous" in f:
        d = f["days_since_previous"]
        lines.append("مضى على المرة السابقة حوالي %s يوماً (حوالي %s سنة)، أي %s و%s." % (
            _fmt(d), _fmt(round(d / 365.0, 1)), _cmp(d / 365.0, 3, "سنوات"), _cmp(d / 365.0, 5, "سنوات")))
    return lines, f


if __name__ == "__main__":
    import sys
    for q in sys.argv[1:]:
        print(q)
        for line in hints(q)[0]:
            print("  -", line)
