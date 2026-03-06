"""Toutes les interactions Groq centralisees ici. Jamais ailleurs."""

import asyncio
import hashlib
import json
import logging
import os
import random
import time

import httpx

from backend.models import IgAccount, Niche, Prospect

logger = logging.getLogger("instafarm.groq")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_TIMEOUT = 10  # secondes
GROQ_MAX_RETRIES = 3
GROQ_CACHE_TTL = 3600  # 1h

# Cache simple en memoire pour les appels identiques (scoring)
_groq_cache: dict[str, tuple[float, str]] = {}


def _get_groq_config() -> tuple[str, str, str]:
    """Retourne (api_key, model, fallback_model)."""
    return (
        os.getenv("GROQ_API_KEY", ""),
        os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        os.getenv("GROQ_FALLBACK_MODEL", "llama-3.1-8b-instant"),
    )


def _cache_key(prompt: str) -> str:
    return hashlib.md5(prompt.encode()).hexdigest()[:16]


async def call_groq(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 256,
    timeout: float = GROQ_TIMEOUT,
    use_cache: bool = False,
) -> str:
    """
    Appel Groq avec :
    - Retry x3 avec backoff exponentiel
    - Fallback sur modele plus petit si le grand est down
    - Gestion 429 (rate limit) et 5xx (erreur serveur)
    - Cache optionnel (pour scoring)
    - Timeout 10s par tentative
    """
    # Check cache
    if use_cache:
        ck = _cache_key(system_prompt + user_prompt)
        if ck in _groq_cache:
            cached_time, cached_val = _groq_cache[ck]
            if time.time() - cached_time < GROQ_CACHE_TTL:
                return cached_val

    api_key, default_model, fallback_model = _get_groq_config()
    if not api_key:
        raise ValueError("GROQ_API_KEY non defini dans .env")

    target_model = model or default_model
    models_to_try = [target_model, fallback_model]

    for m in models_to_try:
        for attempt in range(GROQ_MAX_RETRIES):
            try:
                result = await _do_call(m, system_prompt, user_prompt, temperature, max_tokens, api_key, timeout)

                # Cache le resultat
                if use_cache:
                    _groq_cache[_cache_key(system_prompt + user_prompt)] = (time.time(), result)

                return result

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning(f"Groq rate limit, attente {wait}s (tentative {attempt+1}/{GROQ_MAX_RETRIES})")
                    await asyncio.sleep(wait)
                elif e.response.status_code >= 500:
                    wait = 2 ** attempt
                    logger.warning(f"Groq erreur {e.response.status_code}, retry dans {wait}s")
                    await asyncio.sleep(wait)
                else:
                    logger.error(f"Groq erreur {e.response.status_code}: {e.response.text[:100]}")
                    break

            except (asyncio.TimeoutError, httpx.TimeoutException):
                logger.warning(f"Groq timeout (tentative {attempt+1}/{GROQ_MAX_RETRIES}, modele: {m})")

            except Exception as e:
                logger.error(f"Groq exception: {e}")
                break

    raise RuntimeError("Groq completement indisponible apres toutes les tentatives")


async def _do_call(
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    api_key: str,
    timeout: float = GROQ_TIMEOUT,
) -> str:
    """Appel HTTP brut vers Groq."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(GROQ_API_URL, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

    return data["choices"][0]["message"]["content"].strip()


async def score_bio_with_groq(bio: str, niche_name: str, product_pitch: str) -> float:
    """Scoring Groq d'une bio Instagram. Retourne float 0.0-1.0."""
    system_prompt = (
        "Tu es un expert en qualification de prospects B2B sur Instagram.\n"
        "Tu dois evaluer si un compte Instagram est un professionnel de la niche donnee.\n"
        "Reponds UNIQUEMENT avec un nombre entre 0 et 10. Rien d'autre."
    )
    user_prompt = (
        f"Sur une echelle de 0 a 10, ce compte Instagram est-il un {niche_name} "
        f"qui pourrait avoir besoin de {product_pitch} ?\n"
        f"Bio : {bio}\n"
        f"Reponds UNIQUEMENT avec un nombre entre 0 et 10."
    )
    response = await call_groq(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.1,
        max_tokens=10,
    )
    return _parse_score(response)


def _parse_score(response: str) -> float:
    """Parse la reponse Groq en float 0.0-1.0."""
    cleaned = ""
    for char in response:
        if char.isdigit() or char == ".":
            cleaned += char
    if not cleaned:
        return 0.5
    try:
        score = float(cleaned)
        if score > 1.0:
            score = score / 10.0
        return max(0.0, min(1.0, score))
    except ValueError:
        return 0.5


# ============================================================
# SESSION 4 — GroqService class (DMs, relances, playbook)
# ============================================================

class GroqService:
    """Toutes les interactions Groq centralisees. Jamais ailleurs."""

    async def generate_dm(self, prospect: Prospect, niche: Niche, account: IgAccount) -> str:
        """
        Genere un DM ultra-personnalise.
        Fallback si Groq fail : random template.
        """
        fallback_templates = self._parse_templates(niche.dm_fallback_templates)

        try:
            user_prompt = (
                f"Genere un DM pour ce compte Instagram :\n"
                f"Username: @{prospect.username}\n"
                f"Nom: {prospect.full_name or 'Non renseigne'}\n"
                f"Bio: {prospect.bio or 'Pas de bio'}\n"
                f"Followers: {prospect.followers}\n"
                f"Ville detectee: {prospect.city or 'Non detectee'}\n\n"
                f"DM en francais. Maximum 3 phrases. Personnalise."
            )
            return await call_groq(
                system_prompt=niche.dm_prompt_system,
                user_prompt=user_prompt,
                max_tokens=200,
                temperature=0.85,
            )
        except Exception:
            return random.choice(fallback_templates) if fallback_templates else "Bonjour !"

    async def generate_relance(self, prospect: Prospect, niche: Niche, relance_number: int) -> str:
        """Genere une relance (D+7, D+14, D+21)."""
        relance_prompts = {
            1: "Genere une relance douce (D+7). Rappelle subtilement ton premier message sans repeter le meme contenu. 2 phrases max. Ton : leger et amical.",
            2: "Genere une deuxieme relance (D+14). Change d'angle, propose une valeur ajoutee concrete (stat, temoignage client). 2 phrases max.",
            3: "Genere une derniere relance (D+21). Dernier essai, propose directement un appel de 10min. Si pas de reponse, on arrete. 2 phrases max. Ton : respectueux.",
        }
        fallback_relances = {
            1: "Je me permets de revenir vers vous — avez-vous eu le temps de reflechir a notre echange ?",
            2: "Petit retour : nos clients dans votre secteur voient des resultats en 3 semaines. Ca vous tente d'en discuter ?",
            3: "Derniere relance de ma part ! Un appel de 10 min pour vous montrer ce qu'on fait, ca vous dit ?",
        }

        try:
            system_prompt = (
                f"Tu es un expert en prospection B2B pour la niche {niche.name}.\n"
                f"Tu generes des messages de relance Instagram.\n"
                f"Produit : {niche.product_pitch}\n"
                f"IMPORTANT : Ne repete JAMAIS le premier message. Apporte un angle nouveau."
            )
            user_prompt = (
                f"Prospect : @{prospect.username} ({prospect.full_name or 'inconnu'})\n"
                f"Bio : {prospect.bio or 'Pas de bio'}\n"
                f"Relance numero : {relance_number}\n\n"
                f"{relance_prompts.get(relance_number, relance_prompts[1])}"
            )
            return await call_groq(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=150,
                temperature=0.8,
            )
        except Exception:
            return fallback_relances.get(relance_number, fallback_relances[1])

    async def score_prospect_bio(self, bio: str, niche_name: str, product_pitch: str) -> float:
        """Score 0-10 normalise 0.0-1.0. Delegue a score_bio_with_groq."""
        return await score_bio_with_groq(bio, niche_name, product_pitch)

    async def generate_playbook_response(
        self,
        objection: str,
        niche: Niche,
        conversation_history: list[dict],
    ) -> str:
        """Repond a une objection courante avec le contexte de la conversation."""
        try:
            history_text = "\n".join(
                f"{'Nous' if m.get('direction') == 'outbound' else 'Prospect'}: {m.get('content', '')}"
                for m in conversation_history[-5:]
            )
            system_prompt = (
                f"Tu es un expert commercial dans la niche {niche.name}.\n"
                f"Produit : {niche.product_pitch}\n"
                f"Tu dois repondre a une objection de maniere empathique et persuasive.\n"
                f"Maximum 3 phrases. Jamais agressif."
            )
            user_prompt = (
                f"Historique conversation :\n{history_text}\n\n"
                f"Objection du prospect : {objection}\n\n"
                f"Genere une reponse adaptee :"
            )
            return await call_groq(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=200,
                temperature=0.7,
            )
        except Exception:
            return "Je comprends tout a fait votre hesitation. Si vous le souhaitez, je peux vous montrer en 10 minutes comment ca fonctionne concretement ?"

    async def suggest_response(self, prospect: Prospect, niche: Niche, last_message: str) -> str:
        """Suggestion de reponse pour l'humain dans la PWA."""
        try:
            system_prompt = (
                f"Tu es un assistant commercial pour la niche {niche.name}.\n"
                f"Produit : {niche.product_pitch}\n"
                f"Genere une suggestion de reponse professionnelle et naturelle.\n"
                f"Maximum 3 phrases."
            )
            user_prompt = (
                f"Prospect : @{prospect.username}\n"
                f"Dernier message recu : {last_message}\n\n"
                f"Suggestion de reponse :"
            )
            return await call_groq(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=200,
                temperature=0.7,
            )
        except Exception:
            return "Merci pour votre retour ! Est-ce qu'un appel de 15min cette semaine vous conviendrait pour en discuter ?"

    @staticmethod
    def _parse_templates(templates_json: str) -> list[str]:
        """Parse les fallback templates depuis JSON."""
        try:
            templates = json.loads(templates_json)
            return templates if isinstance(templates, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
