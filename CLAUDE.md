# ⚡ INSTAFARM WAR MACHINE — CLAUDE.md
# Mémoire persistante. LIS CE FICHIER EN ENTIER AVANT DE TOUCHER QUOI QUE CE SOIT.

---

## 🎯 QU'EST-CE QUE CE PROJET ?

InstaFarm est un bot Instagram B2B multi-niche qui :
1. Crée automatiquement des comptes Instagram (Playwright + SMS-activate)
2. Scrape des pros locaux (restaurants, dentistes, garagistes, etc.)
3. Score les prospects avec l'IA (TF-IDF + Groq)
4. Envoie des DMs ultra-personnalisés en masse
5. Gère les réponses via une PWA mobile
6. Tourne en SaaS multi-tenant (un serveur Oracle = 20+ clients)

**Objectif solo test (Phase 1)** : 10 niches, 30 comptes IG, ~680 DMs/jour, résultats en 4-6 semaines.
**Objectif SaaS (Phase 2)** : Clients à 99€/199€/349€/mois, marges 83-88%.

---

## 🏗️ ARCHITECTURE ABSOLUE (NE JAMAIS DÉROGER)

```
instafarm/
├── CLAUDE.md                    ← TU LIS ÇA EN PREMIER (ce fichier)
├── backend/
│   ├── main.py                  ← FastAPI app entry point
│   ├── database.py              ← SQLite WAL + connexion
│   ├── models.py                ← Tous les modèles SQLAlchemy
│   ├── middleware.py            ← Auth tenant_id + rate limiting
│   ├── routers/
│   │   ├── niches.py            ← CRUD niches
│   │   ├── accounts.py          ← Pool comptes IG
│   │   ├── prospects.py         ← Prospects + pipeline
│   │   ├── messages.py          ← Inbox + conversations
│   │   ├── analytics.py         ← Stats + dashboard
│   │   ├── admin.py             ← Super Admin (toi seul)
│   │   └── webhooks.py          ← Outbound webhooks
│   ├── bot/
│   │   ├── scheduler.py         ← asyncio.gather orchestrateur principal
│   │   ├── account_pool.py      ← Gestion pool comptes + round-robin
│   │   ├── account_creator.py   ← Playwright création + warmup 18j
│   │   ├── scraper.py           ← Apify scraping multi-source
│   │   ├── scorer.py            ← TF-IDF + Groq scoring 3 couches
│   │   ├── dm_engine.py         ← DM send + A/B testing + relances
│   │   ├── ig_client.py         ← Abstraction instagrapi/HikerAPI
│   │   ├── session_manager.py   ← Sessions JSON + challenge resolver
│   │   ├── anti_ban.py          ← Détection ban + comportements humains
│   │   └── watchdog.py          ← Auto-healing toutes les 5min
│   ├── services/
│   │   ├── groq_service.py      ← Toutes les calls Groq centralisées
│   │   ├── redis_service.py     ← Queues Redis + rate limiting
│   │   ├── proxy_service.py     ← Rotation proxies + health checks
│   │   ├── notification_service.py ← Push PWA + rapport matin
│   │   └── backup_service.py    ← SQLite → OCI Object Storage
│   └── seeds/
│       ├── seed_niches.py       ← 10 niches pré-configurées
│       └── seed_tenant.py       ← Créer tenant de test
├── pwa/
│   ├── index.html               ← Entry point PWA
│   ├── manifest.json            ← Config PWA installable
│   ├── sw.js                    ← Service Worker offline + push
│   ├── js/
│   │   ├── app.js               ← Router principal
│   │   ├── api.js               ← Toutes les calls API centralisées
│   │   ├── inbox.js             ← Inbox unifiée toutes niches
│   │   ├── dashboard.js         ← Stats + ROI dashboard
│   │   ├── pipeline.js          ← Kanban CRM
│   │   ├── control.js           ← Contrôle bot + niches
│   │   └── notifications.js     ← Push notifications handler
│   └── css/
│       └── app.css              ← Design dark pro
├── tests/
│   ├── test_session_1.py        ← Tests Session 1 (DB + seeds)
│   ├── test_session_2.py        ← Tests Session 2 (création comptes)
│   ├── test_session_3.py        ← Tests Session 3 (scraper + scoring)
│   ├── test_session_4.py        ← Tests Session 4 (DM engine)
│   ├── test_session_5.py        ← Tests Session 5 (scheduler + Redis)
│   ├── test_session_6.py        ← Tests Session 6 (API FastAPI)
│   └── test_session_7.py        ← Tests Session 7 (PWA)
├── .env                         ← Variables d'environnement (NE JAMAIS COMMIT)
├── .env.example                 ← Template variables
├── requirements.txt             ← Dépendances Python
├── docker-compose.yml           ← Redis + serveur local
└── deploy.sh                    ← Script déploiement Oracle
```

---

## 🗄️ SCHÉMA DATABASE COMPLET (SQLite WAL)

```sql
-- ===== MULTI-TENANT =====
CREATE TABLE tenants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    api_key TEXT UNIQUE NOT NULL,           -- UUID généré à la création
    plan TEXT DEFAULT 'war_machine',       -- starter | growth | war_machine
    status TEXT DEFAULT 'trial',           -- trial | active | suspended | deleted
    trial_ends_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- Limites selon plan
    max_niches INTEGER DEFAULT 10,
    max_accounts INTEGER DEFAULT 30,
    max_dms_day INTEGER DEFAULT 900,
    -- Stats billing
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT
);

-- ===== NICHES (cœur du système) =====
CREATE TABLE niches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    name TEXT NOT NULL,                    -- "Restaurants"
    emoji TEXT DEFAULT '🍽️',
    status TEXT DEFAULT 'active',          -- active | paused | creating
    -- Ciblage
    hashtags TEXT NOT NULL,               -- JSON array ["#restaurant", ...]
    target_cities TEXT DEFAULT '[]',      -- JSON array ["Lyon", "Paris", ...]
    target_account_count INTEGER DEFAULT 3,  -- nb comptes IG alloués
    -- IA
    product_pitch TEXT NOT NULL,          -- Description produit pour cette niche
    dm_prompt_system TEXT NOT NULL,       -- Prompt Groq pour générer DMs
    dm_fallback_templates TEXT NOT NULL,  -- JSON array 5 templates fallback
    scoring_vocab TEXT DEFAULT '[]',      -- JSON array mots-clés TF-IDF
    -- Stats
    total_scraped INTEGER DEFAULT 0,
    total_dms_sent INTEGER DEFAULT 0,
    total_responses INTEGER DEFAULT 0,
    total_interested INTEGER DEFAULT 0,
    response_rate REAL DEFAULT 0.0,
    best_send_hour INTEGER DEFAULT 10,    -- Appris par ML après 4 semaines
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ===== COMPTES INSTAGRAM =====
CREATE TABLE ig_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    niche_id INTEGER REFERENCES niches(id),
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    email TEXT,
    phone TEXT,                            -- Numéro SMS-activate
    proxy_id INTEGER REFERENCES proxies(id),
    -- État
    status TEXT DEFAULT 'warmup',          -- warmup | active | paused | banned | suspended
    warmup_day INTEGER DEFAULT 0,          -- Jour 0 à 18
    warmup_started_at DATETIME,
    -- Session Instagram
    session_data TEXT,                     -- JSON session instagrapi
    last_login DATETIME,
    last_action DATETIME,
    -- Fingerprint
    device_id TEXT,                        -- UUID unique par compte
    user_agent TEXT,
    -- Quotas
    follows_today INTEGER DEFAULT 0,
    dms_today INTEGER DEFAULT 0,
    likes_today INTEGER DEFAULT 0,
    quota_reset_at DATETIME,              -- Minuit Paris
    -- Stats
    total_follows INTEGER DEFAULT 0,
    total_dms_sent INTEGER DEFAULT 0,
    total_bans INTEGER DEFAULT 0,
    -- Anti-ban
    action_blocks_week INTEGER DEFAULT 0,
    last_ban_at DATETIME,
    personality TEXT DEFAULT '{}',        -- JSON: typing_speed, pause_min, pause_max, sleep_hour, wake_hour
    -- Driver mode
    ig_driver TEXT DEFAULT 'instagrapi',  -- instagrapi | hikerapi
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ===== PROXIES =====
CREATE TABLE proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    username TEXT,
    password TEXT,
    proxy_type TEXT DEFAULT '4g',          -- 4g | datacenter | residential
    location TEXT DEFAULT 'FR',
    -- Santé
    status TEXT DEFAULT 'active',          -- active | slow | dead
    latency_ms INTEGER DEFAULT 0,
    last_check DATETIME,
    -- Limites
    max_accounts INTEGER DEFAULT 5,        -- JAMAIS PLUS DE 5 COMPTES PAR PROXY
    accounts_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ===== PROSPECTS =====
CREATE TABLE prospects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    niche_id INTEGER NOT NULL REFERENCES niches(id),
    -- Identité Instagram
    instagram_id TEXT UNIQUE NOT NULL,    -- ID IG (clé de déduplication GLOBALE)
    username TEXT NOT NULL,
    full_name TEXT,
    bio TEXT,
    followers INTEGER DEFAULT 0,
    following INTEGER DEFAULT 0,
    posts_count INTEGER DEFAULT 0,
    has_link_in_bio BOOLEAN DEFAULT FALSE,
    profile_pic_url TEXT,
    -- Scoring IA
    score REAL DEFAULT 0.0,               -- 0.0 à 1.0
    score_details TEXT DEFAULT '{}',      -- JSON: tfidf_score, groq_score, intent_score
    intent_signals TEXT DEFAULT '{}',     -- JSON: account_age_days, last_post_days, engagement_rate, follower_growth
    -- Pipeline (statut dans le funnel)
    status TEXT DEFAULT 'scraped',        -- scraped | scored | followed | follow_back | dm_sent | replied | interested | rdv | converted | lost | blacklisted
    -- Interactions
    followed_at DATETIME,
    follow_back_at DATETIME,
    first_dm_at DATETIME,
    last_dm_at DATETIME,
    last_reply_at DATETIME,
    -- Qualif manuelle
    notes TEXT,
    tags TEXT DEFAULT '[]',               -- JSON array tags manuels
    rdv_date DATETIME,
    -- Anti-spam
    spam_reports INTEGER DEFAULT 0,
    unfollow_at DATETIME,
    -- Géo
    city TEXT,
    country TEXT DEFAULT 'FR',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ===== MESSAGES DMs =====
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    prospect_id INTEGER NOT NULL REFERENCES prospects(id),
    ig_account_id INTEGER NOT NULL REFERENCES ig_accounts(id),
    -- Contenu
    direction TEXT NOT NULL,              -- outbound | inbound
    content TEXT NOT NULL,
    -- Métadonnées
    status TEXT DEFAULT 'pending',        -- pending | sent | delivered | read | failed
    ig_message_id TEXT,                   -- ID côté Instagram
    -- A/B Testing
    ab_variant TEXT,                      -- A | B | C | D | E
    -- Relances
    is_relance BOOLEAN DEFAULT FALSE,
    relance_number INTEGER DEFAULT 0,     -- 1=D+7, 2=D+14, 3=D+21
    -- IA
    generated_by TEXT DEFAULT 'groq',     -- groq | fallback | manual | playbook
    groq_prompt_used TEXT,
    -- Erreurs
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    sent_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ===== AB TESTING VARIANTS =====
CREATE TABLE ab_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    niche_id INTEGER NOT NULL REFERENCES niches(id),
    variant_letter TEXT NOT NULL,          -- A | B | C | D | E
    template TEXT NOT NULL,
    is_winner BOOLEAN DEFAULT FALSE,
    -- Stats
    sends INTEGER DEFAULT 0,
    responses INTEGER DEFAULT 0,
    response_rate REAL DEFAULT 0.0,
    status TEXT DEFAULT 'testing',        -- testing | winner | paused
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ===== WEBHOOKS SORTANTS =====
CREATE TABLE webhooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    url TEXT NOT NULL,
    events TEXT NOT NULL,                 -- JSON: ["prospect.interested", "rdv.booked", ...]
    secret TEXT,                          -- HMAC signing
    status TEXT DEFAULT 'active',
    last_triggered DATETIME,
    fail_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ===== LOGS SYSTÈME =====
CREATE TABLE system_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER REFERENCES tenants(id),
    level TEXT NOT NULL,                  -- DEBUG | INFO | WARNING | ERROR | CRITICAL
    module TEXT NOT NULL,                 -- scheduler | dm_engine | scraper | etc.
    message TEXT NOT NULL,
    details TEXT DEFAULT '{}',           -- JSON extra data
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- INDEX CRITIQUES POUR PERFORMANCES
CREATE INDEX idx_prospects_tenant_status ON prospects(tenant_id, status);
CREATE INDEX idx_prospects_instagram_id ON prospects(instagram_id);
CREATE INDEX idx_messages_prospect ON messages(prospect_id);
CREATE INDEX idx_ig_accounts_tenant_status ON ig_accounts(tenant_id, status);
CREATE INDEX idx_niches_tenant ON niches(tenant_id);
```

---

## 🔑 VARIABLES D'ENVIRONNEMENT (.env)

```bash
# App
APP_ENV=development                    # development | production
SECRET_KEY=change_me_ultra_secure_key
ADMIN_TOKEN=your_super_admin_token     # Pour accéder à /admin

# Database
DATABASE_URL=sqlite:///./instafarm.db

# Redis
REDIS_URL=redis://localhost:6379/0

# Groq (gratuit jusqu'à 14400 req/jour)
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_FALLBACK_MODEL=llama-3.1-8b-instant

# Apify (scraping Instagram)
APIFY_TOKEN=apify_api_...
APIFY_ACTOR_HASHTAG=apify/instagram-hashtag-scraper
APIFY_ACTOR_PROFILE=apify/instagram-profile-scraper

# SMS-activate (création comptes)
SMS_ACTIVATE_KEY=...
SMS_ACTIVATE_SERVICE=ig                # Code service Instagram

# HikerAPI (Phase 2 - remplace instagrapi en prod)
HIKERAPI_KEY=                          # Laisser vide en Phase 1
HIKERAPI_ENDPOINT=https://api.hikerapi.com/v1

# 2captcha (création comptes)
TWOCAPTCHA_KEY=...

# OCI Backup
OCI_BUCKET_NAME=instafarm-backup
OCI_NAMESPACE=...
OCI_REGION=eu-frankfurt-1

# Notifications Push (Web Push VAPID)
VAPID_PUBLIC_KEY=...
VAPID_PRIVATE_KEY=...
VAPID_EMAIL=admin@instafarm.io

# Stripe (Phase 3)
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Oracle VM
ORACLE_HOST=your.oracle.vm.ip
ORACLE_USER=ubuntu
```

---

## 🚨 RÈGLES ABSOLUES — JAMAIS DÉROGER

### RÈGLE 1 — TESTS RÉELS OBLIGATOIRES
```
❌ INTERDIT : "Le code est écrit, ça devrait marcher"
✅ OBLIGATOIRE : Requête réelle → Réponse réelle → Rendu visible

Après CHAQUE module :
1. Lance le code
2. Montre la vraie sortie terminal / API response
3. Confirme que c'est le bon résultat attendu

CODE QUI EXISTE ≠ CODE QUI FONCTIONNE.
```

### RÈGLE 2 — ISOLATION TENANT ABSOLUE
```python
# TOUJOURS filtrer par tenant_id dans CHAQUE query
# JAMAIS de query sans WHERE tenant_id = ?
# JAMAIS d'accès croisé entre tenants

# ✅ CORRECT
prospects = db.query(Prospect).filter(
    Prospect.tenant_id == tenant_id,
    Prospect.status == "interested"
).all()

# ❌ INTERDIT
prospects = db.query(Prospect).all()
```

### RÈGLE 3 — PROXY STRICT
```python
# JAMAIS plus de 5 comptes par proxy
# Vérifier avant CHAQUE création de compte
assert proxy.accounts_count < proxy.max_accounts, "Proxy saturé"

# JAMAIS créer un compte sans proxy 4G
assert proxy.proxy_type == "4g", "Proxy datacenter interdit pour création"
```

### RÈGLE 4 — QUOTAS ANTI-BAN
```python
# Quotas MAXIMAUX par compte selon l'âge
QUOTAS = {
    "warmup_0_7":   {"follows": 5,  "dms": 0,  "likes": 10},
    "warmup_7_14":  {"follows": 10, "dms": 3,  "likes": 20},
    "warmup_14_18": {"follows": 15, "dms": 8,  "likes": 30},
    "active_young": {"follows": 20, "dms": 12, "likes": 50},  # 18-30j
    "active_mid":   {"follows": 30, "dms": 15, "likes": 60},  # 30-90j
    "active_old":   {"follows": 40, "dms": 20, "likes": 80},  # >90j
}

# Délais entre actions : JAMAIS moins de 8 minutes
# Heures d'activité : UNIQUEMENT 09h00-20h00 Paris (Europe/Paris)
# Jours OFF configurables par compte (simuler dimanche repos)
```

### RÈGLE 5 — GROQ EN DERNIER RECOURS UNIQUEMENT
```python
# TOUJOURS avoir un fallback template si Groq fail
# TOUJOURS wrapper les calls Groq dans try/except avec timeout 10s
# JAMAIS bloquer le scheduler si Groq est down
try:
    message = await groq_service.generate_dm(prospect, niche)
except Exception:
    message = random.choice(niche.dm_fallback_templates)
```

### RÈGLE 6 — LOGS OBLIGATOIRES
```python
# CHAQUE action importante doit être loggée en DB
# Format : module + action + résultat + tenant_id
await log(tenant_id, "INFO", "dm_engine", f"DM sent to @{username}", {"status": "delivered"})
```

### RÈGLE 7 — JAMAIS DE CREDENTIALS EN CLAIR DANS LE CODE
```python
# TOUJOURS depuis os.environ ou .env
# JAMAIS hardcoder clés API, mots de passe, tokens
import os
GROQ_API_KEY = os.environ["GROQ_API_KEY"]  # ✅
GROQ_API_KEY = "gsk_xxx"                   # ❌ INTERDIT
```

---

## 📦 DÉPENDANCES (requirements.txt)

```
# Web framework
fastapi==0.115.0
uvicorn[standard]==0.30.0
python-multipart==0.0.9

# Database
sqlalchemy==2.0.35
aiosqlite==0.20.0

# Redis
redis[asyncio]==5.1.0

# Instagram
instagrapi==2.1.2
playwright==1.47.0

# IA
groq==0.11.0
scikit-learn==1.5.2           # TF-IDF
numpy==1.26.4

# Scraping
apify-client==1.8.1

# SMS
requests==2.32.3

# Scheduling
apscheduler==3.10.4

# Crypto/Sécurité
passlib[bcrypt]==1.7.4
python-jose[cryptography]==3.3.0
pyotp==2.9.0

# Web Push Notifications
pywebpush==2.0.0

# Backup OCI
oci==2.130.0

# Utils
python-dotenv==1.0.1
pydantic==2.9.2
pydantic-settings==2.5.2
httpx==0.27.2
aiohttp==3.10.5
tenacity==9.0.0               # Retry logic
loguru==0.7.2                 # Logging pro
```

---

## 🤖 LES 10 NICHES PRÉ-CONFIGURÉES

| # | Niche | Emoji | Comptes | DMs/jour |
|---|-------|-------|---------|----------|
| 1 | Restaurants | 🍽️ | 3 | 60 |
| 2 | Dentistes | 🦷 | 3 | 60 |
| 3 | Garagistes | 🔧 | 3 | 60 |
| 4 | Coiffeurs | ✂️ | 3 | 60 |
| 5 | Pharmacies | 💊 | 3 | 60 |
| 6 | Avocats | ⚖️ | 3 | 60 |
| 7 | Architectes | 🏛️ | 3 | 60 |
| 8 | Vétérinaires | 🐾 | 3 | 60 |
| 9 | Opticiens | 👓 | 3 | 60 |
| 10 | Notaires | 📜 | 3 | 60 |

**Total : 30 comptes IG, ~680 DMs/jour (quotas sécurisés)**

---

## 🎯 LES FEATURES 58 — RÉSUMÉ PAR SESSION

```
SESSION 1 → F28 (DB + structure + seed 10 niches + backup)
SESSION 2 → F01-F07 (création comptes + warmup 18j + fingerprint)
SESSION 3 → F08-F14 (scraper Apify + scoring 3 couches + intent signals + géo)
SESSION 4 → F15-F22 (DM engine + A/B test + relances + playbook + 2-step)
SESSION 5 → F23-F27 + F44-F47 (anti-ban + scheduler + Redis queues + watchdog)
SESSION 6 → F29-F36 (API FastAPI complète + analytics + export CSV)
SESSION 7 → F37-F43 (PWA : inbox + kanban + IA suggestion + push notifs)
SESSION 8 → F43 + F52-F53 + déploiement Oracle (multi-tenant + admin + prod)
```

---

## 📊 STATUTS DU FUNNEL (dans l'ordre)

```
scraped → scored → followed → follow_back → dm_sent → replied → interested → rdv → converted
                                                                                  ↓
                                                                               lost / blacklisted
```

---

## ⚡ COMMANDES UTILES

```bash
# Lancer en dev
uvicorn backend.main:app --reload --port 8000

# Lancer Redis
redis-server

# Lancer le bot (scheduler)
python -m backend.bot.scheduler

# Seed la base de données
python -m backend.seeds.seed_niches
python -m backend.seeds.seed_tenant

# Tests
pytest tests/test_session_X.py -v

# Voir les logs en temps réel
tail -f instafarm.log

# Backup manuel
python -m backend.services.backup_service

# Accès Super Admin
# GET http://localhost:8000/admin?token=YOUR_ADMIN_TOKEN
```

---

## 🚀 ÉTAT D'AVANCEMENT (mis à jour par Claude Code)

```
SESSION 1 — DB + Seeds          → [✅ DONE - 2026-03-05]
SESSION 2 — Création comptes    → [✅ DONE - 2026-03-05]
SESSION 3 — Scraper + Scoring   → [✅ DONE - 2026-03-05]
SESSION 4 — DM Engine           → [✅ DONE - 2026-03-05]
SESSION 5 — Anti-ban + Scheduler → [✅ DONE - 2026-03-05]
SESSION 6 — API FastAPI          → [✅ DONE - 2026-03-05]
SESSION 7 — PWA                 → [✅ DONE - 2026-03-05]
SESSION 8 — Deploy Oracle        → [✅ DONE - 2026-03-05]
```

**À mettre à jour après chaque session réussie avec ✅ + date.**

---

## 💡 DÉCISIONS ARCHITECTURALES (POURQUOI)

**Pourquoi SQLite et pas PostgreSQL ?**
SQLite WAL suffit pour 20 clients sur Oracle ARM. Zero setup. Backup trivial. Si >50 clients → migration vers PostgreSQL en 1 journée.

**Pourquoi instagrapi en Phase 1 ?**
Gratuit. Fonctionnel pour test solo. Phase 2 → HikerAPI ($60/mois) car clients payants = zéro tolérance downtime.

**Pourquoi Groq et pas OpenAI ?**
Gratuit jusqu'à 14,400 req/jour. Llama-3.3-70b aussi bon que GPT-4o pour la génération de DMs. Fallback immédiat si down.

**Pourquoi PWA et pas app native ?**
Zéro soumission App Store. Installable sur iPhone/Android. Mise à jour instantanée. Claude Code peut tout builder sans Xcode.

**Pourquoi asyncio.gather pour le scheduler ?**
Toutes les niches tournent en VRAI parallèle. 10 niches = 10 tâches simultanées. Pas de queue séquentielle.

---

*Ce fichier est la loi. Si une décision dans le code contredit ce fichier → le code a tort.*
*Dernière mise à jour : Session 8 — Deploy Oracle ✅ — TOUTES SESSIONS TERMINÉES*
*STATUS FINAL : INSTAFARM WAR MACHINE PRETE POUR LA PRODUCTION*
