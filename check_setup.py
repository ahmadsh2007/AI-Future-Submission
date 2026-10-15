"""Quick setup check:  python3 check_setup.py   (no packages needed)"""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))["model"]
ok = True


def check(name, cond, hint=""):
    global ok
    ok = ok and cond
    print(("[ OK ] " if cond else "[FAIL] ") + name + ("" if cond else "  -> " + hint))


check("Python 3.9+", sys.version_info >= (3, 9), "found %s" % sys.version.split()[0])
data = os.path.join(HERE, "data")
check("12 data files", len([f for f in os.listdir(data) if f.endswith(".txt")]) == 12 if os.path.isdir(data) else False, "data/ must hold the 12 .txt files")
try:
    with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as r:
        names = [m["name"] for m in json.loads(r.read().decode("utf-8")).get("models", [])]
    check("Ollama reachable", True)
    check("model %s pulled" % MODEL, any(n == MODEL or n.split(":")[0] == MODEL for n in names), "run: ollama pull %s" % MODEL)
except Exception as e:  # noqa: BLE001
    check("Ollama reachable", False, "start it with: ollama serve  (%s)" % e)
print("\nAll good." if ok else "\nFix the items marked FAIL.")
sys.exit(0 if ok else 1)
