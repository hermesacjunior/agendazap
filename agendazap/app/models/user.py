from sqlalchemy import Column, String, Boolean, DateTime, Text, Enum as SAEnum
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
    is_active = Column(Boolean, default=True)
    plan = Column(SAEnum(PlanType), default=PlanType.free)
    stripe_customer_id = Column(String(100), nullable=True)
    stripe_subscription_id = Column(String(100), nullable=True)
    evolution_instance = Column(String(100), nullable=True)
    whatsapp_connected = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    schedules = relationship("Schedule", back_populates="user", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="user", cascade="all, delete-orphan")
