"""Scraper Instagram multi-source via Apify."""

import json
import os
import re

from apify_client import ApifyClient
from sqlalchemy import select

from backend.database import async_session
from backend.models import Niche, Prospect, SystemLog

APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
APIFY_ACTOR_HASHTAG = os.getenv("APIFY_ACTOR_HASHTAG", "apify/instagram-hashtag-scraper")
APIFY_ACTOR_PROFILE = os.getenv("APIFY_ACTOR_PROFILE", "apify/instagram-profile-scraper")

# 50 principales villes francaises pour geo-targeting
FRENCH_CITIES = [
    "Paris", "Lyon", "Marseille", "Toulouse", "Nice", "Nantes", "Montpellier",
    "Strasbourg", "Bordeaux", "Lille", "Rennes", "Reims", "Le Havre", "Cergy",
    "Saint-Étienne", "Toulon", "Grenoble", "Dijon", "Angers", "Nîmes",
    "Aix-en-Provence", "Clermont-Ferrand", "Brest", "Limoges", "Tours", "Metz",
    "Amiens", "Perpignan", "Caen", "Orléans", "Rouen", "Mulhouse", "Nancy",
    "Bourg-en-Bresse", "Besançon", "Argenteuil", "Montreuil", "Avignon",
]

# Pattern regex pre-compile pour les villes (insensible a la casse)
_CITY_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(c) for c in FRENCH_CITIES) + r")\b",
    re.IGNORECASE,
)


def extract_city(bio: str, username: str = "") -> str | None:
    """Extrait la ville depuis la bio Instagram via regex sur villes francaises."""
    text = f"{bio} {username}"
    match = _CITY_PATTERN.search(text)
    if match:
        # Retourner la ville avec la bonne casse (depuis FRENCH_CITIES)
        matched_lower = match.group(1).lower()
        for city in FRENCH_CITIES:
            if city.lower() == matched_lower:
                return city
    return None


async def _log(tenant_id: int, level: str, message: str, details: dict | None = None):
    """Log en DB."""
    async with async_session() as session:
        log = SystemLog(
            tenant_id=tenant_id,
            level=level,
            module="scraper",
            message=message,
            details=json.dumps(details or {}, ensure_ascii=False),
        )
        session.add(log)
        await session.commit()


def parse_apify_profile(raw: dict) -> dict | None:
    """
    Parse un profil brut retourne par Apify.
    Gere les variations de format entre les differents actors Apify.
    Retourne None si le profil est invalide ou incomplet.
    """
    if not raw:
        return None

    def get_field(obj: dict, *keys):
        """Cherche un champ parmi plusieurs cles possibles."""
        for key in keys:
            if key in obj and obj[key] is not None:
                return obj[key]
        return None

    instagram_id = get_field(raw, "id", "userId", "pk", "user_id")
    username = get_field(raw, "username", "userName", "ownerUsername")

    # Sans ces deux champs → profil inutilisable
    if not instagram_id or not username:
        return None

    # Followers (peut etre un dict avec "count" dans certains actors)
    followers = get_field(raw, "followersCount", "followers_count",
                          "edge_followed_by", "follower_count")
    if isinstance(followers, dict):
        followers = followers.get("count", 0)
    followers = int(followers or 0)

    # Following
    following = get_field(raw, "followingCount", "following_count",
                          "edge_follow", "following_count")
    if isinstance(following, dict):
        following = following.get("count", 0)
    following = int(following or 0)

    # Filtre de base : pas un bot, pas un mega-compte
    if followers < 100 or followers > 100_000:
        return None
    if following > followers * 10:  # Ratio suspect
        return None

    # Bio
    bio = get_field(raw, "biography", "bio", "description") or ""
    bio = str(bio).strip()[:500]

    # Posts
    posts_count = get_field(raw, "mediaCount", "media_count",
                            "edge_owner_to_timeline_media") or 0
    if isinstance(posts_count, dict):
        posts_count = posts_count.get("count", 0)
    posts_count = int(posts_count)

    if posts_count < 3:
        return None

    # Compte prive
    is_private = get_field(raw, "isPrivate", "is_private", "private") or False
    if is_private:
        return None

    # Photo de profil
    profile_pic = get_field(raw, "profilePicUrl", "profilePicUrlHD",
                             "profile_pic_url", "profile_pic_url_hd") or ""

    # Business account (bonus pour scoring)
    is_business = get_field(raw, "isBusinessAccount", "is_business_account",
                            "is_professional_account") or False

    return {
        "instagram_id": str(instagram_id),
        "username": str(username),
        "bio": bio,
        "followers": followers,
        "following": following,
        "posts_count": posts_count,
        "has_link_in_bio": bool(get_field(raw, "externalUrl", "external_url", "website")),
        "profile_pic_url": str(profile_pic)[:500] if profile_pic else "",
        "is_business": bool(is_business),
        "score": 0.0,
        "status": "scraped",
    }


class InstagramScraper:
    """Multi-source scraping via Apify."""

    def __init__(self, apify_token: str | None = None):
        self._token = apify_token or APIFY_TOKEN
        if self._token:
            self._client = ApifyClient(self._token)
        else:
            self._client = None

    async def scrape_niche(self, niche: Niche, limit: int = 100) -> list[dict]:
        """
        Scrape les profils pour une niche donnee.
        1. Lance le scraping sur les 5 premiers hashtags
        2. Deduplique par instagram_id (cross-niche)
        3. Filtre de base : followers, posts, bio, etc.
        4. Retourne liste de profils bruts
        """
        if not self._client:
            await _log(niche.tenant_id, "ERROR", "APIFY_TOKEN non defini, scraping impossible")
            return []

        hashtags = json.loads(niche.hashtags)[:5]
        all_profiles: list[dict] = []

        for hashtag in hashtags:
            profiles = await self._scrape_hashtag(hashtag, limit=limit // len(hashtags))
            all_profiles.extend(profiles)

        # Deduplication locale (par instagram_id dans ce batch)
        seen_ids: set[str] = set()
        unique_profiles: list[dict] = []
        for p in all_profiles:
            ig_id = str(p.get("id", p.get("pk", p.get("instagram_id", ""))))
            if ig_id and ig_id not in seen_ids:
                seen_ids.add(ig_id)
                p["instagram_id"] = ig_id
                unique_profiles.append(p)

        # Deduplication globale (vs DB)
        unique_profiles = await self._deduplicate_global(unique_profiles, niche.tenant_id)

        # Filtrage de base
        filtered: list[dict] = []
        for p in unique_profiles:
            if await self._apply_basic_filters(p, niche):
                filtered.append(p)

        await _log(
            niche.tenant_id, "INFO",
            f"Niche {niche.name}: {len(all_profiles)} bruts, {len(unique_profiles)} uniques, {len(filtered)} filtres",
        )

        return filtered[:limit]

    async def _scrape_hashtag(self, hashtag: str, limit: int) -> list[dict]:
        """Lance l'actor Apify hashtag scraper et retourne les profils."""
        if not self._client:
            return []

        clean_tag = hashtag.lstrip("#")

        try:
            run = self._client.actor(APIFY_ACTOR_HASHTAG).call(
                run_input={
                    "hashtags": [clean_tag],
                    "resultsLimit": limit,
                    "resultsType": "posts",
                },
                timeout_secs=300,
            )

            items = list(self._client.dataset(run["defaultDatasetId"]).iterate_items())

            # Extraire les profils uniques depuis les posts
            profiles: list[dict] = []
            seen: set[str] = set()
            for item in items:
                owner = item.get("ownerUsername", item.get("owner", {}).get("username", ""))
                owner_id = str(item.get("ownerId", item.get("owner", {}).get("id", "")))
                if owner and owner_id and owner_id not in seen:
                    seen.add(owner_id)
                    profiles.append({
                        "instagram_id": owner_id,
                        "username": owner,
                        "full_name": item.get("ownerFullName", item.get("owner", {}).get("full_name", "")),
                        "bio": item.get("ownerBio", ""),
                        "followers": item.get("ownerFollowers", 0),
                        "following": item.get("ownerFollowing", 0),
                        "posts_count": item.get("ownerPostsCount", 0),
                        "has_link_in_bio": bool(item.get("ownerExternalUrl", "")),
                        "profile_pic_url": item.get("ownerProfilePicUrl", ""),
                        "is_private": item.get("ownerIsPrivate", False),
                        "latest_post_date": item.get("timestamp", ""),
                    })

            return profiles

        except Exception as e:
            await _log(0, "ERROR", f"Scraping hashtag #{clean_tag} echoue: {e}", {"error": str(e)})
            return []

    async def _deduplicate_global(self, profiles: list[dict], tenant_id: int) -> list[dict]:
        """
        Retire les profils deja en DB (par instagram_id).
        Retire les profils blacklistes et avec spam_reports > 0.
        """
        if not profiles:
            return []

        ig_ids = [p["instagram_id"] for p in profiles if p.get("instagram_id")]

        async with async_session() as session:
            result = await session.execute(
                select(Prospect.instagram_id, Prospect.status, Prospect.spam_reports)
                .where(Prospect.instagram_id.in_(ig_ids))
            )
            existing = {row[0]: (row[1], row[2]) for row in result.all()}

        filtered: list[dict] = []
        for p in profiles:
            ig_id = p.get("instagram_id", "")
            if ig_id in existing:
                status, spam = existing[ig_id]
                if status == "blacklisted" or spam > 0:
                    continue
                # Deja en DB (peu importe le tenant) → skip
                continue
            filtered.append(p)

        return filtered

    async def _apply_basic_filters(self, profile: dict, niche: Niche) -> bool:
        """
        Filtre de base :
        - Followers : 200 < x < 50000
        - Ratio following/followers < 5
        - Au moins 3 posts
        - Bio non vide
        - Compte pas prive
        """
        followers = profile.get("followers", 0)
        following = profile.get("following", 0)
        posts = profile.get("posts_count", 0)
        bio = profile.get("bio", "")
        is_private = profile.get("is_private", False)

        if is_private:
            return False
        if not bio or not bio.strip():
            return False
        if followers < 200 or followers > 50000:
            return False
        if posts < 3:
            return False
        if followers > 0 and (following / followers) > 5:
            return False

        return True

    async def enrich_profile(self, username: str) -> dict:
        """Recupere les details complets via apify/instagram-profile-scraper."""
        if not self._client:
            return {}

        try:
            run = self._client.actor(APIFY_ACTOR_PROFILE).call(
                run_input={
                    "usernames": [username],
                },
                timeout_secs=120,
            )

            items = list(self._client.dataset(run["defaultDatasetId"]).iterate_items())
            if not items:
                return {}

            item = items[0]
            return {
                "instagram_id": str(item.get("id", "")),
                "username": item.get("username", username),
                "full_name": item.get("fullName", ""),
                "bio": item.get("biography", ""),
                "followers": item.get("followersCount", 0),
                "following": item.get("followingCount", 0),
                "posts_count": item.get("postsCount", 0),
                "has_link_in_bio": bool(item.get("externalUrl", "")),
                "profile_pic_url": item.get("profilePicUrl", ""),
                "is_private": item.get("isPrivate", False),
                "latest_post_date": item.get("latestPostDate", ""),
            }

        except Exception as e:
            await _log(0, "ERROR", f"Enrichissement @{username} echoue: {e}", {"error": str(e)})
            return {}
