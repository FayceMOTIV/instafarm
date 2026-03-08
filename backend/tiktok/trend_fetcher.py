"""Fetcher de hashtags trending TikTok FR par niche."""

from backend.tiktok.config import TIKTOK_NICHE_CONFIG

# Hashtags statiques par niche — mis a jour manuellement
# En prod, scraper TikTok Discover page pour les vrais trending
STATIC_HASHTAGS = {
    "restauration": [
        "#restaurant", "#restaurateur", "#restauration", "#chef",
        "#gastronomie", "#foodfrance", "#restofrance", "#cuisine",
        "#gestionrestaurant", "#prodelarestauration",
    ],
    "coiffure": [
        "#coiffure", "#coiffeur", "#salondecoiffure", "#beaute",
        "#coiffurefrance", "#cheveux", "#balayage", "#coloriste",
        "#tendancecoiffure", "#salonpro",
    ],
    "btp_artisan": [
        "#artisan", "#btp", "#renovation", "#artisanat",
        "#chantier", "#batiment", "#plombier", "#electricien",
        "#macon", "#artisanfrance",
    ],
    "dentiste": [
        "#dentiste", "#cabinetdentaire", "#sante", "#orthodontie",
        "#implant", "#sourire", "#santebuccodentaire", "#medecin",
        "#cliniquedentaire", "#parodontologie",
    ],
    "auto_garage": [
        "#garage", "#garagiste", "#mecanique", "#automobile",
        "#reparationauto", "#entretien", "#voiture", "#mecano",
        "#garagefrance", "#autorepair",
    ],
    "sport_fitness": [
        "#fitness", "#coaching", "#sport", "#musculation",
        "#coachsportif", "#coachingenligne", "#salledesport",
        "#transformation", "#fitfrance", "#coachfrance",
    ],
    "immobilier": [
        "#immobilier", "#immo", "#agentimmobilier", "#mandataire",
        "#immobilierfrance", "#investissement", "#maison",
        "#appartement", "#mandatimmobilier", "#immopro",
    ],
    "photographe": [
        "#photographe", "#photographie", "#portrait", "#studio",
        "#photographefrance", "#seancephoto", "#artphoto",
        "#photographepro", "#shooting", "#photostudio",
    ],
}


async def get_trending_hashtags_fr(niche: str, limit: int = 8) -> list[str]:
    """Retourne les hashtags trending pour une niche.

    Pour l'instant : hashtags statiques pre-configures.
    TODO: scraper TikTok Discover page pour les vrais trending.
    """
    tags = STATIC_HASHTAGS.get(niche, ["#business", "#entrepreneur", "#france"])
    return tags[:limit]
