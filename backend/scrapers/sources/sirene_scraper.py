"""
Scraper API Sirene (recherche-entreprises.api.gouv.fr).
API 100% gratuite, sans cle API. Jusqu'a 500 resultats par requete.
"""

import asyncio
import logging

import httpx

from backend.scrapers.niches_config import get_naf_codes

logger = logging.getLogger("instafarm.sirene")

SIRENE_API_URL = "https://recherche-entreprises.api.gouv.fr/search"
GEO_API_URL = "https://geo.api.gouv.fr/communes"
SIRENE_TIMEOUT = 15
SIRENE_MAX_PER_PAGE = 25  # max autorise par l'API
SIRENE_MAX_RESULTS = 500  # limite raisonnable

# Mapping villes principales → code departement
_CITY_TO_DEPT: dict[str, str] = {
    "paris": "75", "lyon": "69", "marseille": "13",
    "toulouse": "31", "nice": "06", "nantes": "44",
    "montpellier": "34", "strasbourg": "67", "bordeaux": "33",
    "lille": "59", "rennes": "35", "reims": "51",
    "saint-etienne": "42", "toulon": "83", "grenoble": "38",
    "dijon": "21", "nimes": "30", "angers": "49",
    "brest": "29", "limoges": "87", "tours": "37",
    "amiens": "80", "perpignan": "66", "metz": "57",
    "besancon": "25", "orleans": "45", "rouen": "76",
    "mulhouse": "68", "caen": "14", "nancy": "54",
    "bourg-en-bresse": "01", "clermont-ferrand": "63",
    "pau": "64", "bayonne": "64", "annecy": "74",
    "chambery": "73", "avignon": "84", "cannes": "06",
    "antibes": "06", "aix-en-provence": "13",
    "saint-denis": "93", "montreuil": "93", "boulogne-billancourt": "92",
}


def city_to_department(city: str) -> str:
    """
    Convertit un nom de ville en code departement.
    Utilise le mapping local, puis l'API geo.api.gouv.fr en fallback.
    """
    if not city:
        return ""

    normalized = city.strip().lower()

    # Lookup local
    if normalized in _CITY_TO_DEPT:
        dept = _CITY_TO_DEPT[normalized]
        logger.info(f"ville {city} -> departement {dept} (mapping local)")
        return dept

    # Fallback : API geo.api.gouv.fr
    try:
        resp = httpx.get(
            GEO_API_URL,
            params={"nom": city, "fields": "departement", "boost": "population", "limit": "1"},
            timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data:
                dept = data[0].get("departement", {}).get("code", "")
                if dept:
                    logger.info(f"ville {city} -> departement {dept} (geo API)")
                    return dept
    except Exception as e:
        logger.warning(f"geo.api.gouv.fr echoue pour '{city}': {e}")

    logger.warning(f"Impossible de trouver le departement pour '{city}'")
    return ""


class SireneScraper:
    """Recherche d'etablissements actifs via l'API Sirene."""

    async def search(
        self,
        sector: str,
        city: str | None = None,
        departement: str | None = None,
        limit: int = 200,
        custom_naf: list[str] | None = None,
    ) -> list[dict]:
        """
        Recherche les etablissements actifs pour un secteur dans une zone.

        Args:
            sector: nom du secteur (ex: "restaurant")
            city: ville (optionnel, converti en code departement)
            departement: code departement 2 chiffres (ex: "69")
            limit: nombre max de resultats
            custom_naf: codes NAF supplementaires

        Returns:
            liste de dicts {name, address, siret, naf_code, city, ...}
        """
        naf_codes = get_naf_codes(sector, custom_naf)
        if not naf_codes:
            logger.warning(f"Aucun code NAF pour le secteur '{sector}'")
            return []

        # Convertir ville en departement si pas de departement explicite
        if city and not departement:
            departement = city_to_department(city)

        all_results: list[dict] = []

        for naf_code in naf_codes:
            if len(all_results) >= limit:
                break

            remaining = limit - len(all_results)
            results = await self._search_by_naf(
                naf_code=naf_code,
                departement=departement,
                limit=min(remaining, SIRENE_MAX_RESULTS),
            )
            all_results.extend(results)

        # Deduplication par SIRET
        seen_siret: set[str] = set()
        unique: list[dict] = []
        for r in all_results:
            siret = r.get("siret", "")
            if siret and siret not in seen_siret:
                seen_siret.add(siret)
                unique.append(r)

        logger.info(f"Sirene: {len(unique)} etablissements actifs trouves pour '{sector}' ({city or departement or 'France'})")
        return unique[:limit]

    async def _search_by_naf(
        self,
        naf_code: str,
        departement: str | None,
        limit: int,
    ) -> list[dict]:
        """Pagination automatique sur un code NAF."""
        results: list[dict] = []
        page = 1
        max_pages = (limit // SIRENE_MAX_PER_PAGE) + 1

        async with httpx.AsyncClient(timeout=SIRENE_TIMEOUT) as client:
            while len(results) < limit and page <= max_pages:
                params: dict = {
                    "activite_principale": naf_code,
                    "etat_administratif": "A",  # Actif uniquement
                    "per_page": SIRENE_MAX_PER_PAGE,
                    "page": page,
                }

                # Filtre geographique par departement uniquement
                if departement:
                    params["departement"] = departement

                try:
                    resp = await client.get(SIRENE_API_URL, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.HTTPStatusError as e:
                    logger.error(f"Sirene API erreur {e.response.status_code} pour NAF {naf_code}: {e.response.text[:200]}")
                    break
                except (httpx.TimeoutException, httpx.ConnectError) as e:
                    logger.error(f"Sirene API timeout/connexion pour NAF {naf_code}: {e}")
                    break

                entreprises = data.get("results", [])
                if not entreprises:
                    break

                for ent in entreprises:
                    parsed = self._parse_entreprise(ent)
                    if parsed:
                        # Post-filtre : vérifier que le code postal correspond au département
                        if departement and not self._matches_department(parsed.get("postal_code", ""), departement):
                            continue
                        results.append(parsed)

                total_results = data.get("total_results", 0)
                if page * SIRENE_MAX_PER_PAGE >= total_results:
                    break

                page += 1
                # Rate limiting : 7 req/s max
                await asyncio.sleep(0.15)

        return results

    @staticmethod
    def _matches_department(postal_code: str, departement: str) -> bool:
        """Vérifie que le code postal correspond au département demandé."""
        if not postal_code or not departement:
            return True
        # DOM-TOM : départements 3 chiffres (971, 972, 973, 974, 976)
        if len(departement) == 3:
            return postal_code.startswith(departement)
        # Corse : 2A = 20000-20190, 2B = 20200-20290
        if departement in ("2A", "2B"):
            return postal_code.startswith("20")
        # Métropole : les 2 premiers chiffres du CP = département
        return postal_code[:2] == departement

    @staticmethod
    def _parse_entreprise(raw: dict) -> dict | None:
        """Parse un resultat Sirene en dict standardise."""
        nom = raw.get("nom_complet", "")
        if not nom:
            return None

        # Siege social
        siege = raw.get("siege", {})
        if not siege:
            return None

        siret = siege.get("siret", "")
        adresse_parts = [
            siege.get("numero_voie", ""),
            siege.get("type_voie", ""),
            siege.get("libelle_voie", ""),
        ]
        adresse = " ".join(p for p in adresse_parts if p).strip()
        code_postal = siege.get("code_postal", "")
        commune = siege.get("libelle_commune", "")

        # Activite
        activite = siege.get("activite_principale", "")

        return {
            "name": nom,
            "siret": siret,
            "address": adresse,
            "postal_code": code_postal,
            "city": commune,
            "naf_code": activite,
            "source": "sirene",
            # Champs enrichis plus tard
            "phone": None,
            "website": None,
            "email": None,
            "instagram": None,
            "facebook": None,
        }
