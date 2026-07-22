from sqlalchemy import Column, Integer, String, Date, ForeignKey
from sqlalchemy.sql import func
from core.database import Base # O de donde importes tu Base de SQLAlchemy

class Usuario(Base):
    __tablename__ = "usuario"

    id_usuario = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    correo = Column(String(100), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)
    fecha_registro = Column(Date, server_default=func.current_date())
    tipo_discapacidad = Column(Integer, ForeignKey("tipodiscapacidad.id_tipodiscapacidad"), nullable=True)