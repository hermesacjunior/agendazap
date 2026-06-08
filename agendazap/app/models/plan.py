from sqlalchemy import Column, String, Integer, Boolean, Float, JSON
from sqlalchemy.sql import func
from sqlalchemy import DateTime
import uuid

from app.database import Base


class Plan(Base):
    __tablename__ = "plans"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(50), nullable=False)           # "Free", "Basic", "Pro"
    slug = Column(String(20), unique=True, nullable=False)
    price_brl = Column(Float, default=0.0)
    stripe_price_id = Column(String(100), nullable=True)
    max_bookings_month = Column(Integer, default=10)
    max_schedules = Column(Integer, default=1)
    whatsapp_notifications = Column(Boolean, default=False)
    email_notifications = Column(Boolean, default=True)
    custom_slug = Column(Boolean, default=False)
    features = Column(JSON, default=list)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
