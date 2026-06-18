from sqlalchemy import Column, String, Boolean, DateTime, Integer, Text, Enum as SAEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum

from app.database import Base


class PlanType(str, enum.Enum):
    free = "free"
    basic = "basic"
    pro = "pro"


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)
    email = Column(String(200), unique=True, nullable=False, index=True)
    hashed_password = Column(String(200), nullable=False)
    whatsapp = Column(String(20), nullable=True)
    slug = Column(String(50), unique=True, nullable=False, index=True)
    bio = Column(Text, nullable=True)
    # Foto de perfil como data URL (data:image/...;base64,...). Redimensionada
    # no cliente (<=256px) antes do upload, entao cabe no limite de corpo e
    # respeita a CSP (img-src 'self' data:). Aparece na agenda publica.
    avatar = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    is_superadmin = Column(Boolean, default=False, nullable=False)
    # Incrementado ao trocar a senha: invalida todos os JWTs antigos (logout
    # global) e torna o token de reset de uso unico.
    token_version = Column(Integer, default=0, nullable=False, server_default="0")
    # native_enum=False stores as VARCHAR+CHECK (no native PG type), so asyncpg
    # needs no custom-type introspection — required for the Supabase transaction pooler.
    plan = Column(SAEnum(PlanType, native_enum=False, length=5), default=PlanType.free)
    stripe_customer_id = Column(String(100), nullable=True)
    stripe_subscription_id = Column(String(100), nullable=True)
    evolution_instance = Column(String(100), nullable=True)
    whatsapp_connected = Column(Boolean, default=False)
    # Notificacoes por e-mail para o dono da agenda (novos agendamentos /
    # cancelamentos). Ativo por padrao.
    email_notifications = Column(Boolean, default=True, nullable=False, server_default="true")

    # Resumo diario dos compromissos do dia (opt-in). Canais e horario locais.
    daily_digest_enabled = Column(Boolean, default=False, nullable=False, server_default="false")
    daily_digest_hour = Column(Integer, default=7, nullable=False, server_default="7")
    daily_digest_email = Column(Boolean, default=True, nullable=False, server_default="true")
    daily_digest_whatsapp = Column(Boolean, default=False, nullable=False, server_default="false")
    # Data (YYYY-MM-DD) do ultimo envio, para nao duplicar no mesmo dia.
    daily_digest_last_sent = Column(String(10), nullable=True)

    # Lembrete enviado ao CLIENTE X horas antes do agendamento (opt-in).
    reminder_enabled = Column(Boolean, default=False, nullable=False, server_default="false")
    reminder_hours = Column(Integer, default=24, nullable=False, server_default="24")
    reminder_email = Column(Boolean, default=True, nullable=False, server_default="true")
    reminder_whatsapp = Column(Boolean, default=False, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    schedules = relationship("Schedule", back_populates="user", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="user", cascade="all, delete-orphan")
