"""
InstagramFinder — 4 strategies en cascade pour trouver le compte Instagram
d'un business a partir de son nom, site web, ville.
"""

import logging
import os
import re
import unicodedata

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("instafarm.ig_finder")

# Mots trop generiques — un username = juste ce mot n'est pas un vrai profil pro
_USERNAME_BLACKLIST = frozenset({
    "paris", "lyon", "marseille", "toulouse", "nice", "nantes", "bordeaux",
    "lille", "france", "restaurant", "dentiste", "coiffeur", "garage",
    "pro", "contact", "info", "admin", "official", "page", "test",
})


def clean_username(raw: str) -> str | None:
    """
    Nettoie et valide un username Instagram genere.
    Retourne None si le username est invalide ou trop generique.
    """
    if not raw:
        return None

    # 1. Supprimer le @ si present
    raw = raw.lstrip("@")

    # 2. Normaliser les accents (e→e, c→c, etc.)
    raw = unicodedata.normalize("NFKD", raw)
    raw = "".join(c for c in raw if not unicodedata.combining(c))

    # 3. Remplacer espaces et tirets par rien
    raw = raw.replace(" ", "").replace("-", "")

    # 4. Garder uniquement lettres, chiffres, points, underscores
    raw = re.sub(r"[^a-zA-Z0-9._]", "", raw)

    # 5. Instagram : max 30 caracteres
    raw = raw[:30]

    # 6. Invalider si trop court (<3) ou trop generique
    if len(raw) < 3:
        return None
    if raw.lower() in _USERNAME_BLACKLIST:
        return None

    return raw.lower()

# Timeouts par strategie
WEBSITE_TIMEOUT = 10
GOOGLE_TIMEOUT = 10
APIFY_TIMEOUT = 120


class InstagramFinder:
    """
    Trouve le compte Instagram d'un business via 4 strategies en cascade :
    1. Scrape du site web (liens <a href>, meta tags, JSON-LD)
    2. Recherche via page Facebook
    3. Recherche Google (SerpApi)
    4. Recherche Apify instagram-profile-scraper

    S'arrete des qu'une strategie retourne un resultat.
    """

    def __init__(self):
        self._serpapi_key = os.getenv("SERPAPI_KEY", "")
        self._apify_token = os.getenv("APIFY_TOKEN", "")

    async def find_instagram(self, business: dict) -> str | None:
        """
        Essaie les 4 strategies en ordre pour trouver le username Instagram.

        Args:
            business: dict avec au minimum 'name', optionnel 'city', 'website', 'facebook'

        Returns:
            username Instagram (sans @) ou None
        """
        name = business.get("name", "")
        city = business.get("city", "")
        website = business.get("website", "")
        facebook = business.get("facebook", "")

        # Si Instagram deja connu
        if business.get("instagram"):
            cleaned = clean_username(business["instagram"])
            if cleaned:
                logger.debug(f"[{name}] Instagram deja connu: @{cleaned}")
                return cleaned

        # Strategie 1 : Site web (retourne des usernames extraits d'URL — deja propres)
        if website:
            result = await self.strategy_1_website(website)
            result = clean_username(result) if result else None
            if result:
                logger.info(f"[{name}] Instagram trouve via site web: @{result}")
                return result

        # Strategie 2 : Facebook (retourne des usernames extraits d'URL)
        if facebook:
            result = await self.strategy_2_facebook(facebook, name, city)
            result = clean_username(result) if result else None
            if result:
                logger.info(f"[{name}] Instagram trouve via Facebook: @{result}")
                return result

        # Strategie 3 : Google (retourne des usernames extraits d'URL)
        if name and self._serpapi_key:
            result = await self.strategy_3_google(name, city)
            result = clean_username(result) if result else None
            if result:
                logger.info(f"[{name}] Instagram trouve via Google: @{result}")
                return result

        # Strategie 4 : Apify (genere un username a partir du nom — risque de faux)
        if name and self._apify_token:
            result = await self.strategy_4_apify(name, city)
            result = clean_username(result) if result else None
            if result:
                logger.info(f"[{name}] Instagram trouve via Apify: @{result}")
                return result

        logger.debug(f"[{name}] Aucun Instagram trouve")
        return None

    async def strategy_1_website(self, website_url: str) -> str | None:
        """
        Scrape le site web du business pour trouver des liens Instagram.
        Cherche dans : <a href>, meta tags, JSON-LD, texte brut.
        """
        if not website_url:
            return None

        # S'assurer que l'URL a un scheme
        if not website_url.startswith(("http://", "https://")):
            website_url = "https://" + website_url

        try:
            async with httpx.AsyncClient(
                timeout=WEBSITE_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
            ) as client:
                resp = await client.get(website_url)
                if resp.status_code != 200:
                    return None

                html = resp.text
                soup = BeautifulSoup(html, "html.parser")

                # 1. Chercher dans les liens <a>
                for a_tag in soup.find_all("a", href=True):
                    href = a_tag["href"]
                    username = self._extract_ig_from_url(href)
                    if username:
                        return username

                # 2. Chercher dans les meta tags (og:see_also, etc.)
                for meta in soup.find_all("meta"):
                    content = meta.get("content", "")
                    if "instagram.com" in content:
                        username = self._extract_ig_from_url(content)
                        if username:
                            return username

                # 3. Chercher dans les scripts JSON-LD
                for script in soup.find_all("script", type="application/ld+json"):
                    text = script.string or ""
                    ig_match = re.search(r"instagram\.com/([a-zA-Z0-9_.]+)", text)
                    if ig_match:
                        username = ig_match.group(1).lower()
                        if username not in ("p", "explore", "reel", "stories"):
                            return username

                # 4. Chercher dans le HTML brut (pattern fallback)
                ig_match = re.search(r"instagram\.com/([a-zA-Z0-9_.]{3,30})", html)
                if ig_match:
                    username = ig_match.group(1).lower()
                    if username not in ("p", "explore", "reel", "stories", "accounts", "about"):
                        return username

        except (httpx.TimeoutException, httpx.ConnectError, httpx.TooManyRedirects) as e:
            logger.debug(f"Website scrape echoue pour {website_url}: {e}")
        except Exception as e:
            logger.debug(f"Website scrape erreur pour {website_url}: {e}")

        return None

    async def strategy_2_facebook(
        self, facebook_url: str, business_name: str, city: str
    ) -> str | None:
        """
        Scrape la page Facebook pour extraire le lien Instagram.
        Cherche dans la section 'A propos' / liens de la page.
        """
        if not facebook_url:
            return None

        # Normaliser l'URL
        if not facebook_url.startswith("http"):
            facebook_url = "https://www.facebook.com/" + facebook_url

        try:
            # Scraper la page publique (section about)
            about_url = facebook_url.rstrip("/") + "/about"
            async with httpx.AsyncClient(
                timeout=10,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                },
            ) as client:
                resp = await client.get(about_url)
                if resp.status_code != 200:
                    return None

                # Chercher un lien Instagram dans le HTML
                ig_match = re.search(r"instagram\.com/([a-zA-Z0-9_.]{3,30})", resp.text)
                if ig_match:
                    username = ig_match.group(1).lower()
                    if username not in ("p", "explore", "reel", "stories"):
                        return username

        except Exception as e:
            logger.debug(f"Facebook scrape echoue pour {facebook_url}: {e}")

        return None

    async def strategy_3_google(self, business_name: str, city: str) -> str | None:
        """
        Recherche Google via SerpApi pour trouver le profil Instagram.
        100 requetes/mois gratuites avec SerpApi.
        """
        if not self._serpapi_key:
            return None

        query = f'"{business_name}" {city} site:instagram.com'

        try:
            async with httpx.AsyncClient(timeout=GOOGLE_TIMEOUT) as client:
                resp = await client.get(
                    "https://serpapi.com/search",
                    params={
                        "q": query,
                        "api_key": self._serpapi_key,
                        "num": 5,
                        "gl": "fr",
                        "hl": "fr",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                # Parser les resultats organiques
                for result in data.get("organic_results", []):
                    link = result.get("link", "")
                    username = self._extract_ig_from_url(link)
                    if username:
                        return username

        except Exception as e:
            logger.debug(f"Google/SerpApi echoue pour '{business_name}': {e}")

        return None

    async def strategy_4_apify(self, business_name: str, city: str) -> str | None:
        """
        Recherche via Apify instagram-profile-scraper.
        La strategie la plus couteuse — en dernier recours.
        """
        if not self._apify_token:
            return None

        try:
            from apify_client import ApifyClient

            client = ApifyClient(self._apify_token)

            # Chercher le nom du business comme username possible
            search_term = clean_username(business_name)
            if not search_term:
                return None

            run = client.actor("apify/instagram-profile-scraper").call(
                run_input={"usernames": [search_term]},
                timeout_secs=APIFY_TIMEOUT,
            )

            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            if items:
                username = items[0].get("username", "")
                if username:
                    return username.lower()

        except Exception as e:
            logger.debug(f"Apify search echoue pour '{business_name}': {e}")

        return None

    @staticmethod
    def _extract_ig_from_url(url: str) -> str | None:
        """Extrait un username Instagram d'une URL."""
        if not url or "instagram.com" not in url:
            return None

        match = re.search(r"instagram\.com/([a-zA-Z0-9_.]{3,30})", url)
        if match:
            username = match.group(1).lower()
            excluded = {"p", "explore", "reel", "reels", "stories", "accounts", "about", "developer", "legal"}
            if username not in excluded:
                return username

        return None
