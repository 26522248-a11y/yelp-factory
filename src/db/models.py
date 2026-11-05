"""Database models (section 5) plus the auxiliary tables the flow needs."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class AccountState(str, enum.Enum):
    NEW = "NEW"
    PROVISIONING = "PROVISIONING"
    PROXY_BOUND = "PROXY_BOUND"
    BROWSER_UP = "BROWSER_UP"
    PREWARMED = "PREWARMED"
    FORM_FILLED = "FORM_FILLED"
    CAPTCHA_SOLVED = "CAPTCHA_SOLVED"
    SUBMITTED = "SUBMITTED"
    EMAIL_PENDING = "EMAIL_PENDING"
    EMAIL_VERIFIED = "EMAIL_VERIFIED"
    PHONE_PENDING = "PHONE_PENDING"
    PHONE_VERIFIED = "PHONE_VERIFIED"
    ONBOARDED = "ONBOARDED"
    ACTIVE = "ACTIVE"
    WARMING = "WARMING"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"
    QUARANTINED = "QUARANTINED"
    DEAD = "DEAD"


class RunState(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    gpm_profile_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    proxy_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("proxies.id"))
    status: Mapped[str] = mapped_column(String(32), default="created", nullable=False)
    fingerprint_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Proxy(Base):
    __tablename__ = "proxies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    raw: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(32), default="residential", nullable=False)
    country: Mapped[str] = mapped_column(String(2), default="US", nullable=False)
    city: Mapped[str | None] = mapped_column(String(120))
    zip_prefixes: Mapped[list[str]] = mapped_column(ARRAY(String(16)), default=list, nullable=False)
    health: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    fail_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(String(24), default="auto", nullable=False)
    target_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="planned", nullable=False)
    config_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(String(400))


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("profile_id", name="uq_accounts_profile_id"),
        UniqueConstraint("email", name="uq_accounts_email"),
        Index("ix_accounts_state", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("batches.id"))
    profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("profiles.id"))
    email_pool_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("email_pool.id"))
    proxy_pool_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("proxy_pool.id"))
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    email_password_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    email_alias: Mapped[str | None] = mapped_column(String(320))
    phone_e164: Mapped[str | None] = mapped_column(String(32))
    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    zip: Mapped[str] = mapped_column(String(16), nullable=False)
    city: Mapped[str] = mapped_column(String(160), nullable=False)
    password_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    yelp_user_id: Mapped[str | None] = mapped_column(String(120))
    gender: Mapped[str | None] = mapped_column(String(24))
    birth_date: Mapped[str | None] = mapped_column(String(16))
    address_line: Mapped[str | None] = mapped_column(String(300))
    avatar_path: Mapped[str | None] = mapped_column(String(400))
    proxy_ip: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32), default=AccountState.NEW.value, nullable=False)
    substate: Mapped[str | None] = mapped_column(String(64))
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quarantine_reason: Mapped[str | None] = mapped_column(String(64))

    profile: Mapped[Profile | None] = relationship()


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        # Mỗi account tối đa 1 run RUNNING (E-26: dispatch trùng thì worker 2 exit sạch).
        Index(
            "uq_runs_one_running_per_account",
            "account_id",
            unique=True,
            postgresql_where=text("state = 'RUNNING'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="signup", nullable=False)
    state: Mapped[str] = mapped_column(String(32), default=RunState.PENDING.value, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(120))
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64))


class Step(Base):
    __tablename__ = "steps"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_steps_run_seq"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    artifact_prefix: Mapped[str | None] = mapped_column(String(400))


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_ts", "ts"), Index("ix_events_code", "code"))

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    level: Mapped[str] = mapped_column(String(16), default="info")
    account_id: Mapped[uuid.UUID | None] = mapped_column()
    run_id: Mapped[uuid.UUID | None] = mapped_column()
    code: Mapped[str | None] = mapped_column(String(16))
    msg: Mapped[str] = mapped_column(Text, default="")
    ctx: Mapped[dict] = mapped_column(JSONB, default=dict)


class WarmingPlan(Base):
    __tablename__ = "warming_plans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    phase: Mapped[int] = mapped_column(Integer, default=0)
    day: Mapped[int] = mapped_column(Integer, default=1)
    budget: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="active")


class WarmingTask(Base):
    __tablename__ = "warming_tasks"
    __table_args__ = (Index("ix_warming_tasks_due", "due_at", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warming_plans.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)


class SelectorRow(Base):
    __tablename__ = "selector_registry"
    __table_args__ = (UniqueConstraint("key", "strategy", "value", name="uq_selector_unique"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(24), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    page_tag: Mapped[str | None] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    miss_count: Mapped[int] = mapped_column(Integer, default=0)


class Quarantine(Base):
    __tablename__ = "quarantine"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --------------------------------------------------------------------------------------
# Auxiliary tables required by the edge-case matrix.
# --------------------------------------------------------------------------------------


class GPMOperation(Base):
    """Client-side idempotency for profiles/create (API v1 has no operation_id)."""

    __tablename__ = "gpm_operations"

    operation_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    gpm_profile_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AccountLock(Base):
    __tablename__ = "account_locks"

    account_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(120), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ttl_seconds: Mapped[int] = mapped_column(Integer, default=900)


class Zip(Base):
    __tablename__ = "zips"

    zip: Mapped[str] = mapped_column(String(16), primary_key=True)
    city: Mapped[str] = mapped_column(String(160), nullable=False)
    state: Mapped[str] = mapped_column(String(8), nullable=False)
    country: Mapped[str] = mapped_column(String(2), default="US")
    yelp_served: Mapped[bool] = mapped_column(Boolean, default=True)


class EmailDomain(Base):
    """Domain pool with the automatic 24h cool-down of E-45."""

    __tablename__ = "email_domains"

    domain: Mapped[str] = mapped_column(String(255), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    fail_streak: Mapped[int] = mapped_column(Integer, default=0)
    disabled_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SMSNumber(Base):
    __tablename__ = "sms_numbers"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    e164: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    area_code: Mapped[str] = mapped_column(String(8), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="smsapi")
    used_by_account: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.id"))
    state: Mapped[str] = mapped_column(String(24), default="available")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --------------------------------------------------------------------------------------
# Warming / trust (spec v1.0)
# --------------------------------------------------------------------------------------


class TrustScore(Base):
    __tablename__ = "trust_scores"
    __table_args__ = (Index("ix_trust_account_ts", "account_id", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    components: Mapped[dict] = mapped_column(JSONB, default=dict)


class ActionLog(Base):
    __tablename__ = "action_log"
    __table_args__ = (Index("ix_action_account_ts", "account_id", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column()
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    target: Mapped[str | None] = mapped_column(String(300))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)


class WarmingSession(Base):
    __tablename__ = "warming_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    plan_id: Mapped[uuid.UUID | None] = mapped_column()
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actions: Mapped[int] = mapped_column(Integer, default=0)
    entry_path: Mapped[str | None] = mapped_column(String(32))
    proxy_ip: Mapped[str | None] = mapped_column(String(64))
    trust_before: Mapped[int | None] = mapped_column(Integer)
    trust_after: Mapped[int | None] = mapped_column(Integer)


class ReviewAttempt(Base):
    __tablename__ = "review_attempts"
    __table_args__ = (Index("ix_review_account_biz", "account_id", "business_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    business_id: Mapped[str] = mapped_column(String(200), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    words: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    photo: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(24), default="submitted")
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    filtered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --------------------------------------------------------------------------------------
# Imported pools (email / proxy) - spec v1.1
# --------------------------------------------------------------------------------------


class EmailPool(Base):
    __tablename__ = "email_pool"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    mailbox_email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    mailbox_password_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    refresh_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    client_id: Mapped[str] = mapped_column(String(120), nullable=False)
    alias: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), default="available", nullable=False)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(300))
    source_file: Mapped[str | None] = mapped_column(String(300))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reserved_by: Mapped[uuid.UUID | None] = mapped_column()
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProxyPool(Base):
    __tablename__ = "proxy_pool"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    raw: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    kind: Mapped[str] = mapped_column(String(32), default="residential")
    country: Mapped[str | None] = mapped_column(String(2))
    city: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(24), default="available", nullable=False)
    accounts_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    last_probe_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_file: Mapped[str | None] = mapped_column(String(300))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reserved_by: Mapped[uuid.UUID | None] = mapped_column()
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

