"""Scoring IA 3 couches : TF-IDF + Groq + Intent signals."""

import json
from datetime import datetime, timedelta

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import select, update

from backend.bot.scraper import InstagramScraper, extract_city
from backend.database import async_session
from backend.models import Niche, Prospect, SystemLog
from backend.services.groq_service import score_bio_with_groq


async def _log(tenant_id: int, level: str, message: str, details: dict | None = None):
    """Log en DB."""
    async with async_session() as session:
        log = SystemLog(
            tenant_id=tenant_id,
            level=level,
            module="scorer",
            message=message,
            details=json.dumps(details or {}, ensure_ascii=False),
        )
        session.add(log)
        await session.commit()


class ProspectScorer:
    """Scoring en 3 couches. Score final = 0.0 a 1.0."""

    def async_init(self):
        pass

    async def score_prospect(self, profile: dict, niche: Niche) -> tuple[float, dict]:
        """
        Retourne (score_final, score_details).
        """
        # Couche 1 : TF-IDF
        tfidf = self._tfidf_score(profile, niche)

        # Si TF-IDF < 0.2 → rejet immediat (mauvaise niche)
        if tfidf < 0.2:
            details = {
                "tfidf_score": round(tfidf, 4),
                "groq_score": 0.0,
                "intent_score": 0.0,
                "rejected_reason": "tfidf_below_threshold",
            }
            return 0.0, details

        # Couche 2 : Groq
        try:
            groq = await self._groq_score(profile, niche)
        except Exception:
            # Fallback : utiliser le score TF-IDF si Groq down
            groq = tfidf

        # Couche 3 : Intent signals
        intent = self._intent_score(profile)

        # Score final pondere
        final = self._final_score(tfidf, groq, intent)

        details = {
            "tfidf_score": round(tfidf, 4),
            "groq_score": round(groq, 4),
            "intent_score": round(intent, 4),
            "breakdown": {
                "tfidf_weight": 0.30,
                "groq_weight": 0.40,
                "intent_weight": 0.30,
            },
        }

        return round(final, 4), details

    def _tfidf_score(self, profile: dict, niche: Niche) -> float:
        """
        Couche 1 : TF-IDF sur la bio Instagram.
        Vocabulaire = niche.scoring_vocab.
        Methode hybride : keyword matching pondere par TF-IDF weights.
        Pour les bios courtes, cosine similarity brute est trop basse.
        """
        bio = profile.get("bio", "") or ""
        if not bio.strip():
            return 0.0

        scoring_vocab = json.loads(niche.scoring_vocab) if isinstance(niche.scoring_vocab, str) else niche.scoring_vocab
        if not scoring_vocab:
            return 0.5  # pas de vocab → score neutre

        bio_lower = bio.lower()
        bio_words = set(bio_lower.split())

        # Compter les mots-cles trouves dans la bio (match exact + racine)
        matches = 0
        for keyword in scoring_vocab:
            kw_lower = keyword.lower()
            # Match exact mot ou substring
            if kw_lower in bio_words or kw_lower in bio_lower:
                matches += 1
                continue
            # Match par racine : prefixe commun >= 5 chars
            # Ex: "cuisine" matche "cuisinier", "gastronomie" matche "gastronomique"
            if len(kw_lower) >= 5:
                stem = kw_lower[:5]
                if any(w.startswith(stem) for w in bio_words):
                    matches += 1

        if matches == 0:
            return 0.0

        # Score = proportion de mots-cles trouves, avec scaling non-lineaire
        # 1 match sur 13 = ~0.15, 3 matches = ~0.5, 5+ matches = ~0.8+
        ratio = matches / len(scoring_vocab)
        # Boost : chaque match additionnel a plus de poids (courbe concave)
        score = min(1.0, ratio * 2.5)

        return max(0.0, min(1.0, score))

    async def _groq_score(self, profile: dict, niche: Niche) -> float:
        """
        Couche 2 : Groq analyse la bio et retourne un score de pertinence.
        Timeout 10s, fallback = tfidf_score si Groq fail.
        """
        bio = profile.get("bio", "") or ""
        return await score_bio_with_groq(bio, niche.name, niche.product_pitch)

    def _intent_score(self, profile: dict) -> float:
        """
        Couche 3 : Signaux d'intention (independant de la niche).
        Score 0.0-1.0 base sur l'activite du compte.
        """
        total = 0.0

        # + 0.15 si compte < 2 ans (en plein developpement)
        account_age_days = profile.get("account_age_days", 365)
        if account_age_days < 730:
            total += 0.15

        # + 0.20 si a poste dans les 7 derniers jours (actif)
        last_post_days = profile.get("last_post_days", 30)
        if last_post_days <= 7:
            total += 0.20

        # + 0.15 si engagement_rate > 3%
        engagement_rate = profile.get("engagement_rate", 0.0)
        if engagement_rate > 3.0:
            total += 0.15

        # + 0.10 si has_link_in_bio (pro serieux)
        if profile.get("has_link_in_bio", False):
            total += 0.10

        # + 0.15 si follower_growth > 5%/mois
        follower_growth = profile.get("follower_growth", 0.0)
        if follower_growth > 5.0:
            total += 0.15

        # - 0.20 si dernier post > 60 jours (inactif)
        if last_post_days > 60:
            total -= 0.20

        # - 0.10 si following >> followers (ratio suspect)
        followers = profile.get("followers", 1)
        following = profile.get("following", 0)
        if followers > 0 and (following / followers) > 3:
            total -= 0.10

        return max(0.0, min(1.0, total))

    def _final_score(self, tfidf: float, groq: float, intent: float) -> float:
        """Ponderation : TF-IDF 30% + Groq 40% + Intent 30%."""
        return tfidf * 0.30 + groq * 0.40 + intent * 0.30


# ===== PIPELINE D'INGESTION =====

async def ingest_prospects_for_niche(
    niche: Niche,
    tenant_id: int,
    scraper: InstagramScraper | None = None,
    scorer: ProspectScorer | None = None,
    limit: int = 100,
) -> dict:
    """
    Pipeline complet :
    1. scraper.scrape_niche(niche, limit)
    2. Pour chaque profil filtre : scorer.score_prospect(profile, niche)
    3. Si score >= 0.5 → sauvegarder en DB avec status='scored'
    4. Logger le resultat
    """
    if scraper is None:
        scraper = InstagramScraper()
    if scorer is None:
        scorer = ProspectScorer()

    profiles = await scraper.scrape_niche(niche, limit=limit)

    scraped_count = len(profiles)
    scored_count = 0
    rejected_count = 0

    for profile in profiles:
        score, details = await scorer.score_prospect(profile, niche)

        if score >= 0.5:
            # Extraire la ville
            bio = profile.get("bio", "") or ""
            username = profile.get("username", "")
            city = extract_city(bio, username)

            # Sauvegarder en DB
            async with async_session() as session:
                prospect = Prospect(
                    tenant_id=tenant_id,
                    niche_id=niche.id,
                    instagram_id=profile["instagram_id"],
                    username=profile.get("username", ""),
                    full_name=profile.get("full_name", ""),
                    bio=bio,
                    followers=profile.get("followers", 0),
                    following=profile.get("following", 0),
                    posts_count=profile.get("posts_count", 0),
                    has_link_in_bio=profile.get("has_link_in_bio", False),
                    profile_pic_url=profile.get("profile_pic_url", ""),
                    score=score,
                    score_details=json.dumps(details, ensure_ascii=False),
                    intent_signals=json.dumps({
                        "account_age_days": profile.get("account_age_days", 0),
                        "last_post_days": profile.get("last_post_days", 0),
                        "engagement_rate": profile.get("engagement_rate", 0.0),
                        "follower_growth": profile.get("follower_growth", 0.0),
                    }, ensure_ascii=False),
                    status="scored",
                    city=city,
                )
                session.add(prospect)
                await session.commit()

            scored_count += 1
        else:
            rejected_count += 1

    # Mettre a jour les stats niche
    async with async_session() as session:
        await session.execute(
            update(Niche)
            .where(Niche.id == niche.id)
            .values(total_scraped=Niche.total_scraped + scraped_count)
        )
        await session.commit()

    summary = f"Niche {niche.name}: {scraped_count} scraped, {scored_count} scored (seuil 0.5), {rejected_count} rejetes"
    await _log(tenant_id, "INFO", summary, {
        "scraped": scraped_count,
        "scored": scored_count,
        "rejected": rejected_count,
    })

    return {"scraped": scraped_count, "scored": scored_count, "rejected": rejected_count}
