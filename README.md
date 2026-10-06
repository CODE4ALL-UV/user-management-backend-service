# user-management-backend-service
Repositorio Back-end para el modulo Gestión de Usuarios

Cuentas, inicio de sesión (correo y Google) y foto de perfil. Es también quien
firma los tokens de sesión: los demás microservicios los comprueban con
`user_management_service.auth`....

| Rutas | Para qué |
|---|---|
| `POST /api/auth/register`, `POST /api/auth/login` | Registro e inicio de sesión con correo. |
| `POST /api/auth/google` | Inicio de sesión con Google; crea la cuenta si no existe. |
| `POST /api/user/upload-photo` | Foto de perfil. |
| `GET /uploads/{archivo}` | Las fotos guardadas. |

**Tabla que escribe:** `Usuario`. Los modelos están en `neon-storage`.

## Transición: dos cosas en un repositorio

Mientras dura el paso a microservicios, aquí conviven:

- **`user_management_service/`**: el microservicio de usuarios. Es lo que monta
  el API Gateway (repo `Back-end`).
- **El monolito heredado**: `app/`, `main.py`, `Dockerfile` y `render.yaml`.
  Es lo que Render sigue desplegando como `code4all-api` hasta que la app
  pase al gateway.

**Los cambios se hacen en los paquetes nuevos, no en `app/`.** El monolito
queda congelado; se borra cuando `code4all-api` esté suspendido. Los pasos
están en el README de `Back-end`.

## Cómo lo monta el gateway

`user_management_service/routes.py` tiene `register(app)`, que añade las rutas
de este servicio a una aplicación de FastAPI. El gateway lo llama para cada
servicio, y `user_management_service/main.py` hace lo mismo para arrancarlo
solo.

## Correrlo solo

Hace falta `neon-storage` clonado al lado:

```powershell
$env:PYTHONPATH = "..\neon-storage-backend-service"
pip install -r requirements.txt -r ..\neon-storage-backend-service\requirements.txt
copy .env.example .env
uvicorn user_management_service.main:app --reload
```

## Pruebas

```powershell
pytest tests
```

No tocan Neon: usan una base SQLite temporal. Las del monolito heredado siguen
en `app/test`.
