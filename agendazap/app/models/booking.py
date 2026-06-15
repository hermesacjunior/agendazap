from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum

from app.database import Base


class BookingStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"
    completed = "completed"


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    schedule_id = Column(String, ForeignKey("schedules.id"), nullable=False)

    # Dados do cliente
    client_name = Column(String(100), nullable=False)
    client_email = Column(String(200), nullable=False)
    client_whatsapp = Column(String(20), nullable=True)
    client_notes = Column(Text, nullable=True)

    # Horário
    start_datetime = Column(DateTime(timezone=True), nullable=False)
    end_datetime = Column(DateTime(timezone=True), nullable=False)

    # native_enum=False stores as VARCHAR+CHECK (no native PG type), so asyncpg
    # needs no custom-type introspection — required for the Supabase transaction pooler.
    status = Column(SAEnum(BookingStatus, native_enum=False, length=10), default=BookingStatus.confirmed)

    # Notificações enviadas
    whatsapp_sent_admin = Column(Boolean, default=False)
    whatsapp_sent_client = Column(Boolean, default=False)
    email_sent_admin = Column(Boolean, default=False)
    email_sent_client = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="bookings")
    schedule = relationship("Schedule", back_populates="bookings")
