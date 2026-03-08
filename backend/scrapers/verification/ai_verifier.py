"""
AIVerifier — Verification IA double couche (texte + vision) des profils Instagram.
Utilise Groq pour valider qu'un compte est un vrai professionnel de la niche ciblee.
"""

import asyncio
import base64
import json
import logging

import httpx

from backend.services.groq_service import call_groq

logger = logging.getLogger("instafarm.ai_verifier")

# Modele vision Groq
VISION_MODEL = "llava-v1.5-7b-4096-preview"


class AIVerifier:
    """
    Verification IA en 2 couches :
    1. Analyse textuelle (bio, followers, activite)
    2. Analyse visuelle (photo de profil)

    Score final = (text * 0.6) + (visual * 0.4)
    Seuil de validation : score > 0.65 ET text is_valid = True
    """

    async def verify_text(
        self,
        account_data: dict,
        target_niche: str,
        city: str = "",
    ) -> dict:
        """
        Analyse textuelle du profil Instagram.

        Args:
            account_data: {username, bio, followers, is_business, last_post_caption, ...}
            target_niche: niche ciblee (ex: "restaurant")
            city: ville attendue

        Returns:
            {is_valid, confidence, reason, red_flags, dm_approach}
        """
        username = account_data.get("username", "?")
        bio = account_data.get("bio", "")
        followers = account_data.get("followers", 0)
        is_business = account_data.get("is_business", False)
        last_caption = account_data.get("last_post_caption", "")

        system_prompt = (
            "Tu es un expert en qualification de prospects B2B sur Instagram.\n"
            "Tu dois determiner si un compte Instagram est un VRAI professionnel "
            f"de la niche '{target_niche}'.\n\n"
            "Reponds UNIQUEMENT en JSON valide avec cette structure :\n"
            '{"is_valid": true/false, "confidence": 0.0-1.0, "reason": "...", '
            '"red_flags": ["..."], "dm_approach": "..."}\n\n'
            "Criteres :\n"
            "- is_valid = true si c'est un VRAI etablissement/professionnel, pas un influenceur/particulier\n"
            "- confidence = ta certitude (0.0 = incertain, 1.0 = certain)\n"
            "- red_flags = signaux suspects (bot, faux compte, hors niche, etc.)\n"
            "- dm_approach = suggestion courte pour personnaliser le premier DM"
        )

        user_prompt = (
            f"Niche ciblee : {target_niche}\n"
            f"Ville attendue : {city or 'non specifiee'}\n\n"
            f"Compte a analyser :\n"
            f"- Username : @{username}\n"
            f"- Bio : {bio or '(vide)'}\n"
            f"- Followers : {followers}\n"
            f"- Compte business : {'oui' if is_business else 'non'}\n"
            f"- Derniere publication : {last_caption[:200] if last_caption else '(inconnu)'}\n\n"
            f"Ce compte est-il un vrai {target_niche} professionnel ?"
        )

        try:
            response = await call_groq(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,
                max_tokens=300,
                timeout=12,
            )
            return self._parse_text_response(response)

        except Exception as e:
            logger.warning(f"Verify text echoue pour @{username}: {e}")
            return {
                "is_valid": True,  # En cas de doute, on laisse passer
                "confidence": 0.5,
                "reason": "Verification IA indisponible",
                "red_flags": [],
                "dm_approach": "Approche generique",
            }

    async def verify_visual(self, profile_pic_url: str) -> dict:
        """
        Analyse visuelle de la photo de profil via Groq Vision.

        Args:
            profile_pic_url: URL de la photo de profil

        Returns:
            {is_business_visual, visual_confidence, what_i_see}
        """
        if not profile_pic_url:
            return {
                "is_business_visual": False,
                "visual_confidence": 0.3,
                "what_i_see": "Pas de photo de profil",
            }

        try:
            # Telecharger l'image
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(profile_pic_url)
                if resp.status_code != 200:
                    return {
                        "is_business_visual": False,
                        "visual_confidence": 0.3,
                        "what_i_see": "Image inaccessible",
                    }

                image_data = base64.b64encode(resp.content).decode("utf-8")
                content_type = resp.headers.get("content-type", "image/jpeg")

            # Appel Groq Vision
            system_prompt = (
                "Tu analyses des photos de profil Instagram pour determiner "
                "si c'est un etablissement professionnel.\n"
                "Reponds UNIQUEMENT en JSON :\n"
                '{"is_business_visual": true/false, "visual_confidence": 0.0-1.0, '
                '"what_i_see": "description courte"}'
            )

            user_prompt = (
                "Cette photo de profil Instagram montre-t-elle un etablissement "
                "professionnel (logo, devanture, equipe, produits) ou un particulier ?"
            )

            # Pour le modele vision, on construit le payload manuellement
            api_key = _get_groq_key()
            if not api_key:
                raise ValueError("GROQ_API_KEY non defini")

            payload = {
                "model": VISION_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{content_type};base64,{image_data}",
                                },
                            },
                        ],
                    },
                ],
                "temperature": 0.1,
                "max_tokens": 150,
            }

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                response_text = data["choices"][0]["message"]["content"].strip()

            return self._parse_visual_response(response_text)

        except Exception as e:
            logger.warning(f"Verify visual echoue: {e}")
            return {
                "is_business_visual": True,  # Doute = on laisse passer
                "visual_confidence": 0.4,
                "what_i_see": f"Analyse visuelle indisponible: {e}",
            }

    async def verify_full(self, account_data: dict, niche_config: dict) -> dict:
        """
        Verification complete : texte + vision en parallele.
        Score final = (text_confidence * 0.6) + (visual_confidence * 0.4)

        Args:
            account_data: donnees du profil Instagram
            niche_config: config de la niche (name, city, sector, ...)

        Returns:
            {is_valid, score, verdict, dm_approach, text_result, visual_result}
        """
        target_niche = niche_config.get("sector", niche_config.get("name", ""))
        city = niche_config.get("city", "")
        profile_pic = account_data.get("profile_pic_url", "")

        # Lancer texte + vision en parallele
        text_result, visual_result = await asyncio.gather(
            self.verify_text(account_data, target_niche, city),
            self.verify_visual(profile_pic),
        )

        # Score combine
        text_conf = text_result.get("confidence", 0.5)
        visual_conf = visual_result.get("visual_confidence", 0.4)
        score = (text_conf * 0.6) + (visual_conf * 0.4)

        # Verdict
        text_valid = text_result.get("is_valid", False)
        is_valid = score > 0.65 and text_valid

        verdict = "valide" if is_valid else "rejete"
        red_flags = text_result.get("red_flags", [])
        if not visual_result.get("is_business_visual", True):
            red_flags.append("Photo de profil non-professionnelle")

        username = account_data.get("username", "?")
        logger.info(
            f"[@{username}] Verification IA: {verdict} "
            f"(score={score:.2f}, text={text_conf:.2f}, visual={visual_conf:.2f})"
        )

        return {
            "is_valid": is_valid,
            "score": round(score, 3),
            "verdict": verdict,
            "dm_approach": text_result.get("dm_approach", ""),
            "red_flags": red_flags,
            "text_result": text_result,
            "visual_result": visual_result,
        }

    @staticmethod
    def _parse_text_response(response: str) -> dict:
        """Parse la reponse JSON de Groq pour l'analyse textuelle."""
        try:
            # Nettoyer les backticks markdown
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
            cleaned = cleaned.strip()

            data = json.loads(cleaned)
            return {
                "is_valid": bool(data.get("is_valid", False)),
                "confidence": max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
                "reason": str(data.get("reason", "")),
                "red_flags": data.get("red_flags", []),
                "dm_approach": str(data.get("dm_approach", "")),
            }
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.debug(f"Parse text response echoue: {e}, raw={response[:200]}")
            return {
                "is_valid": True,
                "confidence": 0.5,
                "reason": "Reponse IA non parsable",
                "red_flags": [],
                "dm_approach": "Approche generique",
            }

    @staticmethod
    def _parse_visual_response(response: str) -> dict:
        """Parse la reponse JSON de Groq Vision."""
        try:
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
            cleaned = cleaned.strip()

            data = json.loads(cleaned)
            return {
                "is_business_visual": bool(data.get("is_business_visual", False)),
                "visual_confidence": max(0.0, min(1.0, float(data.get("visual_confidence", 0.4)))),
                "what_i_see": str(data.get("what_i_see", "")),
            }
        except (json.JSONDecodeError, ValueError) as e:
            logger.debug(f"Parse visual response echoue: {e}")
            return {
                "is_business_visual": True,
                "visual_confidence": 0.4,
                "what_i_see": "Reponse non parsable",
            }


def _get_groq_key() -> str:
    """Recupere la cle Groq depuis l'environnement."""
    import os

    return os.getenv("GROQ_API_KEY", "")
