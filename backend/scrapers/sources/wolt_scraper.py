"""
Scraper Wolt via Apify actor "odaudlegur/wolt-scraper".
Source de restaurants/cafes/boulangeries avec donnees de contact riches.
"""

import logging
import os
import re

from apify_client import ApifyClient

logger = logging.getLogger("instafarm.wolt")

APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
WOLT_ACTOR = "odaudlegur/wolt-scraper"


class WoltScraper:
    """Scrape les commerces alimentaires depuis Wolt via Apify."""

    def __init__(self, apify_token: str | None = None):
        self._token = apify_token or APIFY_TOKEN
        if self._token:
            self._client = ApifyClient(self._token)
        else:
            self._client = None

    async def scrape(self, city: str, limit: int = 200) -> list[dict]:
        """
        Scrape les restaurants d'une ville via Wolt.

        Args:
            city: nom de la ville (ex: "Lyon")
            limit: nombre max de resultats

        Returns:
            liste de dicts {name, address, phone, website, instagram, ...}
        """
        if not self._client:
            logger.error("APIFY_TOKEN non defini, Wolt scraping impossible")
            return []

        try:
            # Wolt utilise des slugs de ville (lyon, paris, marseille, etc.)
            city_slug = city.lower().strip().replace(" ", "-")

            run = self._client.actor(WOLT_ACTOR).call(
                run_input={
                    "city": city_slug,
                    "crawl_websites": True,
                    "maxItems": limit,
                },
                timeout_secs=600,
            )

            items = list(self._client.dataset(run["defaultDatasetId"]).iterate_items())
            logger.info(f"Wolt: {len(items)} items bruts pour '{city}'")

            results: list[dict] = []
            instagram_direct = 0

            for item in items:
                parsed = self._parse_item(item, city)
                if parsed:
                    results.append(parsed)
                    if parsed.get("instagram"):
                        instagram_direct += 1

            logger.info(
                f"Wolt: {len(results)} restaurants trouves, "
                f"{instagram_direct} avec Instagram direct"
            )
            return results

        except Exception as e:
            logger.error(f"Wolt scraping echoue pour '{city}': {e}")
            return []

    @staticmethod
    def _parse_item(raw: dict, city: str) -> dict | None:
        """Parse un item Wolt brut."""
        name = raw.get("name", "").strip()
        if not name:
            return None

        # Adresse
        address = raw.get("address", raw.get("street_address", ""))

        # Telephone
        phone = raw.get("phone", raw.get("phone_number", ""))

        # Website
        website = raw.get("website", raw.get("url", ""))

        # Email
        email = raw.get("email", "")

        # Reseaux sociaux — chercher dans les liens et descriptions
        instagram = None
        facebook = None

        # Champ direct
        ig_raw = raw.get("instagram", raw.get("instagram_url", ""))
        if ig_raw:
            instagram = WoltScraper._extract_ig_username(ig_raw)

        fb_raw = raw.get("facebook", raw.get("facebook_url", ""))
        if fb_raw:
            facebook = str(fb_raw)

        # Chercher dans les liens sociaux (si liste fournie)
        social_links = raw.get("social_links", raw.get("links", []))
        if isinstance(social_links, list):
            for link in social_links:
                link_str = str(link.get("url", link) if isinstance(link, dict) else link)
                if "instagram.com" in link_str and not instagram:
                    instagram = WoltScraper._extract_ig_username(link_str)
                elif "facebook.com" in link_str and not facebook:
                    facebook = link_str

        # Chercher Instagram dans la description
        description = raw.get("description", "")
        if not instagram and description:
            ig_match = re.search(r"instagram\.com/([a-zA-Z0-9_.]+)", description)
            if ig_match:
                instagram = ig_match.group(1)
            # Pattern @username
            at_match = re.search(r"@([a-zA-Z0-9_.]{3,30})\b", description)
            if not instagram and at_match:
                username = at_match.group(1)
                # Filtrer les emails
                if "@" not in description[max(0, at_match.start() - 1):at_match.start()]:
                    instagram = username

        return {
            "name": name,
            "address": str(address) if address else "",
            "city": city,
            "phone": str(phone) if phone else None,
            "website": str(website) if website else None,
            "email": str(email) if email else None,
            "instagram": instagram,
            "facebook": facebook,
            "source": "wolt",
        }

    @staticmethod
    def _extract_ig_username(url_or_handle: str) -> str | None:
        """Extrait le username Instagram d'une URL ou handle."""
        if not url_or_handle:
            return None

        text = str(url_or_handle).strip()

        # URL complète
        match = re.search(r"instagram\.com/([a-zA-Z0-9_.]+)", text)
        if match:
            username = match.group(1)
            # Exclure les pages generiques
            if username.lower() not in ("p", "explore", "reel", "stories", "accounts", "about"):
                return username.lower()

        # Handle direct (@username ou juste username)
        text = text.lstrip("@")
        if re.match(r"^[a-zA-Z0-9_.]{3,30}$", text):
            return text.lower()

        return None
