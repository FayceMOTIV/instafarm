"""
Catalogue niches — endpoints publics (pas de tenant auth).
Liste les 20 niches configurees + stats Sirene live.
"""

import httpx
from fastapi import APIRouter, Query

from backend.scrapers.niches_config import (
    NICHES,
    get_gold_source,
    get_naf_codes,
    list_all_niches,
)

router = APIRouter(prefix="/api/catalog", tags=["catalog"])

NICHE_EMOJIS = {
    "restaurant": "\U0001F37D\uFE0F",
    "dentiste": "\U0001F9B7",
    "coiffeur": "\U0001F487",
    "beaute": "\U0001F485",
    "garage": "\U0001F527",
    "btp": "\U0001F3D7\uFE0F",
    "immobilier": "\U0001F3E0",
    "avocat": "\u2696\uFE0F",
    "sport": "\U0001F3CB\uFE0F",
    "veterinaire": "\U0001F43E",
    "formation": "\U0001F393",
    "pharmacie": "\U0001F48A",
    "auto_ecole": "\U0001F697",
    "hotel": "\U0001F3E8",
    "decoration": "\U0001F3A8",
    "traiteur": "\U0001F355",
    "bienetre": "\U0001F9D8",
    "photographe": "\U0001F4F8",
    "depannage": "\U0001F6BF",
    "boulangerie": "\U0001F35E",
}

SIRENE_API_URL = "https://recherche-entreprises.api.gouv.fr/search"
SIRENE_TIMEOUT = 15


@router.get("/niches")
async def catalog_niches():
    """Retourne les 20 niches configurees avec source gold et info IG direct."""
    niches = []
    for key, config in NICHES.items():
        gold = get_gold_source(key)
        gold_name = gold["name"] if gold else "sirene"
        ig_direct = gold.get("returns_instagram", False) if gold else False

        niches.append({
            "key": key,
            "label": config["label"],
            "emoji": NICHE_EMOJIS.get(key, ""),
            "gold_source": gold_name,
            "instagram_direct": ig_direct,
            "naf_codes": config["naf_codes"],
            "sources_count": len(config["sources"]),
            "min_followers": config["instagram_min_followers"],
            "max_followers": config["instagram_max_followers"],
        })

    return {"niches": niches}


@router.get("/niches/{sector}/stats")
async def catalog_niche_stats(
    sector: str,
    city: str = Query(default="", description="Ville pour filtrer"),
    department: str = Query(default="", description="Code departement 2 chiffres"),
):
    """Appelle SIRENE en live pour compter les etablissements actifs."""
    if sector not in NICHES:
        return {"error": f"Niche '{sector}' non trouvee", "available": list(NICHES.keys())}

    config = NICHES[sector]
    naf_codes = config["naf_codes"]
    gold = get_gold_source(sector)
    gold_name = gold["name"] if gold else "sirene"
    ig_direct = gold.get("returns_instagram", False) if gold else False

    # Requete Sirene sur le premier code NAF
    total = 0
    naf_used = naf_codes[0] if naf_codes else ""

    if naf_used:
        params = {
            "activite_principale": naf_used,
            "etat_administratif": "A",
            "per_page": 1,
        }
        if department:
            params["departement"] = department
        if city:
            params["q"] = city

        try:
            async with httpx.AsyncClient(timeout=SIRENE_TIMEOUT) as client:
                resp = await client.get(SIRENE_API_URL, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    total = data.get("total_results", 0)
        except Exception:
            total = 0

    # Estimation Instagram : ~20% sans IG direct, ~40% avec
    ig_pct = 0.40 if ig_direct else 0.20
    estimated_ig = int(total * ig_pct)

    return {
        "sector": sector,
        "label": config["label"],
        "city": city or None,
        "department": department or None,
        "total_establishments": total,
        "naf_code": naf_used,
        "gold_source": gold_name,
        "instagram_direct": ig_direct,
        "estimated_with_instagram": estimated_ig,
        "sources_count": len(config["sources"]),
    }
