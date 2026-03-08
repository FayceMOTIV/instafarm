"""
ScrapingPipeline — Orchestrateur multi-sources en 5 etapes.

Pipeline :
  1. Collecte (Wolt + Sirene)
  2. Deduplication par nom+adresse
  3. Recherche Instagram (InstagramFinder 4 strategies)
  4. Scraping profils IG (Apify) + filtrage
  5. Verification IA (AIVerifier texte+vision) + insertion DB + queue Redis

Remplace le systeme hashtag-only de bot/scraper.py.
"""

import asyncio
import json
import logging
import os
import uuid

from sqlalchemy import select

from backend.database import async_session
from backend.models import Niche, Prospect, SystemLog

from backend.scrapers.niches_config import get_sector_config
from backend.scrapers.sources.sirene_scraper import SireneScraper
from backend.scrapers.sources.wolt_scraper import WoltScraper
from backend.scrapers.enrichment.instagram_finder import InstagramFinder
from backend.scrapers.verification.ai_verifier import AIVerifier

logger = logging.getLogger("instafarm.pipeline")

# Apify profile scraper
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
APIFY_ACTOR_PROFILE = os.getenv("APIFY_ACTOR_PROFILE", "apify/instagram-profile-scraper")

# Batch size pour scraping profils IG
IG_PROFILE_BATCH_SIZE = 10

# Score minimum pour validation IA
AI_SCORE_THRESHOLD = 0.65


async def _log(tenant_id: int, level: str, message: str, details: dict | None = None):
    """Log en DB."""
    async with async_session() as session:
        log_entry = SystemLog(
            tenant_id=tenant_id,
            level=level,
            module="pipeline",
            message=message,
            details=json.dumps(details or {}, ensure_ascii=False),
        )
        session.add(log_entry)
        await session.commit()


class ScrapingPipeline:
    """
    Pipeline multi-sources en 5 etapes.
    Appele par le scheduler pour chaque niche active.
    """

    def __init__(self):
        self._sirene = SireneScraper()
        self._wolt = WoltScraper()
        self._ig_finder = InstagramFinder()
        self._ai_verifier = AIVerifier()

    async def run_for_niche(self, niche: dict) -> dict:
        """
        Execute le pipeline complet pour une niche.

        Args:
            niche: dict avec au minimum :
                - tenant_id (int)
                - niche_id (int)
                - name (str) : nom de la niche ("Restaurants")
                - sector (str) : cle niche_config ("restaurant")
                - city (str) : ville cible ("Lyon")
                - departement (str, optionnel) : code dept ("69")
                - limit (int, optionnel) : max prospects (default 50)

        Returns:
            {collected, deduplicated, instagram_found, profiles_scraped,
             validated, saved, stats_by_source}
        """
        tenant_id = niche["tenant_id"]
        niche_id = niche["niche_id"]
        sector = niche.get("sector", niche.get("name", "").lower())
        city = niche.get("city", "")
        departement = niche.get("departement", "")
        limit = niche.get("limit", 50)

        sector_config = get_sector_config(sector)

        logger.info(f"[Pipeline] Demarrage pour niche '{sector}' ville='{city}' limit={limit}")
        await _log(tenant_id, "INFO", f"Pipeline demarre: {sector} / {city}", {"limit": limit})

        stats = {
            "collected": 0,
            "deduplicated": 0,
            "instagram_found": 0,
            "profiles_scraped": 0,
            "validated": 0,
            "saved": 0,
            "stats_by_source": {"sirene": 0, "wolt": 0},
        }

        # =============================================
        # ETAPE 1 : Collecte multi-sources
        # =============================================
        businesses = await self._step1_collect(sector, city, departement, limit, sector_config)
        stats["collected"] = len(businesses)
        stats["stats_by_source"]["sirene"] = sum(1 for b in businesses if b.get("source") == "sirene")
        stats["stats_by_source"]["wolt"] = sum(1 for b in businesses if b.get("source") == "wolt")

        logger.info(f"[Pipeline] Etape 1: {len(businesses)} business collectes "
                     f"(sirene={stats['stats_by_source']['sirene']}, wolt={stats['stats_by_source']['wolt']})")

        if not businesses:
            await _log(tenant_id, "WARNING", f"Pipeline: 0 business collecte pour {sector}/{city}")
            return stats

        # =============================================
        # ETAPE 2 : Deduplication par nom+adresse
        # =============================================
        businesses = self._step2_deduplicate(businesses)
        stats["deduplicated"] = len(businesses)
        logger.info(f"[Pipeline] Etape 2: {len(businesses)} apres deduplication")

        # =============================================
        # ETAPE 3 : Recherche Instagram
        # =============================================
        businesses = await self._step3_find_instagram(businesses)
        ig_count = sum(1 for b in businesses if b.get("instagram"))
        stats["instagram_found"] = ig_count
        logger.info(f"[Pipeline] Etape 3: {ig_count}/{len(businesses)} ont un Instagram")

        # Garder seulement ceux avec Instagram
        businesses_with_ig = [b for b in businesses if b.get("instagram")]
        if not businesses_with_ig:
            await _log(tenant_id, "WARNING", f"Pipeline: 0 Instagram trouve pour {sector}/{city}")
            return stats

        # =============================================
        # ETAPE 4 : Scraping profils IG via Apify
        # =============================================
        profiles = await self._step4_scrape_profiles(businesses_with_ig, tenant_id)
        stats["profiles_scraped"] = len(profiles)
        logger.info(f"[Pipeline] Etape 4: {len(profiles)} profils IG scrapes")

        if not profiles:
            await _log(tenant_id, "WARNING", f"Pipeline: 0 profil IG scrape pour {sector}/{city}")
            return stats

        # =============================================
        # ETAPE 5 : Verification IA + insertion DB
        # =============================================
        saved_count = await self._step5_verify_and_save(
            profiles, niche_id, tenant_id, sector_config, city,
        )
        stats["validated"] = saved_count
        stats["saved"] = saved_count

        logger.info(
            f"[Pipeline] Termine: {saved_count} prospects valides et sauvegardes "
            f"sur {stats['collected']} collectes"
        )
        await _log(
            tenant_id, "INFO",
            f"Pipeline termine: {saved_count}/{stats['collected']} prospects sauvegardes",
            stats,
        )

        return stats

    # --------------------------------------------------
    # ETAPE 1 : Collecte multi-sources
    # --------------------------------------------------
    async def _step1_collect(
        self,
        sector: str,
        city: str,
        departement: str,
        limit: int,
        sector_config: dict,
    ) -> list[dict]:
        """Collecte depuis Sirene + Wolt (si food sector) en parallele."""
        tasks = []

        # Sirene : toujours
        tasks.append(self._collect_sirene(sector, city, departement, limit))

        # Wolt : uniquement pour les niches alimentaires
        if sector_config.get("wolt_enabled", False) and city:
            tasks.append(self._collect_wolt(city, limit))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        businesses: list[dict] = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"[Pipeline] Collecte erreur: {result}")
                continue
            if isinstance(result, list):
                businesses.extend(result)

        return businesses[:limit * 2]  # Garder une marge pour la dedup

    async def _collect_sirene(
        self, sector: str, city: str, departement: str, limit: int,
    ) -> list[dict]:
        """Wrapper Sirene avec gestion erreur."""
        try:
            return await self._sirene.search(
                sector=sector,
                city=city or None,
                departement=departement or None,
                limit=limit,
            )
        except Exception as e:
            logger.error(f"[Pipeline] Sirene echoue: {e}")
            return []

    async def _collect_wolt(self, city: str, limit: int) -> list[dict]:
        """Wrapper Wolt avec gestion erreur."""
        try:
            return await self._wolt.scrape(city=city, limit=limit)
        except Exception as e:
            logger.error(f"[Pipeline] Wolt echoue: {e}")
            return []

    # --------------------------------------------------
    # ETAPE 2 : Deduplication par nom+adresse
    # --------------------------------------------------
    @staticmethod
    def _step2_deduplicate(businesses: list[dict]) -> list[dict]:
        """Deduplique par nom normalise + code postal."""
        seen: set[str] = set()
        unique: list[dict] = []

        for biz in businesses:
            name = biz.get("name", "").strip().lower()
            # Cle de dedup : nom + code postal (ou ville si pas de CP)
            postal = biz.get("postal_code", biz.get("city", "")).strip().lower()
            key = f"{name}|{postal}"

            if key in seen or not name:
                continue
            seen.add(key)
            unique.append(biz)

        return unique

    # --------------------------------------------------
    # ETAPE 3 : Recherche Instagram
    # --------------------------------------------------
    async def _step3_find_instagram(self, businesses: list[dict]) -> list[dict]:
        """Trouve le compte IG pour chaque business via 4 strategies cascade."""
        # Traiter en parallele par lots de 5 pour eviter rate limits
        batch_size = 5
        for i in range(0, len(businesses), batch_size):
            batch = businesses[i : i + batch_size]
            tasks = [self._ig_finder.find_instagram(biz) for biz in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for biz, result in zip(batch, results):
                if isinstance(result, Exception):
                    logger.debug(f"[Pipeline] IG finder erreur pour '{biz.get('name')}': {result}")
                    continue
                if result:
                    biz["instagram"] = result

            # Petit delai entre batches
            if i + batch_size < len(businesses):
                await asyncio.sleep(0.5)

        return businesses

    # --------------------------------------------------
    # ETAPE 4 : Scraping profils IG via Apify
    # --------------------------------------------------
    async def _step4_scrape_profiles(
        self, businesses: list[dict], tenant_id: int,
    ) -> list[dict]:
        """Scrape les profils IG par batch de 10 via Apify."""
        if not APIFY_TOKEN:
            logger.error("[Pipeline] APIFY_TOKEN non defini, skip scraping profils")
            return []

        usernames = [b["instagram"] for b in businesses if b.get("instagram")]
        if not usernames:
            return []

        from apify_client import ApifyClient

        client = ApifyClient(APIFY_TOKEN)
        all_profiles: list[dict] = []

        # Traiter par batch
        for i in range(0, len(usernames), IG_PROFILE_BATCH_SIZE):
            batch = usernames[i : i + IG_PROFILE_BATCH_SIZE]
            logger.info(f"[Pipeline] Scraping batch IG {i//IG_PROFILE_BATCH_SIZE + 1}: {len(batch)} profils")

            try:
                run = client.actor(APIFY_ACTOR_PROFILE).call(
                    run_input={"usernames": batch},
                    timeout_secs=180,
                )
                items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

                for item in items:
                    profile = self._parse_ig_profile(item)
                    if profile:
                        # Rattacher les donnees business
                        biz_match = next(
                            (b for b in businesses if b.get("instagram") == profile["username"]),
                            None,
                        )
                        if biz_match:
                            profile["business_name"] = biz_match.get("name", "")
                            profile["business_address"] = biz_match.get("address", "")
                            profile["business_city"] = biz_match.get("city", "")
                            profile["business_phone"] = biz_match.get("phone", "")
                            profile["business_website"] = biz_match.get("website", "")
                            profile["source"] = biz_match.get("source", "unknown")

                        all_profiles.append(profile)

            except Exception as e:
                logger.error(f"[Pipeline] Apify profile batch echoue: {e}")
                await _log(tenant_id, "ERROR", f"Apify profile batch echoue: {e}")

        # Dedup globale vs DB
        all_profiles = await self._deduplicate_vs_db(all_profiles)

        return all_profiles

    @staticmethod
    def _parse_ig_profile(raw: dict) -> dict | None:
        """Parse un profil Apify en dict standardise."""
        if not raw:
            return None

        def get(obj: dict, *keys):
            for k in keys:
                if k in obj and obj[k] is not None:
                    return obj[k]
            return None

        instagram_id = get(raw, "id", "userId", "pk", "user_id")
        username = get(raw, "username", "userName", "ownerUsername")

        if not instagram_id or not username:
            return None

        followers = get(raw, "followersCount", "followers_count", "edge_followed_by") or 0
        if isinstance(followers, dict):
            followers = followers.get("count", 0)
        followers = int(followers)

        following = get(raw, "followingCount", "following_count", "edge_follow") or 0
        if isinstance(following, dict):
            following = following.get("count", 0)
        following = int(following)

        posts_count = get(raw, "postsCount", "mediaCount", "media_count") or 0
        if isinstance(posts_count, dict):
            posts_count = posts_count.get("count", 0)
        posts_count = int(posts_count)

        is_private = get(raw, "isPrivate", "is_private", "private") or False
        if is_private:
            return None

        bio = str(get(raw, "biography", "bio", "description") or "").strip()[:500]
        profile_pic = str(get(raw, "profilePicUrl", "profilePicUrlHD", "profile_pic_url") or "")
        is_business = bool(get(raw, "isBusinessAccount", "is_business_account", "is_professional_account"))

        # Dernier post caption (pour verification IA)
        last_caption = ""
        recent_posts = raw.get("latestPosts", raw.get("edge_owner_to_timeline_media", {}).get("edges", []))
        if isinstance(recent_posts, list) and recent_posts:
            first_post = recent_posts[0]
            if isinstance(first_post, dict):
                last_caption = first_post.get("caption", first_post.get("text", ""))
                # Si c'est un edge format
                if "node" in first_post:
                    edges_caption = first_post["node"].get("edge_media_to_caption", {}).get("edges", [])
                    if edges_caption:
                        last_caption = edges_caption[0].get("node", {}).get("text", "")

        return {
            "instagram_id": str(instagram_id),
            "username": str(username).lower(),
            "full_name": str(get(raw, "fullName", "full_name") or ""),
            "bio": bio,
            "followers": followers,
            "following": following,
            "posts_count": posts_count,
            "has_link_in_bio": bool(get(raw, "externalUrl", "external_url", "website")),
            "profile_pic_url": profile_pic[:500],
            "is_business": is_business,
            "last_post_caption": str(last_caption)[:300] if last_caption else "",
        }

    async def _deduplicate_vs_db(self, profiles: list[dict]) -> list[dict]:
        """Retire les profils deja en DB (par instagram_id)."""
        if not profiles:
            return []

        ig_ids = [p["instagram_id"] for p in profiles if p.get("instagram_id")]
        if not ig_ids:
            return profiles

        async with async_session() as session:
            result = await session.execute(
                select(Prospect.instagram_id).where(Prospect.instagram_id.in_(ig_ids))
            )
            existing_ids = {row[0] for row in result.all()}

        return [p for p in profiles if p.get("instagram_id") not in existing_ids]

    # --------------------------------------------------
    # ETAPE 5 : Verification IA + insertion DB + queue
    # --------------------------------------------------
    async def _step5_verify_and_save(
        self,
        profiles: list[dict],
        niche_id: int,
        tenant_id: int,
        sector_config: dict,
        city: str,
    ) -> int:
        """Verifie chaque profil avec l'IA, insere en DB les valides."""
        saved = 0

        # Verifier par lots de 3 (pour limiter les calls Groq simultanes)
        batch_size = 3
        for i in range(0, len(profiles), batch_size):
            batch = profiles[i : i + batch_size]

            tasks = []
            for profile in batch:
                niche_config = {
                    "sector": sector_config.get("keywords_default", [""])[0] if sector_config.get("keywords_default") else "",
                    "name": profile.get("business_name", ""),
                    "city": city,
                }
                tasks.append(self._ai_verifier.verify_full(profile, niche_config))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for profile, result in zip(batch, results):
                if isinstance(result, Exception):
                    logger.warning(f"[Pipeline] IA verification erreur pour @{profile.get('username')}: {result}")
                    # En cas d'erreur IA, on laisse passer avec score 0.5
                    result = {
                        "is_valid": True,
                        "score": 0.5,
                        "verdict": "ia_indisponible",
                        "dm_approach": "Approche generique",
                        "red_flags": [],
                    }

                if result.get("is_valid", False):
                    inserted = await self._save_prospect(
                        profile, result, niche_id, tenant_id, city,
                    )
                    if inserted:
                        saved += 1
                else:
                    logger.debug(
                        f"[Pipeline] @{profile.get('username')} rejete par IA "
                        f"(score={result.get('score', 0):.2f}, flags={result.get('red_flags', [])})"
                    )

        return saved

    async def _save_prospect(
        self,
        profile: dict,
        ai_result: dict,
        niche_id: int,
        tenant_id: int,
        city: str,
    ) -> bool:
        """Insere un prospect valide en DB."""
        try:
            async with async_session() as session:
                # Verifier doublon une derniere fois
                existing = await session.execute(
                    select(Prospect.id).where(
                        Prospect.instagram_id == profile["instagram_id"]
                    )
                )
                if existing.scalar_one_or_none():
                    return False

                prospect = Prospect(
                    tenant_id=tenant_id,
                    niche_id=niche_id,
                    instagram_id=profile["instagram_id"],
                    username=profile["username"],
                    full_name=profile.get("full_name", ""),
                    bio=profile.get("bio", ""),
                    followers=profile.get("followers", 0),
                    following=profile.get("following", 0),
                    posts_count=profile.get("posts_count", 0),
                    has_link_in_bio=profile.get("has_link_in_bio", False),
                    profile_pic_url=profile.get("profile_pic_url", ""),
                    score=ai_result.get("score", 0.0),
                    score_details=json.dumps({
                        "ai_score": ai_result.get("score", 0),
                        "verdict": ai_result.get("verdict", ""),
                        "dm_approach": ai_result.get("dm_approach", ""),
                        "red_flags": ai_result.get("red_flags", []),
                        "text_result": ai_result.get("text_result", {}),
                        "visual_result": ai_result.get("visual_result", {}),
                    }, ensure_ascii=False),
                    intent_signals=json.dumps({
                        "is_business": profile.get("is_business", False),
                        "business_name": profile.get("business_name", ""),
                        "business_phone": profile.get("business_phone", ""),
                        "business_website": profile.get("business_website", ""),
                        "source": profile.get("source", ""),
                    }, ensure_ascii=False),
                    status="scored",
                    city=city or profile.get("business_city", ""),
                    country="FR",
                )
                session.add(prospect)
                await session.commit()

                logger.info(
                    f"[Pipeline] Prospect sauve: @{profile['username']} "
                    f"(score={ai_result.get('score', 0):.2f}, source={profile.get('source', '?')})"
                )
                return True

        except Exception as e:
            logger.error(f"[Pipeline] Erreur insertion @{profile.get('username')}: {e}")
            return False

    # --------------------------------------------------
    # Methode utilitaire pour le scheduler
    # --------------------------------------------------
    async def run_for_niche_from_db(self, niche_row: Niche) -> dict:
        """
        Wrapper qui prend un objet Niche SQLAlchemy et le convertit
        en dict pour run_for_niche().
        """
        cities = json.loads(niche_row.target_cities or "[]")
        city = cities[0] if cities else ""

        # Detecter le departement depuis la ville (heuristique simple)
        departement = ""

        niche_dict = {
            "tenant_id": niche_row.tenant_id,
            "niche_id": niche_row.id,
            "name": niche_row.name,
            "sector": niche_row.name.lower().rstrip("s"),  # "Restaurants" -> "restaurant"
            "city": city,
            "departement": departement,
            "limit": 50,
        }

        return await self.run_for_niche(niche_dict)
