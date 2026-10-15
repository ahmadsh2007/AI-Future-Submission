# Government Services Chatbot (Jordan: passport, family book, smart ID)

42 Irbid · AI Future 26 · Youth Edition. Answers questions only from the 12 official service files in `data/`,
using only the provided model `command-r7b-arabic:7b` through Ollama.

## Run (exact command)

Requirements: Python 3.9+ (standard library only, **no pip install and no virtual environment needed**) and Ollama running locally with the model pulled.

```bash
ollama pull command-r7b-arabic:7b      # once, while online
python3 main.py questions.json         # writes answers.json next to questions.json (use `python` if that is your Python 3)
```

Offline: the program only talks to local Ollama (127.0.0.1:11434). Optional: `python3 check_setup.py` checks Python, Ollama, the model and the data files.

## How it works

1. **Data** (`bot/kb.py`): the 12 files are parsed into the same 9 fields (who, where, conditions, documents, procedure, time, partners, notes, fees). Website menus, tabs and duplicates are removed, typos fixed, number words get their digits added. A check confirms no raw number or word was lost; every change is listed in `kb/cleaning_log.txt`.
2. **Finding the right service** (`bot/router.py`): code, not the model, picks the document (passport / family book / smart ID) and the situation (first time / renewal / lost / damaged), including Jordanian dialect, comparisons, long stories and follow-ups. Unclear questions get a clarifying question; topics that are not in the files are declined.
3. **The user's situation** (`bot/facts.py`, `bot/fees.py`): age, days left on the passport, inside/outside Jordan, number of losses, urgent office, etc. are read from the question and matched to the fee lines in the data, so the 7B model copies the right line instead of comparing numbers itself.
4. **Answering** (`bot/answer.py`): the model sees only the relevant fields of the chosen service(s) and writes the answer. Every number in the answer must come from the sources, the question or a sum of two source amounts, otherwise the model is asked once more. If the sources do not contain the answer the model says so (declines and clarifying questions are written by the model too).
5. **Contexts**: only the data items actually used, in the form `<service title> - <field>: <text>`.
6. **Robustness**: one try/except per message, every message gets an answer, `answers.json` is saved after every chat, UTF-8 everywhere. If Ollama or the model is missing the program warns and never switches to another model.

## Rules
Only the provided files are the knowledge source; answers are generated at run time by the provided model; no other AI model or online service; nothing is downloaded at run time.

Our own 90-question dev set (not shipped here) scored 83.3 overall on this model with the previous version of the code.
