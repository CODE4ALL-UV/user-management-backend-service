# user-management-backend-service · Gestión de usuarios

Este es el microservicio de **gestión de usuarios** de Code4All. Se encarga de
todo lo que tiene que ver con las cuentas:

- **Crear cuentas** de estudiante, docente o director.
- **Iniciar sesión** con correo y contraseña, con **Google** o con **Facebook**.
- **Recuperar la contraseña** con un enlace que llega al correo.
- **Guardar la foto de perfil.**

Además es quien **firma los tokens de sesión**. Cuando alguien inicia sesión,
este servicio le entrega un token, y los demás microservicios lo comprueban con
las funciones de `user_management_service/auth.py`. Por eso casi todos los
servicios dependen de este repositorio.

## Dos cosas en un mismo repositorio (por ahora)

Mientras dura el paso a microservicios, aquí conviven dos cosas:

| Qué | Dónde | Quién lo usa |
|---|---|---|
| **El microservicio de usuarios** | `user_management_service/` | El [API Gateway](https://github.com/CODE4ALL-UV/Back-end), que lo monta junto con los demás servicios. |
| **El monolito heredado** | `app/`, `main.py`, `Dockerfile`, `render.yaml` | Render, que lo sigue desplegando como `code4all-api` hasta que la app pase al gateway. |

**Los cambios nuevos se hacen en `user_management_service/`, no en `app/`.** El
monolito solo recibe arreglos de seguridad y se borra cuando `code4all-api`
esté suspendido. Los pasos del corte están en el README del gateway.

Hay una diferencia importante entre los dos: **el monolito no tiene el inicio
con Facebook ni la recuperación de contraseña.** Esas rutas solo existen en el
microservicio, así que en producción no van a funcionar hasta que se haga el
corte al gateway. Mientras tanto, la app responde «aún no disponible».

## Los roles y el registro

Hay tres roles: `estudiante`, `docente` y `director` (en la app, «la
coordinación»).

- **Cualquiera se puede registrar como estudiante.**
- **Para registrarse como docente o director hace falta un código de
  invitación**, que la coordinación entrega a quien corresponda. Los códigos se
  configuran en el servidor con `DOCENTE_SIGNUP_CODE` y `DIRECTOR_SIGNUP_CODE`.
  Si no se configura el código de un rol, nadie se puede registrar con ese rol.
  El código de docente no sirve para registrarse como director.
- Quien entra por primera vez con Google o Facebook queda como **estudiante**.

## Las rutas

| Ruta | Qué hace | ¿Pide sesión? |
|---|---|---|
| `POST /api/auth/register` | Crea una cuenta. | No |
| `POST /api/auth/login` | Inicia sesión con correo y contraseña. | No |
| `POST /api/auth/google` | Inicia sesión con Google. Si la cuenta no existe, la crea. | No |
| `POST /api/auth/facebook` | Inicia sesión con Facebook. Si la cuenta no existe, la crea. | No |
| `POST /api/auth/password/forgot` | Manda al correo el enlace para cambiar la contraseña. | No |
| `POST /api/auth/password/reset` | Cambia la contraseña con el enlace del correo. | No (el enlace hace de llave) |
| `POST /api/user/upload-photo` | Sube la foto de perfil. | Sí |
| `GET /uploads/{archivo}` | Sirve las fotos guardadas. | No |

### Registro — `POST /api/auth/register`

```json
{
  "nombre": "Ana Pérez",
  "correo": "ana@correo.com",
  "password": "una-clave",
  "tipo_discapacidad": 1,
  "rol": "docente",
  "codigo_invitacion": "el-código-de-docentes"
}
```

- `tipo_discapacidad`, `rol` y `codigo_invitacion` son opcionales. Sin `rol`, la
  cuenta es de estudiante.
- La contraseña se guarda cifrada con **bcrypt**; nunca se guarda tal cual.
- Responde **201** con los datos de la cuenta (sin token: después hay que
  iniciar sesión).

| Código | Cuándo |
|---|---|
| 400 | Ese correo ya está registrado. |
| 403 | Pidió ser docente o director sin el código correcto. |
| 422 | El correo no es válido o falta algún dato. |

Si llega un rol que no existe, la cuenta se crea como estudiante. Si
`tipo_discapacidad` no está en el catálogo, se guarda vacío.

### Inicio de sesión — `POST /api/auth/login`

```json
{ "email": "ana@correo.com", "password": "una-clave" }
```

(Ojo: en el login el campo se llama `email`; en el registro, `correo`.)

Responde con el token y los datos que la app necesita para decidir a qué
pantalla ir:

```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "user_id": 12,
  "email": "ana@correo.com",
  "nombre": "Ana Pérez",
  "rol": "docente",
  "photo_url": "/uploads/3f2a...c1.jpg"
}
```

Si el correo no existe o la contraseña no coincide, responde **401** con el
mismo mensaje en los dos casos («El correo o la contraseña son incorrectos.»),
para no revelar qué correos tienen cuenta.

### Google — `POST /api/auth/google`

La app manda lo que le entrega Google: un `access_token` (en la web) o un
`id_token` (en el celular).

```json
{ "access_token": "ya29...." }
```

El servidor no se fía del token sin más:

1. **Comprueba con Google que el token sea de Code4All.** El `access_token` se
   valida con el servicio `tokeninfo` de Google y el `id_token` con la librería
   `google-auth`. En los dos casos el token tiene que haber sido emitido para
   alguno de los Client ID de `GOOGLE_CLIENT_ID`. Así no sirve un token sacado
   de otra aplicación.
2. **Exige que el correo esté verificado** en Google.
3. Si ya hay una cuenta con ese correo, entra con ella y con su rol. Si no, la
   crea como estudiante, con una contraseña aleatoria (si después quiere entrar
   con correo y contraseña, puede ponerse una con «¿Olvidaste tu contraseña?»).

Si `GOOGLE_CLIENT_ID` no está configurado, responde **503**.

**Para probar en local sin cuenta de Google** existe el token `dev:correo`
(por ejemplo `dev:ana@correo.com:Ana`). Solo funciona si el servidor tiene
`ALLOW_DEV_LOGIN=1`. **Nunca se debe activar en Render**: antes de este
candado, cualquiera podía entrar con el correo de otra persona.

### Facebook — `POST /api/auth/facebook`

```json
{ "code": "AQD...", "redirect_uri": "https://code4all-web.onrender.com/" }
```

La app lleva a la persona a Facebook, Facebook la devuelve con un `code`, y la
app se lo pasa al servidor. El servidor lo canjea con Facebook usando la clave
secreta (que nunca sale del servidor), pide el perfil firmando la petición con
`appsecret_proof` y entra o crea la cuenta igual que con Google.

| Código | Cuándo |
|---|---|
| 400 | La cuenta de Facebook no comparte un correo (por ejemplo, se abrió con el teléfono). |
| 401 | Facebook no aceptó el código. |
| 502 | Facebook no respondió. |
| 503 | Faltan `FACEBOOK_APP_ID` o `FACEBOOK_APP_SECRET` en el servidor. |

Cómo crear la app de Facebook está en el README del
[gateway](https://github.com/CODE4ALL-UV/Back-end).

### Recuperar la contraseña

**1. `POST /api/auth/password/forgot`** con `{ "correo": "ana@correo.com" }`.

- Responde **siempre lo mismo**, exista o no la cuenta: «Si hay una cuenta con
  ese correo, te enviamos un enlace…». Así nadie puede usar esta ruta para
  averiguar quién está registrado.
- Si la cuenta existe, manda un correo con el asunto «Cambia tu contraseña de
  Code4All» y un enlace a la app: `https://code4all-web.onrender.com/?restablecer=<token>`.
  El correo va en texto y en HTML con letra grande y un botón.
- Si se pide dos veces seguidas, solo se manda un correo por minuto a cada
  dirección.
- Busca el correo sin importar mayúsculas y minúsculas.

**2. `POST /api/auth/password/reset`** con `{ "token": "...", "password": "nueva-clave" }`.

- La contraseña nueva tiene que tener **al menos 6 caracteres** (y como mucho
  72 bytes, que es el límite de bcrypt).
- Si el enlace caducó o ya se usó, responde **400**: «El enlace ya no sirve:
  caducó o ya se usó. Pide uno nuevo.».

**Cómo funciona el enlace** (en `application/use_cases/password_reset.py`): el
token es un JWT que **caduca a los 30 minutos** y lleva una «huella» de la
contraseña actual. En cuanto la contraseña cambia, la huella deja de coincidir
y el enlace deja de servir. Así es **de un solo uso sin necesidad de una tabla
nueva** en la base. Se firma con una clave derivada de `SECRET_KEY`, de modo que
un enlace no sirve como sesión ni una sesión sirve como enlace.

**El correo sale por la API de [Brevo](https://www.brevo.com)**
(`core/mailer.py`), no por SMTP: el plan gratis de Render bloquea los puertos
SMTP desde septiembre de 2025. Sin `BREVO_API_KEY` y `MAIL_FROM`, la ruta
responde **503**. En local, con `ALLOW_DEV_LOGIN=1` y sin Brevo, el correo se
escribe en la consola del servidor.

### Foto de perfil — `POST /api/user/upload-photo`

- Pide sesión (`Authorization: Bearer <token>`).
- La foto va como `multipart/form-data` en el campo `file`.
- Formatos: `.jpg`, `.jpeg`, `.png` o `.webp`. Máximo **5 MB** (si no, 413).
- La foto siempre es del dueño del token. Si se manda el id de otra persona,
  responde 403.
- Se guarda en `uploads/` con un nombre aleatorio y queda en
  `Usuario.foto_path`. Responde `{ "photo_url": "/uploads/<archivo>" }`.

Las fotos se sirven en `GET /uploads/{archivo}`, sin sesión.

## La sesión (el token)

Es un **JWT** firmado con `SECRET_KEY` (algoritmo `HS256` por defecto) que dura
**24 horas** (`ACCESS_TOKEN_EXPIRE_MINUTES = 1440`). Lleva:

| Campo | Qué es |
|---|---|
| `sub` | El id del usuario. |
| `email` | Su correo. |
| `rol` | `estudiante`, `docente` o `director`. |
| `exp` | Cuándo caduca. |

La app lo manda en cada petición en la cabecera `Authorization: Bearer <token>`.

**`SECRET_KEY` tiene que ser la misma en todos los servicios** y la misma que
usa `code4all-api`. Si cambia, todas las sesiones abiertas dejan de valer.

### Lo que usan los demás servicios

`user_management_service/auth.py` es la parte de este repositorio que importan
los otros:

```python
from user_management_service.auth import current_caller, require_course_editor
from user_management_service.core.security import decode_access_token
```

- **`current_caller`**: exige un token válido y devuelve quién llama (correo,
  rol e id). Sin token o con un token vencido responde 401 con un mensaje en
  castellano.
- **`require_course_editor`**: además exige que sea docente o director (si no,
  403).
- **`decode_access_token`**: para quien quiera leer el token por su cuenta.
  progress-tracking lo usa para comprobar el rol de director **contra la base
  de datos**.

Estas funciones leen el rol **del token**. Si a alguien le cambian el rol, el
cambio se nota cuando inicia sesión de nuevo (o cuando el token caduca).

## Estructura

```
user_management_service/          el microservicio
├── routes.py                      register(app): lo único que llama el gateway
├── main.py                        arranque independiente
├── auth.py                        current_caller y require_course_editor (para los demás servicios)
├── core/
│   ├── security.py                bcrypt y los JWT
│   └── mailer.py                  el envío de correos por Brevo
├── application/use_cases/
│   ├── create_user.py             registro
│   ├── login_user.py              inicio de sesión
│   └── password_reset.py          el enlace de recuperación
├── domain/repositories/           la interfaz del repositorio de usuarios
├── infrastructure/database/       el repositorio con SQLAlchemy
└── presentation/api/
    ├── auth_routes.py             /api/auth/*
    └── upload_routes.py           /api/user/upload-photo
tests/                             pruebas del microservicio
uploads/                           fotos de perfil
app/, main.py, Dockerfile,         el monolito heredado (code4all-api)
render.yaml
neon_storage/                      puente para el CI (ver «Cosas a tener en cuenta»)
```

Las tablas (`Usuario` y `TipoDiscapacidad`) están definidas en
[neon-storage](https://github.com/CODE4ALL-UV/neon-storage-backend-service).
Este servicio es el único que escribe en `Usuario`.

## Variables de entorno

| Variable | Para qué | ¿Obligatoria? |
|---|---|---|
| `DATABASE_URL` | La cadena de conexión de Neon. | Sí |
| `SECRET_KEY` | Firma los tokens. La misma en todos los servicios y en `code4all-api`. Si falta, se usa una clave por defecto que **no sirve para producción**. | Sí |
| `ALGORITHM` | Algoritmo del token. Por defecto `HS256`. | No |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Duración de la sesión. Por defecto `1440` (24 h). | No |
| `GOOGLE_CLIENT_ID` | El Client ID de Google de Code4All. Si la web y el celular usan IDs distintos, van separados por comas. | Para entrar con Google |
| `DOCENTE_SIGNUP_CODE` | El código para registrarse como docente. | No (sin él, no hay registro de docentes) |
| `DIRECTOR_SIGNUP_CODE` | El código para registrarse como director. | No (sin él, no hay registro de directores) |
| `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET` | La app de Facebook. | Para entrar con Facebook |
| `BREVO_API_KEY`, `MAIL_FROM` | La clave de Brevo y el correo verificado que envía los mensajes. | Para recuperar la contraseña |
| `MAIL_FROM_NAME` | El nombre del remitente. Por defecto `Code4All`. | No |
| `FRONTEND_URL` | La dirección de la app para armar el enlace. Por defecto `https://code4all-web.onrender.com`. | No |
| `CORS_ORIGINS` | Otros orígenes que pueden llamar al API desde el navegador, separados por comas. | No |
| `ALLOW_DEV_LOGIN` | `1` para aceptar tokens `dev:correo` y escribir los correos en consola. **Solo en local, nunca en Render.** | No |

`GOOGLE_SERVER_CLIENT_ID` aparece en `.env.example` y en `render.yaml`, pero hoy
el código no la lee.

## Correrlo

Lo normal es correrlo dentro del gateway (repo `Back-end`), que monta todos
los servicios juntos. Para correrlo solo hace falta `neon-storage` clonado al
lado:

```powershell
$env:PYTHONPATH = "..\neon-storage-backend-service"
pip install -r requirements.txt -r ..\neon-storage-backend-service\requirements.txt
copy .env.example .env
uvicorn user_management_service.main:app --reload
```

El monolito se corre desde la raíz con `uvicorn main:app --reload`, o con el
`Dockerfile`, que es como lo despliega Render.

## Pruebas

```powershell
pytest tests
```

Corren contra una base SQLite temporal, nunca contra Neon. La forma más cómoda
es correrlas desde el gateway, con `pytest` en la raíz de `Back-end`.

| Archivo | Qué comprueba |
|---|---|
| `test_auth_routes.py` | Los tokens `dev:` solo con `ALLOW_DEV_LOGIN`; los códigos de invitación (el estudiante no lo necesita, el de docente no sirve para director, sin código configurado no hay registro); que el token de Google lleve `rol`. |
| `test_create_user_roles.py` | Que el registro guarde el rol. |
| `test_password_reset.py` | El enlace cambia la contraseña una sola vez; caduca; deja de servir si la contraseña cambió; no vale como sesión; un correo desconocido no recibe nada; un correo por minuto; si el envío falla se puede volver a pedir; la llamada a Brevo va bien armada. |
| `test_social_login.py` | Google: entra una cuenta existente, se crea una nueva como estudiante, se rechazan tokens de otra app y correos sin verificar, 503 sin configurar. Facebook: lo mismo, más el correo que no llega y Facebook caído. |
| `test_upload_photo_route.py` | La foto se guarda, es siempre del dueño de la sesión, 401 sin sesión, 403 con el id de otro, 413 si pasa de 5 MB. |

El gateway tiene además pruebas de punta a punta de este servicio:
`test_password_reset_flow.py` y `test_security.py`.

Las pruebas del monolito están en `app/test`. Esas **no** fuerzan SQLite:
antes de correrlas hay que apuntar `DATABASE_URL` a una base de pruebas.

En GitHub, cada push o pull request a `main` corre `pytest tests` con
cobertura y la sube a Codacy (`.github/workflows/codacy-coverage.yml`).

## Cosas a tener en cuenta

- **La carpeta `neon_storage/` de este repositorio no es la capa de datos
  real.** Es un puente para que el CI de GitHub pueda correr las pruebas sin
  clonar neon-storage: reexporta los modelos del monolito (`app/`). Dentro del
  gateway no se usa, porque el gateway encuentra antes el neon-storage de
  verdad. Pero al correr el servicio o las pruebas desde la raíz de este
  repositorio, Python encuentra primero esta carpeta. Hay que borrarla junto
  con `app/` cuando se retire el monolito.
- Google y Facebook entran a la cuenta que tenga ese correo, sea del rol que
  sea.
- El login compara el correo tal cual (distingue mayúsculas); la recuperación
  de contraseña no.
- Cambiar la contraseña no cierra las sesiones que ya estaban abiertas: los
  tokens siguen valiendo hasta que caducan.
- No hay límite de intentos de inicio de sesión. El «un correo por minuto» de
  la recuperación se guarda en memoria y se pierde si el servidor se reinicia.
- Las fotos se guardan en el disco del servidor. En Render ese disco se borra
  con cada despliegue, así que las fotos subidas en producción se pierden.
- No hay rutas para editar el perfil, cambiar la contraseña con la sesión
  abierta ni borrar la cuenta.
- `requirements.txt` lo comparten el monolito y el microservicio, por eso trae
  dependencias pesadas que el microservicio no usa (MediaPipe, OpenCV,
  youtube-transcript-api). Se pueden quitar cuando se borre el monolito.

## Los repositorios de Code4All

| Parte | Repositorio |
|---|---|
| App (Flutter) | [Front-end](https://github.com/CODE4ALL-UV/Front-end) |
| API Gateway | [Back-end](https://github.com/CODE4ALL-UV/Back-end) |
| **Gestión de usuarios** | **este repositorio** |
| Curso y contenidos de Python | [course-content-backend-service](https://github.com/CODE4ALL-UV/course-content-backend-service) |
| Ejercicios y evaluación | [assessment-backend-service](https://github.com/CODE4ALL-UV/assessment-backend-service) |
| Progreso y seguimiento | [progress-tracking-backend-service](https://github.com/CODE4ALL-UV/progress-tracking-backend-service) |
| Accesibilidad y adaptación | [accessibility-backend-service](https://github.com/CODE4ALL-UV/accessibility-backend-service) |
| Interacción multimodal | [multimodal-interaction-backend-service](https://github.com/CODE4ALL-UV/multimodal-interaction-backend-service) |
| Infraestructura y dispositivos | [device-management-backend-service](https://github.com/CODE4ALL-UV/device-management-backend-service) |
| Capa de datos compartida (Neon) | [neon-storage-backend-service](https://github.com/CODE4ALL-UV/neon-storage-backend-service) |
