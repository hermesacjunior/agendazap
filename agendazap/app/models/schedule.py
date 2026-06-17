from sqlalchemy import Column, String, Boolean, DateTime, Time, Integer, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.database import Base


class Schedule(Base):
    """Configuração de disponibilidade do admin"""
    __tablename__ = "schedules"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String(100), default="Minha Agenda")
    slot_duration = Column(Integer, default=60)  # minutos
    buffer_time = Column(Integer, default=0)      # minutos entre agendamentos
    max_advance_days = Column(Integer, default=30) # dias máx no futuro
    is_active = Column(Boolean, default=True)

    # Disponibilidade semanal: {"0": [{"start": "09:00", "end": "18:00"}], ...}
    # 0=segunda, 1=terça, ..., 6=domingo
    weekly_availability = Column(JSON, default=dict)

    # Datas bloqueadas manualmente
    blocked_dates = Column(JSON, default=list)

    # Token para compartilhar uma visualizacao read-only desta agenda (sem
    # expor dados dos clientes). Nulo = nao compartilhada.
    share_token = Column(String(64), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="schedules")
    bookings = relationship("Booking", back_populates="schedule", cascade="all, delete-orphan")
