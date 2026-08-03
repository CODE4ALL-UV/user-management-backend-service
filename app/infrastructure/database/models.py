from sqlalchemy import Column, Integer, String, Date, ForeignKey
from sqlalchemy.sql import func
from core.database import Base  # O de donde importes tu Base de SQLAlchemy


class TipoDiscapacidad(Base):
    __tablename__ = "TipoDiscapacidad"

    id_tipo = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(50), nullable=False)


class Usuario(Base):
    __tablename__ = "Usuario"

    id_usuario = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    correo = Column(String(100), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)
    fecha_registro = Column(Date, server_default=func.current_date())
    tipo_discapacidad = Column(Integer, ForeignKey("TipoDiscapacidad.id_tipo"), nullable=True)
    rol = Column(String(20), nullable=False, server_default="estudiante")
    foto_path = Column(String(500), nullable=True)


class StudentPerformance(Base):
    __tablename__ = "student_performance"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("Usuario.id_usuario"), nullable=True)
    lesson_name = Column(String(150), nullable=False)
    score = Column(Integer, nullable=False, server_default="0")
    failed = Column(Integer, nullable=False, server_default="0")
    good = Column(Integer, nullable=False, server_default="0")
    excellent = Column(Integer, nullable=False, server_default="0")
    created_at = Column(Date, server_default=func.current_date())