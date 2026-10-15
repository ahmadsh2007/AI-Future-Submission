"""Deterministic routing for the twelve supported government services."""

import re

from . import schema
from .normalize import normalize


_DOC_ORDER = ("passport", "family_book", "id_card")
_SITUATION_ORDER = ("first_issue", "renewal", "lost", "damaged")
_PREFIXES = ("وال", "بال", "فال", "كال", "هال", "لل", "ال", "و", "ف", "ب", "ل", "ك")
_PRONOUN_SUFFIXES = ("كما", "هما", "كم", "كن", "هم", "هن", "نا", "ها", "ه", "ك", "ي")
_VERB_PREFIXES = ("بت", "بي", "ت", "ي", "ب", "ن")
_VERB_SUFFIXES = (
    "تهم", "تها", "ته", "تنا", "توا", "وهم", "وها", "وه",
    "وا", "نا", "ها", "هم", "ت", "ه",
)
_DIALECT_CHAR_MAP = str.maketrans(
    {"ء": "ق", "ك": "ق", "ذ": "د", "ز": "د", "ث": "ت", "ظ": "ض"}
)

_CARD_TRAPS = {
    "الجسور", "جسور", "احصاءات", "فلسطينيه", "اسرائيليه", "ائتمان",
    "بنكيه", "بنك", "مصرفيه", "صراف", "تهنيه", "دعوه", "تموين",
    "مقدسيه", "مقدسي", "القدس", "فيزا", "كارد",
}

_FIELD_PATTERNS = {
    "fees": (
        "رسوم", "الرسم", "بدفع", "ادفع", "بكلف", "بتكلف", "تكلفه",
        "سعر", "دينار", "غرامه", "كفاله", "تعهد مالي", "قيمه", "اغلي", "ارخص",
        "مبلغ", "المبلغ", "مبالغ", "المبالغ", "مصاري", "فلوس", "بيترتب علي", "يترتب علي",
        "بتترتب علي", "المجموع", "كلفه", "بتكلفني", "بيكلف", "يكلف", "تكلف",
    ),
    "documents": (
        "اوراق", "وثايق", "وثائق", "مستندات", "شو بدي اجيب",
        "شو بجيب", "شو بلزمني", "ايش بلزمني", "صور شخصيه", "صوره شخصيه",
        "المرفقات", "اثباتات", "احتاج", "بحتاج", "مطلوب",
    ),
    "conditions": (
        "شروط", "مين بقدر", "من بقدر", "بحقلي", "يحقلي", "يحق له",
        "لازم", "موافقه", "حضور شخصي", "شخصيا", "العمر", "عمر",
        "القاصر", "ولي الامر", "مسموح", "بصير", "صح",
    ),
    "locations": (
        "وين", "اين", "مكان", "اماكن", "سفاره", "السفاره", "قنصليه",
        "برا البلد", "برا الاردن", "خارج الاردن", "خارج البلاد",
        "خارج المملكه", "بالخارج", "داخل الاردن", "داخل البلاد",
    ),
    "time": (
        "قديش بياخد", "كم بياخد", "قديش يستغرق", "كم يستغرق", "كم وقت",
        "قديش وقت", "الوقت المستغرق", "مده", "يستغرق", "دقيقه", "متى بيطلع", "متى بطلع", "متى يطلع",
        "كم يوم", "قديش يوم", "اسبوعين",
        "بتاخد", "بتاخذ", "بياخذ", "وقت", "الوقت", "متى بتطلع", "متى تطلع",
        "امتى بتطلع", "امتى بيطلع", "امتى بطلع", "ساعه",
    ),
    "procedure": (
        "خطوات", "اجراءات", "كيف بقدم", "كيف اقدم", "كيف بطلع",
        "كيف اطلع", "طريقه التقديم", "شو الطريقه", "وين ابدا",
    ),
    "partners": ("شركاء", "جهات شريكه", "الجهات المشاركه", "مين الجهات"),
    "beneficiaries": (
        "مين الفيه", "الفئه المستفيده", "مين بستفيد", "من يستفيد",
        "لغير الاردنيين", "غير الاردني", "لمن الخدمه",
    ),
    "notes": (
        "ملاحظات", "ملاحظه", "استثناء", "استثناءات", "حاله خاصه",
        "حالات خاصه", "تنبيه",
    ),
}

# These denote unsupported services when they are the question's subject.
_STRONG_OUT_OF_SCOPE = (
    "تصديق الشهاده", "تصديق شهاده", "جواز دبلوماسي", "جواز سفر دبلوماسي",
    "جواز خاص", "جواز سفر خاص", "جواز موقت", "جواز سفر موقت",
    "تاشيره", "فيزا", "رخصه", "عدم محكوميه", "لم شمل", "تذكره طيران",
    "تذكره الطيران", "تذاكر طيران", "تذاكر الطيران", "حجز طيران",
    "ساعات الدوام", "اوقات الدوام", "ساعات العمل", "اوقات العمل", "دوام",
    "عطله", "عطل",
)
_ONLINE_ONLY_SUBJECTS = (
    "حجز موعد", "موعد الكتروني", "تطبيق", "الموقع الالكتروني", "موقع الكتروني",
)
_CONTEXTUAL_OUT_OF_SCOPE = (
    "شهاده ميلاد", "شهاده ولاده", "شهاده وفاه", "شهاده زواج",
    "شهاده طلاق", "اقامه", "تجنيس", "جنسيه", "وثيقه سفر",
)
_UNSUPPORTED_SUBJECTS = (
    "تصريح عمل", "تصريح العمل", "اذن عمل", "عامل وافد", "العماله الوافده",
    "رخصه مهن", "رخصه المهن", "سجل تجاري", "السجل التجاري", "ترخيص سياره",
    "تسجيل سياره", "تامين صحي", "التامين الصحي", "ضمان اجتماعي",
    "الضمان الاجتماعي", "بطاقه بنك", "بطاقه بنكيه", "فيزا كارد",
)
_SUBJECT_WORDS = (
    "رسوم", "سعر", "تكلفه", "اصدار", "استخراج", "استخرج", "اطلع",
    "تجديد", "اجدد", "كيف", "وين", "شروط", "اوراق", "وثائق", "بدي",
)


def _contains(text, phrase):
    """Match a normalized phrase while tolerating attached Arabic proclitics."""
    wanted = normalize(phrase).split()
    available = text.split()
    if not wanted or len(wanted) > len(available):
        return False
    for start in range(len(available) - len(wanted) + 1):
        if all(
            _token_forms(available[start + offset]) & _token_forms(term)
            for offset, term in enumerate(wanted)
        ):
            return True
    return False


def _token_forms(word):
    """Yield a word and forms with common Arabic proclitics removed."""
    forms = {word}
    pending = [word]
    while pending:
        current = pending.pop()
        for prefix in _PREFIXES:
            if current.startswith(prefix) and len(current) > len(prefix) + 1:
                stripped = current[len(prefix):]
                if stripped not in forms:
                    forms.add(stripped)
                    pending.append(stripped)
    return forms


def _is_stem(word, stems, allow_suffix=True):
    for form in _token_forms(word):
        for stem in stems:
            if form == stem:
                return True
            if allow_suffix and form.startswith(stem):
                suffix = form[len(stem):]
                if suffix in _PRONOUN_SUFFIXES:
                    return True
    return False


def _dialect_key(word):
    """Collapse common Jordanian spelling substitutions for family matching."""
    return word.translate(_DIALECT_CHAR_MAP)


def _is_word_family(word, stems):
    """Match a verb stem with dialect letters and common spoken affixes.

    Prefixes and suffixes are removed at most twice. This covers combinations
    such as بتضيع, لقيتها, سرقوها, and نمددها without using loose substrings.
    """
    wanted = {_dialect_key(normalize(stem)) for stem in stems}
    pending = [(_dialect_key(form), 0, 0) for form in _token_forms(word)]
    seen = set()
    while pending:
        current, prefix_depth, suffix_depth = pending.pop()
        state = (current, prefix_depth, suffix_depth)
        if state in seen:
            continue
        seen.add(state)
        if current in wanted:
            return True
        if prefix_depth < 2:
            for prefix in _VERB_PREFIXES:
                key = _dialect_key(prefix)
                if current.startswith(key) and len(current) > len(key) + 1:
                    pending.append((current[len(key):], prefix_depth + 1, suffix_depth))
        if suffix_depth < 2:
            for suffix in _VERB_SUFFIXES:
                key = _dialect_key(suffix)
                if current.endswith(key) and len(current) > len(key) + 1:
                    pending.append((current[:-len(key)], prefix_depth, suffix_depth + 1))
    return False


def _token_items(text):
    return [(match.group(), match.start(), match.end()) for match in re.finditer(r"\S+", text)]


def _dedupe_mentions(mentions):
    result = []
    seen = set()
    for item in sorted(mentions, key=lambda value: (value[1], -(value[2] - value[1]))):
        key = (item[0], item[1])
        if key in seen:
            continue
        # A phrase and its component token describe one mention, not two.
        if result and result[-1][0] == item[0] and item[1] < result[-1][2]:
            continue
        result.append(item)
        seen.add(key)
    return result


def _detect_docs(text):
    items = _token_items(text)
    mentions = []
    consumed = set()
    identity_descriptors = {"ذكيه", "شخصيه", "احوال", "مدنيه"}
    has_military_book = any(
        _contains(text, phrase)
        for phrase in ("دفتر خدمه العلم", "دفاتر خدمه العلم", "دفترين خدمه العلم")
    )
    for index, (word, start, end) in enumerate(items):
        if index in consumed:
            continue
        forms = _token_forms(word)
        nearby = set()
        for item in items[max(0, index - 2):index + 3]:
            nearby.update(_token_forms(item[0]))
        next_words = [item[0] for item in items[index + 1:index + 4]]

        if _is_stem(
            word,
            ("جواز", "جوازات", "جوازين", "باسبور", "باسبورات", "باسبورين", "passport"),
        ):
            mentions.append(("passport", start, end))
            continue

        identity_word = (
            _is_stem(word, ("هويه", "هويت", "هويات", "هويتين"))
            or any(form == "id" for form in forms)
            or _is_stem(word, ("ذكيه",), allow_suffix=False)
        )
        card_word = _is_stem(word, ("بطاقه", "بطاقت", "بطاقات", "بطاقتين"))
        card_is_trap = bool(nearby & _CARD_TRAPS)
        if (identity_word or card_word) and not card_is_trap:
            compound_end = end
            # Collapse "البطاقة الشخصية/الذكية/الأحوال المدنية" and
            # "الهوية الذكية" into one document mention.
            for lookahead in range(index + 1, min(len(items), index + 4)):
                descriptor_forms = _token_forms(items[lookahead][0])
                if descriptor_forms & identity_descriptors:
                    consumed.add(lookahead)
                    compound_end = items[lookahead][2]
                else:
                    break
            mentions.append(("id_card", start, compound_end))
            continue

        if _is_stem(word, ("دفتر", "دفاتر", "دفترين")):
            is_service_booklet = len(next_words) >= 2 and (
                _is_stem(next_words[0], ("خدمه",), allow_suffix=False)
                and _is_stem(next_words[1], ("علم",), allow_suffix=False)
            )
            is_family_booklet = any(
                _is_stem(next_word, ("عايله", "عيله", "اسره"), allow_suffix=False)
                for next_word in next_words[:2]
            )
            # Once دفتر خدمة العلم is introduced, a later bare الدفتر refers
            # to that booklet unless family wording explicitly changes it.
            if not is_service_booklet and (not has_military_book or is_family_booklet):
                mentions.append(("family_book", start, end))

    # Family-record and newlywed vocabulary is specific enough to imply the
    # family book even when the user never says دفتر.
    family_topics = (
        "رب الاسره", "ربا للاسره", "القيد المدني", "قيد مدني", "فتح قيد",
        "فتح سجل مدني", "السجل المدني", "سجل مدني",
        "اقدم الزوجات", "الزوجه الثانيه", "الزوجتين",
        "تعدد الزوجات", "المطلقه تفتح قيد", "المطلقه فتح قيد",
        "الابناء غير الشرعيين", "ابناء غير شرعيين", "دفتر عيله",
        "وفاه رب الاسره", "لسا متجوزين", "تزوجنا", "اتجوزنا",
        "كتبنا الكتاب", "عرسنا", "بعد العرس", "حديثا متزوجين",
    )
    if not any(item[0] == "family_book" for item in mentions):
        positions = [text.find(normalize(term)) for term in family_topics if normalize(term) in text]
        if positions:
            position = min(value for value in positions if value >= 0)
            mentions.append(("family_book", position, position + 1))
    return _dedupe_mentions(mentions)


def _is_replacement_reference(text):
    replacement_words = (
        "بدالها", "بداله", "بدالهم", "بدالنا", "بدلها", "بدله", "بدلهم",
        "بدل عنه", "بدل عنها", "بدل عنهم", "وحده بدل", "واحد بدل",
    )
    return any(_contains(text, phrase) for phrase in replacement_words)


def _same_document_context(first, other, docs):
    """Return whether two situations refer to the same nearby document mention."""
    gap = max(first[1] - other[2], other[1] - first[2], 0)
    if gap > 60:
        return False
    if not docs:
        return True
    first_center = (first[1] + first[2]) / 2.0
    first_doc = min(
        docs,
        key=lambda doc: (abs(((doc[1] + doc[2]) / 2.0) - first_center), doc[1]),
    )
    return first_doc == _nearest_doc(other, docs)


def _detect_situations(text, docs):
    items = _token_items(text)
    mentions = []
    first_mentions = []

    def add_phrase_mentions(situation, phrases):
        for phrase in phrases:
            normalized = normalize(phrase)
            for match in re.finditer(r"(?<!\w)%s(?!\w)" % re.escape(normalized), text):
                mention = (situation, match.start(), match.end())
                mentions.append(mention)
                if situation == "first_issue":
                    first_mentions.append(mention)

    phrase_terms = {
        "first_issue": (
            "اول مره", "لاول مره", "للمره الاولي",
            "اول جواز", "اول باسبور", "اول هويه", "اول بطاقه", "اول دفتر",
        ),
        "renewal": (
            "انتهت صلاحيته", "انتهت صلاحيتها", "منتهي الصلاحيه",
            "خلصت صفحاته", "خلصت صفحات", "خلصت مدته", "خلصت صلاحيتها",
            "خلصت صلاحيته", "قرب يخلص", "قربت تخلص", "بيخلص الشهر الجاي",
            "باقي فيه", "باقي فيها", "باقي عليه", "باقي عليها", "ضل فيه",
            "ضل فيها", "صار قديم", "صارت قديمه", "تمديد صلاحيه",
        ),
        "lost": (
            "بدل فاقد", "بدل مفقود", "وقع مني", "وقعت مني", "طاح مني",
            "طاحت مني", "ما لقيته", "ما لقيتها", "مش لاقيه", "مش لاقيها",
            "ما بلاقيه", "ما بلاقيها", "راح مني", "راحت مني",
            "مش عارف وينه", "مش عارف وينها", "ضيعته بالعزال",
            "ضيعتها بالعزال", "نسيته بالتكسي", "نسيتها بالتكسي",
            "انسرقت المحفظه", "انسرقت محفظتي",
        ),
        "damaged": (
            "بدل تالف", "بدل اتلاف", "انقطع نصين", "انقطعت نصين", "نصين",
            "وقع بالمي", "وقعت بالمي", "وقع بالميه", "وقعت بالميه",
            "وقع عليه مي", "وقعت عليه مي", "وقع عليها مي", "وقعت عليها مي",
            "انغسل مع الغسيل", "انغسلت مع الغسيل", "شخبط عليه",
            "شخبط عليها", "الشريحه طالعه", "الشريحه خربانه",
            "الكلب اكل", "الكلب اكله", "الكلب اكلها", "كلبي اكل",
            "كلبي اكله", "كلبي اكلها", "الولد لعب فيه", "الولد لعب فيها",
            "ابني لعب فيه", "ابني لعب فيها",
        ),
    }
    for situation, phrases in phrase_terms.items():
        add_phrase_mentions(situation, phrases)

    renewal_stems = (
        "تجديد", "تجدد", "جدد", "اجدد", "يتجدد", "منتهي", "انتهي",
        "انته", "خلص", "خلصان", "خلصانه", "خالص", "مخلص", "ممتلي",
        "تعبي", "مدد", "امدد", "تمديد",
    )
    lost_stems = (
        "ضاع", "ضايع", "ضيع", "فقد", "فاقد", "مفقود", "انسرق", "سرق",
        "اضاع", "اضعت", "اختفي", "نسي", "نشل", "انخطف", "خطف",
    )
    damaged_stems = (
        "تلف", "تالف", "متلف", "اتلف", "اهتري", "اهتر", "مهتري",
        "انمزق", "تمزق", "ممزق", "شق", "انشق", "مشقوق", "قص", "انقص",
        "مقصوص", "قطع", "انقطع", "غرق", "بلل", "تبلل", "مبلول",
        "نقع", "انغسل", "غسل", "لزق", "ملزق", "ذاب", "انحرق",
        "احترق", "حرق", "محروق", "ولع", "اتمزع", "تمزع", "مزع",
        "مخربش", "خربش", "شخبط", "انمحي", "انمسح", "ممسوح", "مسح",
        "باهت", "انكسر", "كسر", "مكسور", "طق", "انطوي", "مطعوج",
        "طعج", "خرب", "خربان", "تخرب", "تبهدل", "مخزوق", "انخزق",
    )
    water_damage = any(
        _contains(text, phrase)
        for phrase in ("بالمي", "بالميه", "عليه مي", "عليها مي")
    )
    apartment_words = {
        "الشقه", "بالشقه", "والشقه", "فالشقه", "للشقه", "شقتي",
        "شقتنا", "شقته", "شقتها", "شقتهم",
    }
    for word, start, end in items:
        if _is_word_family(word, renewal_stems):
            mentions.append(("renewal", start, end))
        if _is_word_family(word, lost_stems):
            mentions.append(("lost", start, end))
        # وقعته is a required colloquial loss form, but the same verb in a
        # water clause describes damage instead.
        if not water_damage and _is_word_family(word, ("وقعته", "وقعتها")):
            mentions.append(("lost", start, end))
        # الشقة is a frequent newlywed-story noun, not an inflection of شق.
        if word not in apartment_words and _is_word_family(word, damaged_stems):
            mentions.append(("damaged", start, end))

    issue_verbs = (
        r"(?:طلعت|طلعنا|طلع|عملت|عملنا|عمل|فتحت|فتحنا|فتح|"
        r"استخرجت|استخرجنا|استخرج)(?:ها|ه|هم)?"
    )
    negative_patterns = (
        r"(?<!\w)(?:(?:عمري|عمره|عمرها|عمرهم|لسا)\s+)?[وف]?ما\s+%s(?!\w)" % issue_verbs,
        r"(?<!\w)ولا\s+مره\s+%s(?!\w)" % issue_verbs,
        (
            r"(?<!\w)(?:لسا\s+)?[وف]?ما\s+"
            r"(?:عندي|عنده|عندها|عندهم|عندنا|معي|معه|معها|معهم|معنا)(?!\w)"
        ),
    )
    for pattern in negative_patterns:
        for match in re.finditer(pattern, text):
            # Anchor near the following document so this clause-local first
            # issue wins over a renewal/loss stated for another document.
            mention = ("first_issue", max(match.end() - 1, match.start()), match.end())
            mentions.append(mention)
            first_mentions.append(mention)

    # Apply the same negative rule to productive spoken forms such as
    # ما بنطلعها and ما بيستخرجوه.
    issue_stems = ("طلع", "استخرج", "اعمل", "عمل", "افتح", "فتح", "اصدر")
    for index, (word, start, end) in enumerate(items):
        if not _is_word_family(word, issue_stems):
            continue
        previous = items[max(0, index - 4):index]
        previous_forms = set()
        for previous_word, _, _ in previous:
            previous_forms.update(_token_forms(previous_word))
        if "ما" in previous_forms or (
            "ولا" in previous_forms and "مره" in previous_forms
        ):
            mention = ("first_issue", max(end - 1, start), end)
            mentions.append(mention)
            first_mentions.append(mention)

    # First-time or non-possession language describes the count/context of a
    # loss or damage when both refer to the same document. It is not another
    # service request, but remains clause-local in multi-document stories.
    conflicting = [mention for mention in mentions if mention[0] in ("lost", "damaged")]
    ignored_first = {
        first for first in first_mentions
        if any(_same_document_context(first, other, docs) for other in conflicting)
    }
    if ignored_first:
        mentions = [mention for mention in mentions if mention not in ignored_first]

    # Only infer a first issue from a positive issuance verb when no explicit
    # situation was stated. A request for a replacement is never first issue.
    if not mentions and docs and not _is_replacement_reference(text):
        first_words = {
            "اصدار", "استصدار", "استخراج", "استخرج", "استخرجت", "اطلع",
            "تطلع", "يطلع", "طلع", "اعمل",
        }
        receiving_document = any(
            _is_word_family(word, ("استلم", "تسلم")) for word, _, _ in items
        )
        for word, start, end in items:
            forms = _token_forms(word)
            is_new_document = bool(forms & {"جديد", "جديده"}) and not receiving_document
            if forms & first_words or is_new_document or _is_word_family(word, issue_stems):
                mentions.append(("first_issue", start, end))
                break
        if not mentions and docs and any(
            _contains(text, phrase)
            for phrase in ("بدي جواز", "بدي هويه", "بدي بطاقه", "بدي دفتر")
        ):
            position = text.find("بدي")
            mentions.append(("first_issue", position, position + 3))

    # Newlywed, civil-record, and family-head topics default to first issue
    # only when no renewal/loss/damage wording is present.
    # "ملف عائلي" is NOT here: in the data it only appears as a passport first-issue document.
    family_first_phrases = (
        "فتح قيد", "فتح سجل",
        "لغير المسجلين", "رب الاسره", "وفاه رب الاسره", "تعدد الزوجات",
        "اقدم الزوجات", "الزوجه الثانيه", "الزوجتين",
        "المطلقه تفتح قيد", "المطلقه بدها تفتح قيد", "تفتح قيد",
        "الابناء غير الشرعيين", "لسا متجوزين",
        "تزوجنا", "اتجوزنا", "كتبنا الكتاب", "عرسنا", "بعد العرس",
        "حديثا متزوجين", "السجل المدني", "القيد المدني",
    )
    if not mentions and any(_contains(text, phrase) for phrase in family_first_phrases):
        positions = [
            text.find(normalize(phrase))
            for phrase in family_first_phrases
            if normalize(phrase) in text
        ]
        position = min(positions) if positions else 0
        mentions.append(("first_issue", position, position + 1))

    return _dedupe_mentions(mentions)


def _detect_fields(text):
    found = []

    def add(field):
        if field not in found:
            found.append(field)

    if _contains(text, "شو المطلوب") or _contains(text, "ايش المطلوب") or _contains(text, "ما المطلوب"):
        add("documents")
        add("conditions")
    if _contains(text, "شو بعمل") or _contains(text, "ايش اعمل") or _contains(text, "ماذا افعل"):
        add("procedure")
        add("documents")

    located = []
    for field, patterns in _FIELD_PATTERNS.items():
        positions = [text.find(normalize(pattern)) for pattern in patterns if normalize(pattern) in text]
        if positions:
            located.append((min(positions), field))
    for _, field in sorted(located):
        add(field)

    # Bare "كم/قديش" usually asks a fee, except with duration or document quantity.
    if ("كم" in text.split() or "قديش" in text.split()) and not any(
        field in found for field in ("fees", "time", "documents")
    ):
        add("fees")
    return found


def _is_out_of_scope(text, docs, situations):
    if any(_contains(text, phrase) for phrase in _STRONG_OUT_OF_SCOPE):
        return True
    # Appointment/application/site help is unsupported by itself, but can be
    # incidental wording in a complete in-scope document+situation question.
    if any(_contains(text, phrase) for phrase in _ONLINE_ONLY_SUBJECTS) and not (
        docs and situations
    ):
        return True
    requested_certificates = (
        "شهاده ميلاد", "شهاده ولاده", "شهاده وفاه", "شهاده زواج", "شهاده طلاق",
    )
    certificate_actions = ("اطلع", "استخراج", "اصدار", "بدي", "رسوم", "تجديد")
    if any(_contains(text, certificate) for certificate in requested_certificates) and any(
        _contains(text, "%s %s" % (action, certificate))
        for action in certificate_actions
        for certificate in requested_certificates
    ):
        return True
    if not docs and any(
        _contains(text, phrase)
        for phrase in (
            "دفتر خدمه العلم", "دفاتر خدمه العلم", "دفترين خدمه العلم",
            "بطاقه الجسور", "بطاقات الجسور", "بطاقه احصاءات الجسور",
            "بطاقات احصاءات", "بطاقات احصاءات الجسور",
            "البطاقه الفلسطينيه", "بطاقه فلسطينيه", "البطاقه الاسرائيليه",
        )
    ):
        return True
    if not docs and any(_contains(text, phrase) for phrase in _UNSUPPORTED_SUBJECTS):
        if any(_contains(text, subject) for subject in _SUBJECT_WORDS):
            return True
    has_family_context = any(doc[0] == "family_book" for doc in docs) or _contains(text, "رب الاسره")
    has_in_scope_doc = bool(docs)
    for phrase in _CONTEXTUAL_OUT_OF_SCOPE:
        if not _contains(text, phrase):
            continue
        if phrase in ("شهاده وفاه", "شهاده زواج", "شهاده طلاق") and has_family_context:
            continue
        if phrase in ("اقامه", "جنسيه", "وثيقه سفر") and has_in_scope_doc:
            continue
        if any(_contains(text, subject) for subject in _SUBJECT_WORDS):
            return True
    foreign_passport_phrases = (
        "جواز اجنبي", "جواز السفر الاجنبي", "جواز سفر لغير الاردنيين",
        "جواز لغير الاردنيين", "جواز سفر غير اردني",
    )
    if any(_contains(text, phrase) for phrase in foreign_passport_phrases) and any(
        _contains(text, word) for word in ("اجدد", "تجديد", "اصدار", "اطلع", "بدل فاقد", "بدل تالف")
    ):
        return True
    return False


def _nearest_doc(situation, docs):
    center = (situation[1] + situation[2]) / 2.0
    # Loss/damage predicates usually follow their noun, but forms such as
    # "ضاع الجواز" put the document immediately after the predicate. Let a
    # close following noun win over a much older preceding mention.
    if situation[0] in ("lost", "damaged"):
        preceding = [doc for doc in docs if doc[2] <= situation[1]]
        following = [doc for doc in docs if doc[1] >= situation[2]]
        closest_preceding = max(preceding, key=lambda doc: doc[2]) if preceding else None
        closest_following = min(following, key=lambda doc: doc[1]) if following else None
        if closest_following and closest_following[1] - situation[2] <= 16:
            if not closest_preceding or situation[1] - closest_preceding[2] > 20:
                return closest_following
        if closest_preceding:
            return closest_preceding
    return min(docs, key=lambda doc: (abs(((doc[1] + doc[2]) / 2.0) - center), doc[1]))


def _resolve(docs, situations):
    """Return definite pairs and unresolved doc/situation values with anchors."""
    pairs = []
    unresolved_docs = []
    unresolved_situations = []
    if docs and situations:
        if len(docs) == 1:
            for situation in situations:
                pairs.append((docs[0][0], situation[0], min(docs[0][1], situation[1])))
        elif len(situations) == 1:
            for doc in docs:
                pairs.append((doc[0], situations[0][0], min(doc[1], situations[0][1])))
        else:
            assigned_docs = set()
            assigned_doc_names = set()
            for situation in situations:
                doc = _nearest_doc(situation, docs)
                pairs.append((doc[0], situation[0], min(doc[1], situation[1])))
                assigned_docs.add((doc[0], doc[1]))
                assigned_doc_names.add(doc[0])
            # A repeated mention of an already-resolved document (often in a
            # trailing fee question) does not introduce a new unknown service.
            unresolved_docs.extend(
                doc for doc in docs
                if (doc[0], doc[1]) not in assigned_docs and doc[0] not in assigned_doc_names
            )
    elif docs:
        unresolved_docs.extend(docs)
    elif situations:
        unresolved_situations.extend(situations)
    return pairs, unresolved_docs, unresolved_situations


_PERSON_CLAUSE_WORDS = {
    "انا", "اني", "هو", "هي", "هم", "زوجي", "زوجتي", "جوزي", "مرتي",
    "ابني", "بنتي", "امي", "ابوي", "اخي", "اختي", "اخوي", "ابونا", "امنا",
}


def _clause_start_kind(word):
    """Classify conjunction-attached words that start an independent clause."""
    forms = _token_forms(word)
    if forms & _PERSON_CLAUSE_WORDS:
        return "person"
    if (
        _is_stem(
            word,
            ("جواز", "جوازات", "جوازين", "باسبور", "باسبورات", "باسبورين", "passport"),
        )
        or _is_stem(word, ("هويه", "هويت", "هويات", "هويتين"))
        or _is_stem(word, ("بطاقه", "بطاقت", "بطاقات", "بطاقتين"))
        or _is_stem(word, ("دفتر", "دفاتر", "دفترين"))
    ):
        return "document"
    return None


def _split_clauses(question):
    """Return normalized clauses and whether each continues a document list."""
    source = question if isinstance(question, str) else str(question)
    clauses = []
    anchor = 0
    for raw_part in re.split(r"[،,.;؛!?؟\n]+", source):
        words = normalize(raw_part).split()
        if not words:
            continue
        start = 0
        shares_previous = False
        index = 1
        while index < len(words):
            next_start = index
            kind = None
            if words[index] == "و" and index + 1 < len(words):
                kind = _clause_start_kind(words[index + 1])
                next_start = index + 1
            elif words[index].startswith("و"):
                kind = _clause_start_kind(words[index])
            if kind:
                clause = " ".join(words[start:index])
                if clause:
                    clauses.append((clause, anchor, shares_previous))
                    anchor += len(clause) + 100
                start = next_start
                shares_previous = kind == "document"
                index = start + 1
                continue
            index += 1
        clause = " ".join(words[start:])
        if clause:
            clauses.append((clause, anchor, shares_previous))
            anchor += len(clause) + 100
    if clauses:
        return clauses
    return [(normalize(question), 0, False)]


def _resolve_by_clause(question):
    """Detect and resolve evidence locally before narrowly sharing situations."""
    full_text = normalize(question)
    has_military_book = any(
        _contains(full_text, phrase)
        for phrase in ("دفتر خدمه العلم", "دفاتر خدمه العلم", "دفترين خدمه العلم")
    )
    records = []
    for clause, offset, shares_previous in _split_clauses(question):
        docs = _detect_docs(clause)
        situations = _detect_situations(clause, docs)
        words = [item[0] for item in _token_items(clause)]
        has_book_word = any(
            _is_stem(word, ("دفتر", "دفاتر", "دفترين")) for word in words
        )
        has_family_label = has_book_word and any(
            _is_stem(word, ("عايله", "عيله", "اسره", "عائلي"), allow_suffix=False)
            for word in words
        )
        # A later bare "الدفتر" keeps referring to a previously introduced
        # military-service booklet unless family wording explicitly changes it.
        if has_military_book and has_book_word and not has_family_label:
            docs = [doc for doc in docs if doc[0] != "family_book"]
            situations = _detect_situations(clause, docs)
        records.append({
            "offset": offset,
            "shares_previous": shares_previous,
            "docs": docs,
            "situations": situations,
            "has_book_word": has_book_word,
        })

    # A newlywed/civil-record topic without an explicit booklet is context for
    # an explicit family-book loss, damage, or renewal in a neighbouring clause.
    for index, record in enumerate(records):
        if record["has_book_word"] or not record["docs"]:
            continue
        if {item[0] for item in record["docs"]} != {"family_book"}:
            continue
        if {item[0] for item in record["situations"]} != {"first_issue"}:
            continue
        has_explicit_family_situation = any(
            other_index != index
            and any(doc[0] == "family_book" for doc in other["docs"])
            and any(situation[0] != "first_issue" for situation in other["situations"])
            for other_index, other in enumerate(records)
        )
        if has_explicit_family_situation:
            record["docs"] = []
            record["situations"] = []

    # Preserve established pronoun continuations such as "it was stolen, my
    # ID": with only one document and one situation, this is completion rather
    # than sharing one situation across several documents.
    doc_records = [record for record in records if record["docs"]]
    situation_records = [record for record in records if record["situations"]]
    if len(doc_records) == 1 and len(situation_records) == 1:
        doc_record = doc_records[0]
        situation_record = situation_records[0]
        if doc_record is not situation_record and not doc_record["situations"]:
            situation_names = {item[0] for item in situation_record["situations"]}
            if len(situation_names) == 1 and not situation_record["docs"]:
                situation = next(iter(situation_names))
                position = doc_record["docs"][0][1]
                doc_record["situations"] = [(situation, position, position)]
                situation_record["situations"] = []

    # A conjunction-started document may share one situation with its adjacent
    # list item. Punctuation and person-started clauses never borrow evidence.
    for _ in range(len(records)):
        changed = False
        for index, record in enumerate(records):
            if not record["docs"] or record["situations"]:
                continue
            neighbours = []
            if record["shares_previous"] and index > 0:
                neighbours.append(records[index - 1])
            if index + 1 < len(records) and records[index + 1]["shares_previous"]:
                neighbours.append(records[index + 1])
            for neighbour in neighbours:
                situation_names = {item[0] for item in neighbour["situations"]}
                if len(situation_names) != 1:
                    continue
                situation = next(iter(situation_names))
                position = record["docs"][0][1]
                record["situations"] = [(situation, position, position)]
                changed = True
                break
        if not changed:
            break

    all_docs = []
    all_situations = []
    pairs = []
    unresolved_docs = []
    unresolved_situations = []
    for record in records:
        offset = record["offset"]
        docs = record["docs"]
        situations = record["situations"]
        local_pairs, local_docs, local_situations = _resolve(docs, situations)
        all_docs.extend((name, start + offset, end + offset) for name, start, end in docs)
        all_situations.extend(
            (name, start + offset, end + offset) for name, start, end in situations
        )
        pairs.extend((doc, situation, position + offset) for doc, situation, position in local_pairs)
        unresolved_docs.extend(
            (name, start + offset, end + offset) for name, start, end in local_docs
        )
        unresolved_situations.extend(
            (name, start + offset, end + offset)
            for name, start, end in local_situations
        )

    # Trailing field clauses may repeat evidence already resolved earlier.
    resolved_doc_names = {doc for doc, _, _ in pairs}
    resolved_situation_names = {situation for _, situation, _ in pairs}
    unresolved_docs = [doc for doc in unresolved_docs if doc[0] not in resolved_doc_names]
    unresolved_situations = [
        situation
        for situation in unresolved_situations
        if situation[0] not in resolved_situation_names
        and not (
            situation[0] == "first_issue"
            and bool(resolved_situation_names & {"lost", "damaged"})
        )
    ]
    return (
        _dedupe_mentions(all_docs),
        _dedupe_mentions(all_situations),
        pairs,
        unresolved_docs,
        unresolved_situations,
    )


def _history_context(history):
    if not history:
        return [], [], []
    for turn in reversed(history):
        if not isinstance(turn, dict):
            continue
        previous = turn.get("route")
        if not isinstance(previous, dict):
            continue
        service_ids = previous.get("services") or previous.get("candidates") or []
        docs = []
        situations = []
        for service in service_ids:
            if service not in schema.SERVICES:
                continue
            doc, situation, _ = schema.SERVICES[service]
            if doc not in docs:
                docs.append(doc)
            if situation not in situations:
                situations.append(situation)
        # Candidate variation represents uncertainty, not several definite
        # mentions. Retain only dimensions the previous turn had resolved.
        previous_missing = previous.get("missing")
        if previous_missing in ("doc", "doc_and_situation"):
            docs = []
        if previous_missing in ("situation", "doc_and_situation"):
            situations = []
        if docs or situations:
            fields = [field for field in previous.get("fields", []) if field in schema.FIELD_KEYS]
            return docs, situations, fields
    return [], [], []


def _candidate_ids(pairs, unresolved_docs, unresolved_situations):
    candidates = []

    def add(service):
        if service in schema.SERVICES and service not in candidates:
            candidates.append(service)

    for doc, situation, _ in sorted(pairs, key=lambda item: item[2]):
        add(schema.service_id(doc, situation))
    for doc in unresolved_docs:
        doc_name = doc[0] if isinstance(doc, tuple) else doc
        for situation in _SITUATION_ORDER:
            add(schema.service_id(doc_name, situation))
    for situation in unresolved_situations:
        situation_name = situation[0] if isinstance(situation, tuple) else situation
        for doc in _DOC_ORDER:
            add(schema.service_id(doc, situation_name))
    return candidates


def _result(status, services=None, candidates=None, fields=None, missing=None,
            inherited=False, docs=None, situations=None, reason=""):
    return {
        "status": status,
        "services": services or [],
        "candidates": candidates or [],
        "fields": fields or [],
        "missing": missing,
        "inherited": bool(inherited),
        "mentions": {"docs": docs or [], "situations": situations or []},
        "reason": reason,
    }


def route(question, history=None):
    """Route one user question without invoking a language model.

    The function is intentionally total: malformed input or an unexpected
    internal failure produces a contract-shaped result rather than raising.
    """
    try:
        text = normalize(question)
        if not text:
            return _result(schema.STATUS_OUT_OF_SCOPE, reason="empty question")

        (
            doc_mentions,
            situation_mentions,
            pairs,
            unresolved_docs,
            unresolved_situations,
        ) = _resolve_by_clause(question)
        fields = _detect_fields(text)
        mention_docs = [item[0] for item in doc_mentions]
        mention_situations = [item[0] for item in situation_mentions]

        if _is_out_of_scope(text, doc_mentions, situation_mentions):
            return _result(
                schema.STATUS_OUT_OF_SCOPE, fields=fields, docs=mention_docs,
                situations=mention_situations, reason="unsupported service is the subject",
            )

        inherited = False
        previous_docs, previous_situations, previous_fields = _history_context(history)

        if not doc_mentions and previous_docs:
            anchors = situation_mentions or [("", 0, 0)]
            inherited_docs = [(doc, anchors[0][1], anchors[0][1]) for doc in previous_docs]
            doc_mentions = inherited_docs
            inherited = True
        if not situation_mentions and previous_situations:
            anchors = doc_mentions or [("", 0, 0)]
            inherited_situations = [(situation, anchors[0][1], anchors[0][1]) for situation in previous_situations]
            situation_mentions = inherited_situations
            inherited = True
        if not fields and previous_fields:
            fields = list(previous_fields)
            inherited = True

        if inherited:
            pairs, unresolved_docs, unresolved_situations = _resolve(doc_mentions, situation_mentions)

        # No routing evidence and no useful history is outside this knowledge base.
        if not doc_mentions and not situation_mentions and not fields:
            return _result(
                schema.STATUS_OUT_OF_SCOPE, fields=fields, inherited=inherited,
                docs=mention_docs, situations=mention_situations,
                reason="no supported service intent detected",
            )

        services = []
        for doc, situation, _ in sorted(pairs, key=lambda item: item[2]):
            service = schema.service_id(doc, situation)
            if service in schema.SERVICES and service not in services:
                services.append(service)

        candidates = _candidate_ids(pairs, unresolved_docs, unresolved_situations)
        missing_doc = bool(unresolved_situations) or (not doc_mentions and bool(situation_mentions))
        missing_situation = bool(unresolved_docs) or (not situation_mentions and bool(doc_mentions))

        if not doc_mentions and not situation_mentions:
            missing = "doc_and_situation"
            candidates = list(schema.SERVICES)
        elif missing_doc and missing_situation:
            missing = "doc_and_situation"
        elif missing_doc:
            missing = "doc"
        elif missing_situation:
            missing = "situation"
        else:
            missing = None

        if missing is None and services:
            status = schema.STATUS_OK
            candidates = list(services)
            reason = "resolved explicit or inherited service mentions"
        else:
            status = schema.STATUS_UNCLEAR
            if not candidates:
                candidates = list(schema.SERVICES)
            reason = "missing %s" % missing

        return _result(
            status, services, candidates, fields, missing, inherited,
            mention_docs, mention_situations, reason,
        )
    except Exception as error:  # pragma: no cover - defensive contract boundary
        return _result(
            schema.STATUS_OUT_OF_SCOPE,
            reason="router internal error: %s" % type(error).__name__,
        )
