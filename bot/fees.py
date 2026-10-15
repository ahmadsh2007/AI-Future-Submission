"""Pick the fee lines that apply to the user's situation (code), so the 7B model only has to copy them.

The fee field of most services is a rule table (age, expiry, abroad, times lost, urgent office ...).
A 7B model often picks the wrong row. This module:
  1. splits multi-person questions into chunks (one per person / service),
  2. reads each chunk's situation with bot.facts.extract,
  3. selects the exact source lines that apply, the lines that clearly do NOT apply (with the reason),
     and, when a fact is missing, the alternatives ("if ... then ...").
Every line returned is an item copied from the knowledge base; the only computed value is a sum of two
source amounts (e.g. 50 + 25 urgent office = 75). The model still writes the answer.
"""
import re

from bot import facts as factsmod
from bot import router, schema
from bot.normalize import normalize


class Case(object):
    def __init__(self, service, who=None, situation=None):
        self.service = service
        self.who = who
        self.situation = situation or []   # Arabic descriptions of the facts used
        self.apply = []                    # [item]
        self.not_apply = []                # [(item, reason)]
        self.conditional = []              # [(condition, item)]
        self.total = None                  # (expression, value) or None

    def items_used(self):
        return list(self.apply)

    def __repr__(self):
        return "Case(%s, who=%s, apply=%d, not=%d, cond=%d, total=%s)" % (
            self.service, self.who, len(self.apply), len(self.not_apply), len(self.conditional), self.total)


# ----------------------------------------------------------------------------- helpers
def _find(items, *needles):
    """First item containing every needle (normalized). None if not found."""
    ns = [normalize(n) for n in needles]
    for it in items or []:
        t = normalize(it)
        if all(n in t for n in ns):
            return it
    return None


def _amount(item):
    """The money amount of a fee/notes item: the number right before دينار/دنانير (list markers ignored)."""
    t = normalize(re.sub(r"^\s*\d{1,2}\s*[.)\-]\s", " ", item or ""))
    m = re.search(r"(\d+)\s*(?:\)\s*)?(?:دينار|دنانير)", t) or re.search(r"\d+", t)
    return int(m.group(1) if m.lastindex else m.group(0)) if m else None


def _age(f):
    ages = f.get("ages") or []
    return ages[0][0] if len(ages) == 1 else None


def _years_since(f):
    d = f.get("days_since_previous")
    return None if d is None else d / 365.0


def _fmt(v):
    return str(int(v)) if float(v).is_integer() else str(round(v, 1))


def _describe(f):
    out = []
    a = _age(f)
    if a is not None:
        out.append("العمر %s سنة" % _fmt(a))
    if "days_left" in f:
        out.append("متبقي على انتهاء الوثيقة حوالي %s يوماً" % _fmt(f["days_left"]))
    elif f.get("expired"):
        out.append("الوثيقة منتهية")
    elif f.get("valid"):
        out.append("الوثيقة سارية")
    if f.get("full_pages"):
        out.append("صفحات الجواز ممتلئة")
    if f.get("abroad") is True:
        out.append("خارج الأردن")
    elif f.get("abroad") is False:
        out.append("داخل الأردن")
    if f.get("urgent"):
        out.append("يريد مكتب الخدمة المستعجلة")
    if f.get("military"):
        out.append("من العسكريين/الأجهزة الأمنية")
    if f.get("marital_change"):
        out.append("تغيير في الحالة الاجتماعية")
    if "times_lost" in f:
        out.append("المرة %s للفقدان" % {1: "الأولى", 2: "الثانية", 3: "الثالثة"}.get(f["times_lost"], f["times_lost"]))
    if "days_since_previous" in f:
        out.append("مضى على المرة السابقة حوالي %s سنة" % _fmt(round(f["days_since_previous"] / 365.0, 1)))
    if "days_since_marriage" in f:
        out.append("مضى على عقد الزواج حوالي %s يوماً" % _fmt(f["days_since_marriage"]))
    return out


# ----------------------------------------------------------------------------- rules per service
def _passport_renewal(c, F, N, f):
    mil = _find(F, "20", "القوات المسلحة")
    u16 = _find(F, "25", "دون السادسة")
    full = _find(F, "20", "الممتلئ")
    exp = _find(F, "50", "180")
    valid = _find(F, "100", "غير المنتهي")
    abroad = _find(F, "100", "خارج البلاد")
    urgent = _find(N, "يضاف", "المستعجلة")
    age = _age(f)
    base = None
    if f.get("abroad") is True:
        if age is not None and age < 16:
            c.conditional += [("لمن هم خارج البلاد", abroad), ("لمن هم دون السادسة عشر", u16)]
        else:
            base = abroad
    elif f.get("military") or f.get("marital_change"):
        base = mil
    elif age is not None and age < 16:
        base = u16
    elif f.get("full_pages") and not f.get("expired"):
        base = full
    elif f.get("expired") or ("days_left" in f and f["days_left"] < 180):
        if age is None:
            c.conditional += [("إذا كان عمره فوق السادسة عشر", exp), ("إذا كان دون السادسة عشر", u16)]
        else:
            base = exp
    elif "days_left" in f and f["days_left"] > 180:
        if age is not None and age < 16:
            base = u16
        else:
            base = valid
    elif f.get("valid"):
        c.conditional += [("إذا كان المتبقي على انتهاء الجواز أقل من 180 يوماً", exp),
                          ("إذا كان المتبقي أكثر من 180 يوماً", valid)]
    if base:
        c.apply.append(base)
        if age is not None and age > 16 and base is not u16 and u16:
            c.not_apply.append((u16, "لأن العمر أكبر من 16 سنة"))
    elif not c.conditional:  # nothing known about the person: show every rule
        c.conditional += [("لأفراد القوات المسلحة والأجهزة الأمنية أو عند تغيير الحالة الاجتماعية", mil),
                          ("لمن هم دون السادسة عشر", u16), ("للجواز الممتلئ الصفحات وساري المفعول", full),
                          ("لمن هم فوق السادسة عشر وجوازه منتهي أو متبقي أقل من 180 يوماً", exp),
                          ("للجواز غير المنتهي أو المتبقي أكثر من 180 يوماً", valid),
                          ("لمن هم خارج البلاد", abroad)]
    if f.get("urgent") and urgent:
        c.apply.append(urgent)
        if base and _amount(base) is not None:
            c.total = ("%d + %d" % (_amount(base), _amount(urgent)), _amount(base) + _amount(urgent))


def _passport_first_issue(c, F, N, f):
    mil = _find(F, "20", "القوات المسلحة")
    u16 = _find(F, "25", "16")
    inside = _find(F, "50", "داخل")
    abroad = _find(F, "100", "خارج")
    age = _age(f)
    if f.get("military"):
        c.apply.append(mil)
    elif f.get("abroad") is True:
        if age is not None and age < 16:
            c.conditional += [("لمن هم خارج البلاد", abroad), ("لمن هم دون سن 16", u16)]
        else:
            c.apply.append(abroad)
    elif age is not None and age < 16:
        c.apply.append(u16)
        c.not_apply.append((inside, "لأن العمر أقل من 16 سنة"))
    elif age is not None:
        c.apply.append(inside)
        c.not_apply.append((u16, "لأن العمر ليس دون 16 سنة"))
    else:
        c.conditional += [("لأفراد القوات المسلحة والأجهزة الأمنية", mil), ("لمن هم دون سن 16", u16),
                          ("لمن هم فوق 16 داخل البلاد", inside), ("لمن هم خارج البلاد", abroad)]


def _passport_lost(c, F, N, f):
    first = _find(F, "125")
    later = _find(F, "250")
    t = f.get("times_lost")
    if t == 1:
        c.apply.append(first)
        c.not_apply.append((later, "لأنها المرة الأولى"))
    elif t and t >= 2:
        c.apply.append(later)
        c.not_apply.append((first, "لأنها ليست المرة الأولى"))
        y = _years_since(f)
        if y is not None:
            c.situation.append("شرط تحصيل الكفالة السابقة (أقل من 5 سنوات): %s" % ("ينطبق" if y < 5 else "لا ينطبق"))
    else:
        c.conditional += [("إذا كانت المرة الأولى", first), ("إذا كانت أي مرة بعد الأولى", later)]


def _family_book_first_issue(c, F, N, f):
    fee = _find(F, "2", "رسوم")
    fine = _find(F, "10", "غرامه")
    c.apply.append(fee)
    d = f.get("days_since_marriage")
    if d is not None and d > 90:
        c.apply.append(fine)
        c.total = ("%d + %d" % (_amount(fee), _amount(fine)), _amount(fee) + _amount(fine))
    elif d is not None:
        c.not_apply.append((fine, "لأنه لم يمر 90 يوماً على عقد الزواج"))
    else:
        c.conditional.append(("إذا مرّ 90 يوماً على عقد الزواج", fine))


def _family_book_renewal(c, F, N, f):
    exp = _find(F, "دينارين")
    valid = _find(F, "غير منتهي")
    if f.get("expired"):
        c.apply.append(exp)
        c.not_apply.append((valid, "لأن الدفتر منتهي"))
    elif f.get("valid"):
        c.apply.append(valid)
        c.not_apply.append((exp, "لأن الدفتر غير منتهي"))
    else:
        c.conditional += [("إذا كان الدفتر منتهي المدة", exp), ("إذا كان غير منتهي المدة", valid)]


def _family_book_lost(c, F, N, f):
    base = _find(F, "5 دنانير")
    c.apply.append(base)
    prev = _find(F, "استيفاء")
    t = f.get("times_lost")
    y = _years_since(f)
    if t == 3:
        c.apply.append(_find(N, "للمره الثالثه", "50"))
    elif t == 2:
        second = _find(N, "للمره الثانيه")
        c.apply.append(second)
        if y is not None and y < 3:
            c.total = ("%d + %d" % (_amount(base), 10), _amount(base) + 10)
    elif t == 1:
        c.apply.append(_find(N, "لاول مره"))
    else:
        c.apply.append(_find(F, "تعهد خطي", "10"))
        c.conditional += [("إذا كانت المرة الثانية", _find(N, "للمره الثانيه")),
                          ("إذا كانت المرة الثالثة", _find(N, "للمره الثالثه", "50"))]
    if t and t >= 2 and y is not None:
        if y < 3:
            c.apply.append(prev)
        else:
            c.not_apply.append((prev, "لأن الفقدان السابق كان قبل أكثر من 3 سنوات"))


def _family_book_damaged(c, F, N, f, D):
    c.apply.append(_find(F, "3 دنانير"))
    pledge = _find(D, "التعهد الخطي", "10")
    if pledge:
        c.apply.append(pledge)
    prev = _find(F, "استيفاء")
    y = _years_since(f)
    if y is not None:
        if y < 3:
            c.apply.append(prev)
        else:
            c.not_apply.append((prev, "لأن الإصدار السابق كان قبل أكثر من 3 سنوات"))
    else:
        c.conditional.append(("إذا حدث التلف خلال 3 سنوات من الإصدار السابق", prev))


def _id_card_first_issue(c, F, N, f):
    fee = _find(F, "2 دينار")
    fine = _find(F, "غرامه", "18")
    c.apply.append(fee)
    age = _age(f)
    if age is not None and age >= 18:
        c.apply.append(fine)
        c.total = ("%d + %d" % (_amount(fee), _amount(fine)), _amount(fee) + _amount(fine))
    elif age is not None:
        c.not_apply.append((fine, "لأن العمر أقل من 18 سنة"))
    else:
        c.conditional.append(("إذا أتم 18 عاماً ولم يصدر بطاقة", fine))


def _id_card_lost(c, F, N, f):
    base = _find(F, "5 دنانير")
    c.apply.append(base)
    prev = _find(F, "استيفاء")
    second = _find(N, "للمره الثانيه", "10")
    third = _find(N, "50", "للمره الثالثه")
    t = f.get("times_lost")
    y = _years_since(f)
    if t == 3:
        c.apply.append(_find(N, "للمره الثالثه", "لجنه"))
        c.apply.append(third)
    elif t == 2:
        if y is not None and y >= 3:
            c.not_apply.append((second, "لأن الفقدان السابق كان قبل أكثر من 3 سنوات"))
            c.not_apply.append((prev, "لأن الفقدان السابق كان قبل أكثر من 3 سنوات"))
        elif y is not None:
            c.apply += [second, prev]
            c.total = ("%d + %d" % (_amount(base), _amount(second)), _amount(base) + _amount(second))
        else:
            c.conditional.append(("إذا كان الفقدان السابق خلال أقل من 3 سنوات", second))
    elif t is None:
        c.conditional += [("إذا كانت المرة الثانية خلال أقل من 3 سنوات", second), ("إذا كانت المرة الثالثة", third)]


def _single(c, F, N, f):
    c.apply += list(F)


RULES = {
    "passport_renewal": _passport_renewal,
    "passport_first_issue": _passport_first_issue,
    "passport_lost": _passport_lost,
    "passport_damaged": _single,
    "family_book_first_issue": _family_book_first_issue,
    "family_book_renewal": _family_book_renewal,
    "family_book_lost": _family_book_lost,
    "family_book_damaged": None,  # needs documents (pledge line), handled below
    "id_card_first_issue": _id_card_first_issue,
    "id_card_renewal": _single,
    "id_card_lost": _id_card_lost,
    "id_card_damaged": _single,
}


def compute(service, f, kb, who=None):
    fields = kb[service]["fields"]
    F, N, D = fields.get("fees") or [], fields.get("notes") or [], fields.get("documents") or []
    c = Case(service, who, _describe(f))
    if service == "family_book_damaged":
        _family_book_damaged(c, F, N, f, D)
    else:
        RULES[service](c, F, N, f)
    c.apply = [x for x in dict.fromkeys(c.apply) if x]
    c.not_apply = [(x, r) for x, r in c.not_apply if x and x not in c.apply]
    c.conditional = [(cond, x) for cond, x in c.conditional if x]
    return c


# ----------------------------------------------------------------------------- multi-person splitting
# A new person starts at "و + person word" ("وبنتي", "واختي"); a bare "انا" inside a clause does not split.
_PERSON_START = re.compile(r"\s+(?=و(?:انا|ابني|ابنى|بنتي|ابنتي|اخوي|اخي|اختي|ابوي|والدي|امي|والدتي|زوجتي|مرتي|زوجي|جوزي)(?:\s|$))")
_MY_DOC = re.compile(r"(?:^|\s)[وفب]?(?:جوازي|باسبوري|هويتي|بطاقتي|دفتري)(?:\s|$)")


def _segments(question):
    raw = re.split(r"[،,.؛;!?؟:\n]+|\s+(?:و?كمان|بس|اما)\s+", question or "")
    out = []
    for part in raw:
        p = normalize(part)
        if p:
            out.extend(s.strip() for s in _PERSON_START.split(p) if s.strip())
    return out or [normalize(question)]


def _who(seg):
    who = factsmod.person_of(seg)
    if who is None and _MY_DOC.search(seg):
        who = "المستخدم نفسه"
    return who


def _chunks(question):
    """[(who, [segments])]: a new chunk starts when a different person is named."""
    chunks = []
    for seg in _segments(question):
        who = _who(seg)
        if chunks and (who is None or who == chunks[-1][0]):
            chunks[-1][1].append(seg)
        else:
            chunks.append([who, [seg]])
    return [(w, s) for w, s in chunks]


def _distinct_people(question):
    return len(set(w for w, _ in _chunks(question) if w))


def cases(question, services, kb, previous=None):
    """Fee cases for the routed services. previous: earlier question texts of this chat (follow-ups)."""
    services = [s for s in services if s in schema.SERVICES]
    if not services:
        return []
    chunks = _chunks(question)
    people = [w for w, _ in chunks if w]
    if len(services) == 1 and len(set(people)) <= 1:
        f = {}
        for p in previous or []:
            f.update(factsmod.extract(p))
        f.update(factsmod.extract(question))  # the current message wins
        return [compute(services[0], f, kb)]

    out = []
    background = {}  # facts said in clauses without a document (e.g. "احنا ساكنين بالسعودية")
    for who, segs in chunks:
        if not (router.route(" ".join(segs)).get("services")) and who in (None, "المستخدم نفسه"):
            bf = factsmod.extract(" ".join(segs))
            if "abroad" in bf:
                background["abroad"] = bf["abroad"]
    for who, segs in chunks:
        seg_routes = [(s, router.route(s).get("services") or []) for s in segs]
        chunk_services = [x for x in (router.route(" ".join(segs)).get("services") or []) if x in services]
        for sid in chunk_services:
            mine = [s for s, r in seg_routes if sid in r]
            shared = [s for s, r in seg_routes if not r]
            f = factsmod.extract(" ".join(mine + shared) if mine else " ".join(segs))
            for k, v in background.items():
                f.setdefault(k, v)
            out.append(compute(sid, f, kb, who=who))
    covered = set(c.service for c in out)
    for sid in services:
        if sid not in covered:
            out.append(compute(sid, factsmod.extract(question), kb))
    return out


# ----------------------------------------------------------------------------- prompt text
def render(case_list, kb):
    lines = []
    for c in case_list:
        if not (c.apply or c.conditional):
            continue
        head = "• [%s]" % kb[c.service]["title_raw"]
        if c.who:
            head += " الشخص: %s" % c.who
        if c.situation:
            head += " — حالته: %s" % "، ".join(c.situation)
        lines.append(head)
        for it in c.apply:
            lines.append("   ينطبق: «%s»" % it)
        if c.total:
            lines.append("   المجموع: %s = %d دينار" % c.total)
        for it, why in c.not_apply:
            lines.append("   لا ينطبق: «%s» %s" % (it, why))
        for cond, it in c.conditional:
            lines.append("   غير معروف من كلام المستخدم — %s: «%s»" % (cond, it))
    return "\n".join(lines)
