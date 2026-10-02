# Imagen del backend de Code4All.
#
# Va en Docker y no en el entorno de Python que trae Render por dos motivos
# concretos:
#
# 1. MediaPipe necesita librerias del sistema (libGL, libglib) que el entorno
#    nativo de Render no tiene y no deja instalar. Sin ellas, importar
#    mediapipe falla al arrancar y el reconocimiento de senas no funciona.
# 2. Asi la version de Python es la misma aqui y en produccion, en lugar de la
#    que Render elija por su cuenta.

FROM python:3.12-slim

# Librerias del sistema que piden MediaPipe y OpenCV.
#
# MediaPipe arrastra la pila de OpenGL aunque solo use la CPU. Sin libEGL
# falla al CREAR el detector, no al importarse, asi que el error no sale al
# arrancar sino en la primera peticion de verdad: el servicio parece sano y
# se cae en cuanto alguien usa la camara.
#
# opencv-python-headless ya evita por su cuenta todo lo de ventanas.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libegl1 \
    libgles2 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Las dependencias van antes que el codigo: asi un cambio en el codigo no
# obliga a reinstalarlas todas en cada despliegue.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

# El modelo de MediaPipe (7,8 MB) se descarga solo la primera vez que alguien
# usa el reconocimiento. Se deja fuera de la imagen a proposito para no
# engordarla; el disco de Render es efimero, asi que volvera a bajarlo tras
# cada despliegue. Es una espera de un par de segundos, y solo la primera vez.
ENV PYTHONUNBUFFERED=1

# Render manda el puerto en la variable PORT. Hay que escuchar en 0.0.0.0:
# en 127.0.0.1 el contenedor no recibiria nada de fuera.
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
