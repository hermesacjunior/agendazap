from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
import uuid

from app.database import Base


class PushSubscription(Base):
    """Inscricao de Web Push de um dispositivo do usuario (PWA instalado).

    Guarda o endpoint do navegador + as chaves para criptografar o payload.
    Um usuario pode ter varios dispositivos. Endpoints expirados (404/410) sao
    removidos automaticamente no envio.
    """
    __tablename__ = "push_subscriptions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint = Column(Text, unique=True, nullable=False)
    p256dh = Column(Text, nullable=False)
    auth = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
