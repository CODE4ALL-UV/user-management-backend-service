from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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


class CourseOverride(Base):
    """Lo que el docente ha cambiado del curso.

    Aqui solo se guarda lo *editado*, no el curso entero. El temario de fabrica
    sigue viviendo dentro de la aplicacion, asi que si este servidor se cae el
    estudiante sigue viendo el curso completo: simplemente vera la version
    original en lugar de la editada.

    `scope` dice que se edito: 'section' para el contenido de una seccion o
    'module' para el nombre de un modulo. `target_id` es 'm1-s1' o '1'.
    `payload` lleva el JSON con lo editado.
    """

    __tablename__ = "CourseOverride"
    __table_args__ = (UniqueConstraint("scope", "target_id", name="uq_course_override"),)

    id = Column(Integer, primary_key=True, index=True)
    scope = Column(String(20), nullable=False, index=True)
    target_id = Column(String(60), nullable=False, index=True)
    payload = Column(Text, nullable=False)

    # Quien y cuando, para poder rendir cuentas de un cambio en el temario.
    updated_by = Column(String(100), nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class QuizAnswer(Base):
    """Cada respuesta que da un estudiante, una fila por pregunta.

    Guardar la respuesta suelta, y no solo la nota final, es lo que permite
    responder la pregunta que de verdad le importa al docente: *que pregunta
    concreta esta fallando todo el mundo*. Con una nota media por leccion se
    sabe que algo va mal, pero no que.

    No se guarda **que** contesto el estudiante, solo si acerto. Para saber
    que tema cuesta mas no hace falta mas, y guardar menos datos personales de
    los necesarios es lo correcto.
    """

    __tablename__ = "QuizAnswer"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("Usuario.id_usuario"), nullable=True, index=True)

    # Donde estaba la pregunta.
    section_id = Column(String(40), nullable=False, index=True)
    activity = Column(String(20), nullable=False, index=True)
    question_index = Column(Integer, nullable=False)

    # El enunciado se copia tal cual estaba al responder. Si el docente lo
    # cambia luego, lo ya respondido sigue diciendo a que se contestaba.
    prompt = Column(String(500), nullable=False, server_default="")

    correct = Column(Boolean, nullable=False)

    # Cuanto tardo en contestar, en milisegundos. Es nulo en lo registrado
    # antes de que se midiera, asi que al promediar hay que descartar los
    # nulos en vez de contarlos como cero.
    elapsed_ms = Column(Integer, nullable=True)

    answered_at = Column(DateTime, server_default=func.now(), index=True)


class ActivityCompletion(Base):
    """Cada actividad que un estudiante termina.

    Con QuizAnswer se sabe *que se falla*; con esto se sabe *hasta donde ha
    llegado cada uno*. Son preguntas distintas y el docente necesita las dos:
    un tema con mal porcentaje puede ser dificil, o puede ser que solo lo
    hayan hecho tres personas.

    Una fila por estudiante y actividad: terminar dos veces la misma lectura
    no cuenta dos veces, porque lo que importa es si la hizo, no cuantas.
    """

    __tablename__ = "ActivityCompletion"
    __table_args__ = (
        UniqueConstraint(
            "usuario_id", "section_id", "activity", name="uq_activity_completion"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("Usuario.id_usuario"), nullable=True, index=True)

    section_id = Column(String(40), nullable=False, index=True)
    activity = Column(String(20), nullable=False, index=True)

    completed_at = Column(DateTime, server_default=func.now(), index=True)


class TeacherReview(Base):
    """La valoracion que el director hace del trabajo de un docente.

    Se guarda el historico, no solo la ultima: el sentido de evaluar a alguien
    es poder ver si mejora. Sobrescribir la anterior borraria justo eso.

    El comentario es lo que de verdad sirve al docente; la nota sola no dice
    que hacer distinto. Por eso el comentario se guarda siempre junto a ella.
    """

    __tablename__ = "TeacherReview"

    id = Column(Integer, primary_key=True, index=True)
    docente_id = Column(Integer, ForeignKey("Usuario.id_usuario"), nullable=False, index=True)
    director_id = Column(Integer, ForeignKey("Usuario.id_usuario"), nullable=True)

    # De 1 a 5. Se comprueba en la ruta, no aqui, para poder dar un mensaje en
    # castellano en vez de un error de base de datos.
    score = Column(Integer, nullable=False)
    comment = Column(Text, nullable=False, server_default="")

    created_at = Column(DateTime, server_default=func.now(), index=True)


class ContentReview(Base):
    """Lo que el director opina del contenido de una seccion.

    Una sola fila por seccion: aqui lo que importa es el estado actual —si el
    contenido esta aprobado o tiene observaciones pendientes— no la historia.

    Guarda tambien **cuando** se reviso, para saber si la revision es anterior
    al ultimo cambio del docente. Un "aprobado" de antes de que se reescribiera
    la seccion no vale de nada, y decirlo es mas util que esconderlo.
    """

    __tablename__ = "ContentReview"
    __table_args__ = (UniqueConstraint("section_id", name="uq_content_review_section"),)

    id = Column(Integer, primary_key=True, index=True)
    section_id = Column(String(40), nullable=False, index=True)

    # 'aprobado' o 'observado'.
    status = Column(String(20), nullable=False)
    comment = Column(Text, nullable=False, server_default="")

    director_id = Column(Integer, ForeignKey("Usuario.id_usuario"), nullable=True)
    reviewed_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
