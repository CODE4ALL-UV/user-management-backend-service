from typing import Optional, Any
from sqlalchemy.orm import Session
from domain.repositories.user_repository import UserRepository

# IMPORTANTE: Importamos tu modelo real de SQLAlchemy que apunta a la tabla "usuario"
# Asegúrate de ajustar esta ruta según dónde hayas creado tu clase Usuario
from infrastructure.database.models import Usuario, TipoDiscapacidad  # O desde donde tengas tu modelo
from infrastructure.database.models import StudentPerformance

class UserRepositoryImpl(UserRepository):
    def __init__(self, db_session: Session):
        self.db = db_session

    def get_user_by_email(self, email: str) -> Optional[Any]:
        """Busca un usuario en NeonDB usando la columna 'correo'."""
        return self.db.query(Usuario).filter(Usuario.correo == email).first()

    def get_user_by_id(self, user_id: int) -> Optional[Any]:
        return self.db.query(Usuario).filter(Usuario.id_usuario == user_id).first()

    def list_students(self) -> list[Usuario]:
        """Devuelve todos los usuarios cuyo rol sea 'estudiante'."""
        return self.db.query(Usuario).filter(Usuario.rol == 'estudiante').all()

    # StudentPerformance methods
    def create_performance(self, performance_data: dict) -> Any:
        new = StudentPerformance(**performance_data)
        self.db.add(new)
        self.db.commit()
        self.db.refresh(new)
        return new

    def get_all_performances(self) -> list[StudentPerformance]:
        return self.db.query(StudentPerformance).order_by(StudentPerformance.created_at.desc()).all()

    def get_performances_by_student(self, usuario_id: int) -> list[StudentPerformance]:
        return self.db.query(StudentPerformance).filter(StudentPerformance.usuario_id == usuario_id).all()

    def aggregate_by_lesson(self) -> list[dict]:
        """Retorna agregados simples por lección: suma de score, failed, good, excellent."""
        from sqlalchemy import func

        rows = (
            self.db.query(
                StudentPerformance.lesson_name,
                func.sum(StudentPerformance.score).label('score'),
                func.sum(StudentPerformance.failed).label('failed'),
                func.sum(StudentPerformance.good).label('good'),
                func.sum(StudentPerformance.excellent).label('excellent'),
            )
            .group_by(StudentPerformance.lesson_name)
            .all()
        )

        return [
            {
                "lesson_name": r.lesson_name,
                "score": int(r.score or 0),
                "failed": int(r.failed or 0),
                "good": int(r.good or 0),
                "excellent": int(r.excellent or 0),
            }
            for r in rows
        ]

    def aggregate_avg_by_lesson(self) -> list[dict]:
        """Retorna promedio por lección: avg score, cantidad de registros y cantidad de estudiantes únicos."""
        from sqlalchemy import func, distinct

        rows = (
            self.db.query(
                StudentPerformance.lesson_name,
                func.avg(StudentPerformance.score).label('avg_score'),
                func.avg(StudentPerformance.failed).label('avg_failed'),
                func.avg(StudentPerformance.good).label('avg_good'),
                func.avg(StudentPerformance.excellent).label('avg_excellent'),
                func.count(StudentPerformance.id).label('records'),
                func.count(distinct(StudentPerformance.usuario_id)).label('students'),
            )
            .group_by(StudentPerformance.lesson_name)
            .all()
        )

        return [
            {
                "lesson_name": r.lesson_name,
                "avg_score": float(r.avg_score) if r.avg_score is not None else 0.0,
                "avg_failed": float(r.avg_failed) if r.avg_failed is not None else 0.0,
                "avg_good": float(r.avg_good) if r.avg_good is not None else 0.0,
                "avg_excellent": float(r.avg_excellent) if r.avg_excellent is not None else 0.0,
                "records": int(r.records or 0),
                "students": int(r.students or 0),
            }
            for r in rows
        ]

    def get_tipo_discapacidad_by_id(self, tipo_id: int) -> Optional[Any]:
        """Busca si el tipo de discapacidad existe en la tabla TipoDiscapacidad."""
        return self.db.query(TipoDiscapacidad).filter(TipoDiscapacidad.id_tipo == tipo_id).first()

    def create_user(self, user_data: dict) -> Any:
        """Guarda un nuevo usuario en la tabla 'usuario' en NeonDB."""
        new_user = Usuario(**user_data)
        self.db.add(new_user)
        self.db.commit()
        self.db.refresh(new_user)
        return new_user

    def update_photo_path(self, user_id: int, photo_path: str) -> Any:
        user = self.db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
        if not user:
            raise ValueError("Usuario no encontrado")

        user.foto_path = photo_path
        self.db.commit()
        self.db.refresh(user)
        return user