"""Minimal Ollama client (stdlib only, works offline against a local Ollama server)."""
import json
import os
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(os.path.dirname(_HERE), "config.json")

DEFAULTS = {
    "model": "command-r7b-arabic:7b",
    "ollama_url": "http://127.0.0.1:11434",
    "num_ctx": 8192,          # Ollama's default window is small; set it explicitly
    "num_predict": 600,
    "temperature": 0.0,
    "seed": 7,
    "timeout_s": 240,
}


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    # Environment overrides (handy if the organisers' model has a different tag)
    if os.environ.get("OLLAMA_MODEL"):
        cfg["model"] = os.environ["OLLAMA_MODEL"]
    if os.environ.get("OLLAMA_HOST"):
        host = os.environ["OLLAMA_HOST"]
        cfg["ollama_url"] = host if host.startswith("http") else "http://" + host
    return cfg


class LLM:
    def __init__(self, cfg=None):
        self.cfg = cfg or load_config()
        self.url = self.cfg["ollama_url"].rstrip("/")
        self.model = self.cfg["model"]

    def _post(self, path, payload, timeout):
        req = urllib.request.Request(
            self.url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def available_models(self):
        try:
            with urllib.request.urlopen(self.url + "/api/tags", timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return [m.get("name", "") for m in data.get("models", [])]
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def resolve_model(self):
        """Use the configured model; if it is not pulled, report it (never silently use a different model)."""
        names = self.available_models()
        if names is None:
            return self.model, "ollama not reachable at %s" % self.url
        if not names:
            return self.model, "no models pulled in ollama"
        want = self.model
        for n in names:
            if n == want or n == want + ":latest" or n.split(":")[0] == want:
                self.model = n
                return n, "ok"
        # Configured model missing: do NOT substitute another model. The rules allow only the provided model to
        # generate answers, so the caller must treat this as "model unusable" (see main.py).
        return want, "configured model %r not found in ollama (no other model is substituted)" % want

    def chat(self, system, user, num_predict=None, temperature=None):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "keep_alive": "30m",
            "options": {
                "temperature": self.cfg["temperature"] if temperature is None else temperature,
                "num_ctx": self.cfg["num_ctx"],
                "num_predict": num_predict or self.cfg["num_predict"],
                "seed": self.cfg["seed"],
            },
        }
        data = self._post("/api/chat", payload, self.cfg["timeout_s"])
        return (data.get("message") or {}).get("content", "").strip()
