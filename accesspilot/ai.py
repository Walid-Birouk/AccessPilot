"""Optional: have an LLM rewrite fix instructions for the exact code found.

The deterministic plan already says what to fix for each rule. With ``--ai``, an
LLM sees each fix's rule and a few failing HTML snippets and writes instructions
specific to that markup. Its output goes through the claim guard; any fix whose
rewrite fails (compliance claim, rate, evidence ID not in that fix) keeps its
deterministic text. The LLM can improve wording, never change what was found.

Works with any OpenAI-compatible chat-completions endpoint:
  ACCESSPILOT_LLM_API_KEY   required
  ACCESSPILOT_LLM_MODEL     required, e.g. gpt-4.1-mini, mistral-small-latest
  ACCESSPILOT_LLM_BASE_URL  default https://api.openai.com/v1
What is sent: rule ids, template names, CSS selectors and HTML excerpts of the
public pages scanned. Nothing else.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from typing import Any

import httpx

from .guard import check_text
from .plan import Fix

SYSTEM = """\
Tu es expert en accessibilité web (RGAA, WCAG 2.1 AA) et tu écris pour le développeur
ou l'agence qui maintient le thème d'une boutique en ligne.

Pour chaque correction fournie, réécris le champ "instructions" en 2 à 4 phrases, en
français, concrètes et spécifiques au code HTML montré : quel élément modifier, quel
attribut ajouter ou changer, avec un exemple de code corrigé court si utile.

Interdits : affirmer une conformité ou un niveau de conformité, donner un pourcentage,
inventer des éléments absents de l'entrée, citer un identifiant de preuve qui n'est pas
dans la correction concernée.

Réponds UNIQUEMENT avec ce JSON :
{"fixes": [{"priority": <entier repris de l'entrée>, "instructions": "...",
            "evidence_ids": ["<repris de l'entrée>"]}]}
"""

MAX_FIXES = 30
BATCH = 10


class AIError(RuntimeError):
    pass


def llm_from_env() -> Callable[[str, str], str]:
    key = os.environ.get("ACCESSPILOT_LLM_API_KEY")
    model = os.environ.get("ACCESSPILOT_LLM_MODEL")
    base = os.environ.get("ACCESSPILOT_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    if not key or not model:
        raise AIError("--ai needs ACCESSPILOT_LLM_API_KEY and ACCESSPILOT_LLM_MODEL "
                      "(and ACCESSPILOT_LLM_BASE_URL for a provider other than OpenAI)")

    def call(system: str, user: str) -> str:
        delay = 2.0
        for _ in range(4):
            try:
                r = httpx.post(f"{base}/chat/completions", timeout=120,
                               headers={"Authorization": f"Bearer {key}"},
                               json={"model": model, "temperature": 0,
                                     "messages": [{"role": "system", "content": system},
                                                  {"role": "user", "content": user}]})
            except httpx.TransportError:
                time.sleep(delay)
                delay *= 2
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(delay)
                delay *= 2
                continue
            if r.status_code >= 400:
                raise AIError(f"LLM endpoint returned HTTP {r.status_code}: {r.text[:200]}")
            return r.json()["choices"][0]["message"]["content"] or ""
        raise AIError("LLM endpoint unavailable after retries")

    return call


def _parse(text: str) -> Any:
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    try:
        return json.loads(m.group(1) if m else text)
    except json.JSONDecodeError as e:
        raise AIError(f"LLM reply is not JSON: {e}") from e


def enrich(plan: list[Fix], call: Callable[[str, str], str],
           log: Callable[[str], None] = print) -> tuple[int, list[str]]:
    """Rewrite instructions in place. Returns (fixes rewritten, rejection reasons)."""
    targets = plan[:MAX_FIXES]
    by_priority = {fx.priority: fx for fx in targets}
    rewritten, rejected = 0, []
    for i in range(0, len(targets), BATCH):
        chunk = targets[i:i + BATCH]
        payload = [{"priority": fx.priority, "template": fx.template, "rule": fx.rule,
                    "title": fx.title, "current_instructions": fx.instructions,
                    "samples": [{"selector": fx.sample_selector, "html": fx.sample_html}],
                    "evidence_ids": fx.evidence_ids[:5]} for fx in chunk]
        try:
            reply = _parse(call(SYSTEM, json.dumps({"fixes": payload}, ensure_ascii=False)))
        except AIError as e:
            rejected.append(f"batch {i // BATCH + 1}: {e}")
            continue
        for item in (reply.get("fixes") if isinstance(reply, dict) else None) or []:
            fx = by_priority.get(item.get("priority")) if isinstance(item, dict) else None
            if fx is None or fx not in chunk:
                continue
            text = str(item.get("instructions") or "").strip()
            verdict = check_text(text, valid_ids=set(fx.evidence_ids),
                                 cited_ids=[str(e) for e in item.get("evidence_ids") or []])
            if not text or not verdict.ok:
                rejected.append(f"fix {fx.priority}: " + ("; ".join(verdict.reasons) or "empty"))
                continue
            fx.instructions = text
            fx.source = "ai"
            fx.notes.append("Instructions rédigées par IA à partir du code relevé : à relire.")
            rewritten += 1
    log(f"  AI rewrote {rewritten} of {len(targets)} fix instructions"
        + (f"; kept the deterministic text for {len(rejected)}" if rejected else ""))
    return rewritten, rejected
