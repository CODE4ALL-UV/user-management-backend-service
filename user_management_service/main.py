"""Arranca solo este microservicio, sin el gateway.

Sirve para desarrollarlo o desplegarlo por separado. En producción lo monta el
API Gateway (repo Back-end) junto a los demás. Necesita neon-storage clonado al
lado y en el PYTHONPATH:

    uvicorn user_management_service.main:app --reload
"""

import os
from dotenv import load_dotenv

# El .env de este repositorio, antes de importar nada que lea variables.
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from neon_storage import prepare_database
from user_management_service.routes import register

prepare_database()

app = FastAPI(title="User Management Service", version="1.0.0")

# Desde qué páginas puede un navegador llamar a este API: la web publicada en
# Render y, para desarrollar, localhost en cualquier puerto. CORS_ORIGINS
# (separados por comas) añade otros sin tocar el código, por ejemplo un
# dominio propio. Antes era "*" con credenciales, que el navegador traduce en
# «cualquier página puede llamar en nombre del usuario».
#
# Sin credenciales: la sesión viaja en la cabecera Authorization, no en
# cookies, así que no hacen falta.
CORS_ORIGINS = ["https://code4all-web.onrender.com"] + [
    origin.strip().rstrip("/")
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

register(app)
