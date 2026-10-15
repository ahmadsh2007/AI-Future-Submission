"""Entry point: python main.py questions.json  ->  answers.json (same folder as questions.json).

Options (all optional):
  --out PATH     write answers to PATH instead
  --debug        add a "debug" key per message (route, checks); the scorer ignores extra keys
  --dry-run      do not call Ollama (extractive answers) - only for testing the pipeline
"""
import argparse
import copy
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from bot.answer import Bot  # noqa: E402
from bot.llm import LLM, load_config  # noqa: E402


def log(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("questions", nargs="?", default="questions.json")
    ap.add_argument("--out", default=None)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    qpath = os.path.abspath(args.questions)
    out_path = os.path.abspath(args.out) if args.out else os.path.join(os.path.dirname(qpath), "answers.json")

    with open(qpath, encoding="utf-8-sig") as f:
        data = json.load(f)
    result = copy.deepcopy(data)
    chats = result.get("chats") if isinstance(result, dict) else None
    if not isinstance(chats, list):
        chats = []

    # Pre-fill every message so a crash still leaves a complete, valid file.
    total = 0
    for chat in chats:
        for msg in (chat.get("messages") or []) if isinstance(chat, dict) else []:
            if isinstance(msg, dict):
                msg["answer"] = "error"
                msg["contexts"] = []
                total += 1
    write_json(out_path, result)

    llm = None
    if not args.dry_run:
        llm = LLM(load_config())
        model, status = llm.resolve_model()
        log("model: %s (%s)" % (model, status))
        if status.startswith(("ollama not reachable", "no models", "configured model")):
            log("WARNING: Ollama / the configured model is not usable - falling back to extractive answers. "
                "Start Ollama (ollama serve) and run: ollama pull command-r7b-arabic:7b")
            llm = None
        else:
            try:  # warm-up: load the model into memory once
                llm.chat("أجب بكلمة واحدة.", "مرحبا", num_predict=5)
            except Exception as e:  # noqa: BLE001
                log("WARNING: warm-up failed: %s" % e)
    bot = Bot(llm=llm)

    t0 = time.time()
    done = 0
    for chat in chats:
        if not isinstance(chat, dict):
            continue
        history = []  # every chat is a new user
        for msg in chat.get("messages") or []:
            if not isinstance(msg, dict):
                continue
            q = msg.get("question")
            q = q if isinstance(q, str) else ("" if q is None else str(q))
            t1 = time.time()
            try:
                ans, ctx, dbg = bot.answer(q, history)
            except Exception:  # noqa: BLE001 - one bad message must not stop the run
                ans, ctx, dbg = "error", [], {"exception": traceback.format_exc(limit=3)}
                log(traceback.format_exc())
            msg["answer"] = ans if isinstance(ans, str) and ans.strip() else "error"
            msg["contexts"] = [c for c in (ctx or []) if isinstance(c, str)]
            if args.debug:
                dbg["seconds"] = round(time.time() - t1, 2)
                msg["debug"] = dbg
            history.append({"question": q, "route": (dbg.get("route") or {}), "answer": msg["answer"]})
            done += 1
            log("[%d/%d] %s  %.1fs" % (done, total, msg.get("message_id", "?"), time.time() - t1))
        write_json(out_path, result)  # save progress after every chat

    write_json(out_path, result)
    log("wrote %s (%d messages, %.1fs)" % (out_path, done, time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
