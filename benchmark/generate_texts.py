"""Ask models for the reports: each data set, as a team would hand it over, without the package.

The model gets the brief and the data the way describe() writes them, and is
asked for a short report in prose. Half the data sets go with a strict prompt
(use only the data), half with a plain one, so the evaluation sees both how a
careful team asks and how most people ask. Which one each text got is recorded.

    python -m benchmark.generate_texts --list-models
    python -m benchmark.generate_texts --split pilot --model groq:llama-3.1-8b-instant --model groq:openai/gpt-oss-120b

Keys come from the environment, or from .tmp/eval.env (GROQ_API_KEY=...), which
git ignores; they are never printed. A text already written is kept, so a run
cut by a rate limit picks up where it stopped. Each text goes to
benchmark/texts/<split>/<model>/<data set>.json with the prompt, the reply,
the model that served it and its token use.
"""

import argparse
import json
import os
import re
import sys
import time
import zlib
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .make_datasets import describe, load_datasets

HERE = Path(__file__).resolve().parent
TEXTS = HERE / "texts"
ENV_FILE = HERE.parent / ".tmp" / "eval.env"
PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "ollama": ("http://localhost:11434/v1", ""),
}
VARIANTS = ("strict", "plain")
MAX_TOKENS = 4096  # reasoning models spend part of it before the report
ATTEMPTS = 6

SYSTEM = {
    "es": "Eres un analista que redacta informes claros y breves para empresas.",
    "en": "You are an analyst who writes clear, concise business reports.",
}
ASK = {
    "es": "Escribe un informe de {low} a {high} oraciones para {audience} de {company} sobre {topic} en {period}, "
    "a partir de estos datos.",
    "en": "Write a report of {low} to {high} sentences for {audience} at {company} on {topic} for {period}, "
    "based on this data.",
}
STRICT = {
    "es": "Usa solo la información de los datos: no agregues cifras, nombres, causas ni predicciones que no estén ahí.",
    "en": "Use only the information in the data: do not add figures, names, causes or predictions that are not there.",
}
FORMAT = {
    "es": "Escribe solo el informe, en prosa, sin títulos ni listas.",
    "en": "Write only the report, in prose, with no headings or lists.",
}
_THINKING = re.compile(r"<think>.*?</think>", re.DOTALL)


def variant(dataset_id: str, model: str) -> str:
    """strict or plain: half the data sets each, and a different half for each model."""
    number = int(re.sub(r"\D", "", dataset_id) or 0)
    return VARIANTS[(number + zlib.crc32(model.encode("utf-8"))) % 2]


def prompt(dataset: Mapping[str, object], which: str) -> tuple[str, str]:
    """The system prompt and the request for one data set."""
    locale = str(dataset["locale"])
    brief = dataset["brief"]
    if not isinstance(brief, dict):
        raise TypeError("the data set has no brief")
    low, high = brief["sentences"] if isinstance(brief["sentences"], list) else (5, 8)
    ask = ASK[locale].format(low=low, high=high, audience=brief["audience"], company=brief["company"],
                             topic=brief["topic"], period=brief["period"])
    parts = [ask, describe(dataset)]
    rules = ([STRICT[locale]] if which == "strict" else []) + [FORMAT[locale]]
    return SYSTEM[locale], "\n\n".join(parts + [" ".join(rules)])


def load_keys(path: Path = ENV_FILE) -> None:
    """KEY=value lines from the env file into the environment, without overriding what is set."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and name and not name.startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def _endpoint(model: str) -> tuple[str, str, dict[str, str]]:
    provider, _, name = model.partition(":")
    if provider not in PROVIDERS or not name:
        raise SystemExit(f"name the model as provider:model, with provider one of {', '.join(PROVIDERS)}: {model}")
    base, key_name = PROVIDERS[provider]
    headers: dict[str, str] = {}
    if key_name:
        key = os.environ.get(key_name, "")
        if not key:
            raise SystemExit(f"{provider} needs a key: put {key_name}=... in {ENV_FILE} or the environment")
        headers["Authorization"] = f"Bearer {key}"
    return base, name, headers


def chat(model: str, system: str, user: str, client: httpx.Client) -> dict[str, object]:
    """One request, retried on a rate limit or a server error. Returns the reply and what came with it."""
    base, name, headers = _endpoint(model)
    body = {"model": name, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_completion_tokens": MAX_TOKENS}
    for attempt in range(1, ATTEMPTS + 1):
        started = time.monotonic()
        try:
            response = client.post(f"{base}/chat/completions", json=body, headers=headers)
        except httpx.HTTPError as exc:
            if attempt == ATTEMPTS:
                raise SystemExit(f"could not reach {base}: {exc}") from exc
            time.sleep(5 * attempt)
            continue
        seconds = round(time.monotonic() - started, 2)
        if response.status_code == 429 or response.status_code >= 500:
            wait = _retry_after(response) or 10.0 * attempt
            print(f"  {response.status_code}, waiting {wait:.0f} s", file=sys.stderr)
            time.sleep(min(wait, 120))
            continue
        payload: object = response.json() if response.content else {}
        if not response.is_success or not isinstance(payload, dict):
            raise SystemExit(f"{model} answered {response.status_code}: {response.text[:300]}")
        choices = payload.get("choices")
        choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
        message = choice.get("message") if isinstance(choice, dict) else None
        raw = message.get("content") if isinstance(message, dict) else None
        raw_text = raw if isinstance(raw, str) else ""
        return {
            "raw": raw_text,
            "text": _THINKING.sub("", raw_text).strip(),
            "finish_reason": choice.get("finish_reason") if isinstance(choice, dict) else None,
            "served_by": payload.get("model"),
            "usage": payload.get("usage"),
            "seconds": seconds,
        }
    raise SystemExit(f"{model} kept refusing after {ATTEMPTS} attempts")


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after", "")
    try:
        return float(value) + 1
    except ValueError:
        return None


def slug(model: str) -> str:
    """A folder name for a model: groq:openai/gpt-oss-120b -> groq_openai_gpt-oss-120b."""
    return re.sub(r"[^A-Za-z0-9.-]+", "_", model)


def text_path(split: str, model: str, dataset_id: str) -> Path:
    return TEXTS / split / slug(model) / f"{dataset_id}.json"


def list_models() -> int:
    _, _, headers = _endpoint("groq:any")
    response = httpx.get(f"{PROVIDERS['groq'][0]}/models", headers=headers, timeout=30)
    payload: object = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    for item in sorted((m for m in data or [] if isinstance(m, dict)), key=lambda m: str(m.get("id"))):
        print(f"groq:{item.get('id')}  (context {item.get('context_window')}, owner {item.get('owned_by')})")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", choices=("pilot", "main"), default="pilot")
    parser.add_argument("--model", action="append", default=[], help="provider:model, as many as wanted")
    parser.add_argument("--only", nargs="*", default=[], help="data set ids, to run a few")
    parser.add_argument("--list-models", action="store_true", help="the models Groq serves now")
    args = parser.parse_args(argv)
    load_keys()
    if args.list_models:
        return list_models()
    if not args.model:
        parser.error("name at least one --model")
    datasets = [d for d in load_datasets(args.split) if not args.only or d["id"] in args.only]
    written = kept = 0
    with httpx.Client(timeout=180) as client:
        for model in args.model:
            for dataset in datasets:
                ident = str(dataset["id"])
                path = text_path(args.split, model, ident)
                if path.exists():
                    kept += 1
                    continue
                which = variant(ident, model)
                system, user = prompt(dataset, which)
                reply = chat(model, system, user, client)
                if reply["finish_reason"] == "length" or not reply["text"]:
                    print(f"{model} {ident}: cut off or empty, not saved", file=sys.stderr)
                    continue
                record = {"dataset": ident, "split": dataset["split"], "model": model, "variant": which,
                          "system": system, "prompt": user, **reply,
                          "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                written += 1
                print(f"{model} {ident} ({which}): {len(str(reply['text']))} characters in {reply['seconds']} s")
    print(f"written: {written}, already there: {kept}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
