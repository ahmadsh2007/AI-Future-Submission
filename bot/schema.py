"""Shared contract for every module of the chatbot. Do not rename keys.

Pipeline:
    kb.load_kb()  -> SERVICES data (cleaned, structured)
    router.route(question, history) -> which services / fields
    answer.answer(question, history, kb) -> {"answer", "contexts"} via Ollama
    main.py -> reads questions.json, writes answers.json
"""

# Service id == file name in data/ (without .txt).
DOCS = {
    "passport": "جواز السفر",
    "family_book": "دفتر العائلة",
    "id_card": "البطاقة الذكية",
}

SITUATIONS = {
    "first_issue": "لأول مرة",
    "renewal": "تجديد",
    "lost": "بدل فاقد",
    "damaged": "بدل تالف",
}

# service_id -> (doc, situation, Arabic display name used in context strings)
SERVICES = {
    "passport_first_issue": ("passport", "first_issue", "جواز سفر لأول مرة"),
    "passport_renewal": ("passport", "renewal", "تجديد جواز السفر"),
    "passport_lost": ("passport", "lost", "جواز سفر بدل فاقد"),
    "passport_damaged": ("passport", "damaged", "جواز سفر بدل تالف"),
    "family_book_first_issue": ("family_book", "first_issue", "دفتر عائلة لأول مرة"),
    "family_book_renewal": ("family_book", "renewal", "تجديد دفتر العائلة"),
    "family_book_lost": ("family_book", "lost", "دفتر عائلة بدل فاقد"),
    "family_book_damaged": ("family_book", "damaged", "دفتر عائلة بدل تالف"),
    "id_card_first_issue": ("id_card", "first_issue", "بطاقة ذكية لأول مرة"),
    "id_card_renewal": ("id_card", "renewal", "تجديد البطاقة الذكية"),
    "id_card_lost": ("id_card", "lost", "بطاقة ذكية بدل فاقد"),
    "id_card_damaged": ("id_card", "damaged", "بطاقة ذكية بدل تالف"),
}


def service_id(doc, situation):
    return "%s_%s" % (doc, situation)


# Field key -> Arabic label used in context strings. Order = order in the files.
FIELDS = [
    ("beneficiaries", "الفئة المستفيدة"),
    ("locations", "أماكن تقديم الخدمة"),
    ("conditions", "شروط تقديم الخدمة"),
    ("documents", "الوثائق المطلوبة"),
    ("procedure", "إجراءات تقديم الخدمة"),
    ("time", "الزمن المستغرق لتقديم الخدمة"),
    ("partners", "شركاء الخدمة"),
    ("notes", "ملاحظات"),
    ("fees", "الرسوم"),
]
FIELD_KEYS = [k for k, _ in FIELDS]
FIELD_LABELS = dict(FIELDS)

# Router statuses
STATUS_OK = "ok"
STATUS_UNCLEAR = "unclear"          # ask the user what they mean
STATUS_OUT_OF_SCOPE = "out_of_scope"  # not covered by the 12 files
