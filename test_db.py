import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# 1. Cargar las variables del archivo .env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("❌ ERROR: No se encontró la variable DATABASE_URL en tu archivo .env")
    exit()

print("🔄 Intentando conectar a NeonDB...")

try:
    # 2. Crear el motor de conexión
    engine = create_engine(DATABASE_URL)
    
    # 3. Hacer una consulta de prueba
    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1;"))
        print("\n✅ ¡CONEXIÓN EXITOSA! Tu backend se ha comunicado perfectamente con NeonDB.")
        
        # Consultar la versión de PostgreSQL en tu servidor de Neon
        version = connection.execute(text("SELECT version();")).scalar()
        print(f"📊 Información del servidor:\n{version}\n")
        
except Exception as e:
    print("\n❌ FALLÓ LA CONEXIÓN A LA BASE DE DATOS:")
    print("--------------------------------------------------")
    print(e)
    print("--------------------------------------------------")
    print("💡 Consejo: Verifica que tu contraseña en el .env sea correcta y que tengas internet.")