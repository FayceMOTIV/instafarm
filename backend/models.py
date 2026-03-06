from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ===== MULTI-TENANT =====
class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    api_key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(String, default="war_machine")
    status: Mapped[str] = mapped_column(String, default="trial")
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    max_niches: Mapped[int] = mapped_column(Integer, default=10)
    max_accounts: Mapped[int] = mapped_column(Integer, default=30)
    max_dms_day: Mapped[int] = mapped_column(Integer, default=900)
    stripe_customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Relations
    niches: Mapped[list["Niche"]] = relationship(back_populates="tenant")
    ig_accounts: Mapped[list["IgAccount"]] = relationship(back_populates="tenant")
    proxies: Mapped[list["Proxy"]] = relationship(back_populates="tenant")
    prospects: Mapped[list["Prospect"]] = relationship(back_populates="tenant")
    messages: Mapped[list["Message"]] = relationship(back_populates="tenant")
    ab_variants: Mapped[list["AbVariant"]] = relationship(back_populates="tenant")
    webhooks: Mapped[list["Webhook"]] = relationship(back_populates="tenant")
    system_logs: Mapped[list["SystemLog"]] = relationship(back_populates="tenant")


# ===== NICHES =====
class Niche(Base):
    __tablename__ = "niches"
    __table_args__ = (Index("idx_niches_tenant", "tenant_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    emoji: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="active")
    # Ciblage
    hashtags: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    target_cities: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    target_account_count: Mapped[int] = mapped_column(Integer, default=3)
    # IA
    product_pitch: Mapped[str] = mapped_column(Text, nullable=False)
    dm_prompt_system: Mapped[str] = mapped_column(Text, nullable=False)
    dm_fallback_templates: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    scoring_vocab: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    # Stats
    total_scraped: Mapped[int] = mapped_column(Integer, default=0)
    total_dms_sent: Mapped[int] = mapped_column(Integer, default=0)
    total_responses: Mapped[int] = mapped_column(Integer, default=0)
    total_interested: Mapped[int] = mapped_column(Integer, default=0)
    response_rate: Mapped[float] = mapped_column(Float, default=0.0)
    best_send_hour: Mapped[int] = mapped_column(Integer, default=10)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relations
    tenant: Mapped["Tenant"] = relationship(back_populates="niches")
    ig_accounts: Mapped[list["IgAccount"]] = relationship(back_populates="niche")
    prospects: Mapped[list["Prospect"]] = relationship(back_populates="niche")
    ab_variants: Mapped[list["AbVariant"]] = relationship(back_populates="niche")


# ===== COMPTES INSTAGRAM =====
class IgAccount(Base):
    __tablename__ = "ig_accounts"
    __table_args__ = (Index("idx_ig_accounts_tenant_status", "tenant_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False)
    niche_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("niches.id"), nullable=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    proxy_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("proxies.id"), nullable=True)
    # Etat
    status: Mapped[str] = mapped_column(String, default="warmup")
    warmup_day: Mapped[int] = mapped_column(Integer, default=0)
    warmup_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Session Instagram
    session_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_action: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Fingerprint
    device_id: Mapped[str | None] = mapped_column(String, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String, nullable=True)
    # Quotas
    follows_today: Mapped[int] = mapped_column(Integer, default=0)
    dms_today: Mapped[int] = mapped_column(Integer, default=0)
    likes_today: Mapped[int] = mapped_column(Integer, default=0)
    quota_reset_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Stats
    total_follows: Mapped[int] = mapped_column(Integer, default=0)
    total_dms_sent: Mapped[int] = mapped_column(Integer, default=0)
    total_bans: Mapped[int] = mapped_column(Integer, default=0)
    # Anti-ban
    action_blocks_week: Mapped[int] = mapped_column(Integer, default=0)
    last_ban_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    personality: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    # Driver mode
    ig_driver: Mapped[str] = mapped_column(String, default="instagrapi")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relations
    tenant: Mapped["Tenant"] = relationship(back_populates="ig_accounts")
    niche: Mapped["Niche | None"] = relationship(back_populates="ig_accounts")
    proxy: Mapped["Proxy | None"] = relationship(back_populates="ig_accounts")
    messages: Mapped[list["Message"]] = relationship(back_populates="ig_account")


# ===== PROXIES =====
class Proxy(Base):
    __tablename__ = "proxies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False)
    host: Mapped[str] = mapped_column(String, nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    password: Mapped[str | None] = mapped_column(String, nullable=True)
    proxy_type: Mapped[str] = mapped_column(String, default="4g")
    location: Mapped[str] = mapped_column(String, default="FR")
    # Sante
    status: Mapped[str] = mapped_column(String, default="active")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    last_check: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Limites
    max_accounts: Mapped[int] = mapped_column(Integer, default=5)
    accounts_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relations
    tenant: Mapped["Tenant"] = relationship(back_populates="proxies")
    ig_accounts: Mapped[list["IgAccount"]] = relationship(back_populates="proxy")


# ===== PROSPECTS =====
class Prospect(Base):
    __tablename__ = "prospects"
    __table_args__ = (
        Index("idx_prospects_tenant_status", "tenant_id", "status"),
        Index("idx_prospects_instagram_id", "instagram_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False)
    niche_id: Mapped[int] = mapped_column(Integer, ForeignKey("niches.id"), nullable=False)
    # Identite Instagram
    instagram_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    followers: Mapped[int] = mapped_column(Integer, default=0)
    following: Mapped[int] = mapped_column(Integer, default=0)
    posts_count: Mapped[int] = mapped_column(Integer, default=0)
    has_link_in_bio: Mapped[bool] = mapped_column(Boolean, default=False)
    profile_pic_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Scoring IA
    score: Mapped[float] = mapped_column(Float, default=0.0)
    score_details: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    intent_signals: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    # Pipeline
    status: Mapped[str] = mapped_column(String, default="scraped")
    # Interactions
    followed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    follow_back_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_dm_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_dm_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_reply_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Qualif manuelle
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    rdv_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Anti-spam
    spam_reports: Mapped[int] = mapped_column(Integer, default=0)
    unfollow_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Geo
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    country: Mapped[str] = mapped_column(String, default="FR")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relations
    tenant: Mapped["Tenant"] = relationship(back_populates="prospects")
    niche: Mapped["Niche"] = relationship(back_populates="prospects")
    messages: Mapped[list["Message"]] = relationship(back_populates="prospect")


# ===== MESSAGES DMs =====
class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("idx_messages_prospect", "prospect_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False)
    prospect_id: Mapped[int] = mapped_column(Integer, ForeignKey("prospects.id"), nullable=False)
    ig_account_id: Mapped[int] = mapped_column(Integer, ForeignKey("ig_accounts.id"), nullable=False)
    # Contenu
    direction: Mapped[str] = mapped_column(String, nullable=False)  # outbound | inbound
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Metadonnees
    status: Mapped[str] = mapped_column(String, default="pending")
    ig_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # A/B Testing
    ab_variant: Mapped[str | None] = mapped_column(String, nullable=True)
    # Relances
    is_relance: Mapped[bool] = mapped_column(Boolean, default=False)
    relance_number: Mapped[int] = mapped_column(Integer, default=0)
    # IA
    generated_by: Mapped[str] = mapped_column(String, default="groq")
    groq_prompt_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Erreurs
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relations
    tenant: Mapped["Tenant"] = relationship(back_populates="messages")
    prospect: Mapped["Prospect"] = relationship(back_populates="messages")
    ig_account: Mapped["IgAccount"] = relationship(back_populates="messages")


# ===== AB TESTING VARIANTS =====
class AbVariant(Base):
    __tablename__ = "ab_variants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False)
    niche_id: Mapped[int] = mapped_column(Integer, ForeignKey("niches.id"), nullable=False)
    variant_letter: Mapped[str] = mapped_column(String, nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    is_winner: Mapped[bool] = mapped_column(Boolean, default=False)
    # Stats
    sends: Mapped[int] = mapped_column(Integer, default=0)
    responses: Mapped[int] = mapped_column(Integer, default=0)
    response_rate: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String, default="testing")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relations
    tenant: Mapped["Tenant"] = relationship(back_populates="ab_variants")
    niche: Mapped["Niche"] = relationship(back_populates="ab_variants")


# ===== WEBHOOKS SORTANTS =====
class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    events: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    secret: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")
    last_triggered: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relations
    tenant: Mapped["Tenant"] = relationship(back_populates="webhooks")


# ===== LOGS SYSTEME =====
class SystemLog(Base):
    __tablename__ = "system_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tenants.id"), nullable=True)
    level: Mapped[str] = mapped_column(String, nullable=False)
    module: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relations
    tenant: Mapped["Tenant | None"] = relationship(back_populates="system_logs")
