# Plan de Ejecución y Planificación: Contenedorización del Entorno (#infra-40)

## 📌 Contexto y Objetivo
El objetivo de este proyecto es definir y estandarizar el entorno de desarrollo y producción mediante contenedores Docker. La plataforma consta de los componentes de interfaz en `/uis` (website en puerto 3000 y backoffice en puerto 3001) y el servicio de backend FastAPI en `/services` (puerto 8000).

Toda la arquitectura, nombres de variables y detalles de infraestructura específicos del proyecto deben validarse contra el archivo `CONTEXT.md` ubicado en la raíz del espacio de trabajo.

---

## 🎯 Criterios de Aceptación (Acceptance Criteria)

- [ ] **Aislamiento y Despliegue Unificado**: La plataforma debe ser capaz de levantarse ejecutando únicamente `docker compose up` desde la raíz, sin pasos de configuración manuales en el host.
- [ ] **Recarga en Caliente (Hot Reloading)**: Los cambios realizados en el código local (`/uis` o `/services`) deben reflejarse inmediatamente en el navegador sin reconstruir las imágenes (Bind Mounts).
- [ ] **Contenedor Único de Interfaces**: El servicio `/uis` debe compilar y ejecutar tanto el `website` (3000) como el `backoffice` (3001) desde una sola imagen Node.js mediante un script de arranque `start.sh`.
- [ ] **Red Docker Interna**: La comunicación inter-servicio (interfaces a backend) debe realizarse obligatoriamente por el nombre del servicio en la red Docker (ej. `http://api:8000`), evitando el uso de `localhost`.
- [ ] **Seguridad e Higiene de Repositorio**: 
  - Existen archivos `.dockerignore` tanto en `/uis/` como en `/services/`.
  - Nunca incluyas secretos reales, ni APIs ni contraseñas en `docker-compose.yml` ni los `Dockerfile` contienen secretos, credenciales o tokens hardcodeados.
  - El archivo `.env` está registrado en el `.gitignore`.
- [ ] **Despliegue en Producción (VPS)**: El mismo stack de contenedores está desplegado y accesible en producción en el servidor VPS configurado.

---

## 📋 Protocolo de Trabajo para el Agente de IA

1. **Revisión Inicial**: El agente debe analizar primero este documento junto a `CONTEXT.md` antes de escribir cualquier código.
2. **Ejecución Secuencial**: Las fases deben completarse estrictamente una por una.
3. **Puntos de Control e Informes**: Al terminar cada fase, el agente **debe detenerse** y presentar un informe del trabajo realizado, detallando los archivos creados o modificados y los comandos probados.
4. **Autorización Explicita**: El agente no debe avanzar a la siguiente fase hasta recibir la confirmación del usuario tras revisar el informe de la fase actual.

---

## 🚀 Fases de Ejecución

### Fase 0: Inicialización de Rama e Higiene
**Objetivo**: Establecer la rama de trabajo y asegurar la protección de credenciales sensibles.

1. Crear y cambiarse a la rama Git: `feature/docker-containerization`.
2. Consultar `CONTEXT.md` para validar las variables de entorno utilizadas.
3. Verificar la presencia de `.env` en `.gitignore`.
4. Crear un archivo `.env.example` en la raíz con las claves de variables requeridas sin exponer valores reales.

*Entregable de la Fase*: Confirmación de rama activa, `.gitignore` verificado y archivo `.env.example` generado.

---

### Fase 1: Dockerización del Módulo de Interfaces (`/uis`)
**Objetivo**: Empaquetar el sitio web y el panel de administración en un único contenedor Node.js Alpine.

1. Crear el archivo `/uis/.dockerignore` excluyendo `node_modules`, `.next`, `.env*` y logs.
2. Crear un script `/uis/start.sh` con permisos de ejecución (`chmod +x`) para ejecutar simultáneamente el `website` (puerto 3000) y el `backoffice` (puerto 3001).
3. Crear el archivo `/uis/Dockerfile` basado en `node:20-alpine`:
   - Configurar el directorio de trabajo en `/app`.
   - Copiar los manifestos de dependencias e instalarlas.
   - Exponer los puertos `3000` y `3001`.
   - Definir el `CMD` apuntando a `start.sh`.

*Entregable de la Fase*: Archivos `/uis/.dockerignore`, `/uis/start.sh` y `/uis/Dockerfile` creados. Informe técnico con los detalles del script y la imagen.

---

### Fase 2: Dockerización del Módulo Backend (`/services`)
**Objetivo**: Empaquetar el servicio FastAPI con `uv` sobre Python en su propio contenedor.

1. Crear el archivo `/services/.dockerignore` excluyendo `__pycache__`, `.env*`, `.venv`, `tests/` y logs.
2. Crear el archivo `/services/Dockerfile` basado en `python:3.11-slim`:
   - Instalar `uv` para la gestión rápida de dependencias.
   - Configurar el directorio de trabajo en `/app`.
   - Copiar `requirements.txt` e instalar dependencias con `uv pip install`.
   - Exponer el puerto `8000`.
   - Definir el `CMD` para arrancar Uvicorn con la bandera `--reload` activada.

*Entregable de la Fase*: Archivos `/services/.dockerignore` y `/services/Dockerfile` creados. Informe técnico del backend.

---

### Fase 3: Orquestación Local con Docker Compose (`docker-compose.yml`)
**Objetivo**: Unificar los servicios en una red Docker privada, vincular volúmenes para Hot Reloading e inyectar configuración desde `.env`.

1. Crear el archivo `docker-compose.yml` en la raíz del proyecto:
   - Configurar el servicio de UI con build en `./uis`, puertos `3000:3000` y `3001:3001`, y bind mount `./uis:/app`.
   - Configurar el servicio de API con build en `./services`, puerto `8000:8000`, y bind mount `./services:/app`.
   - Crear una red personalizada llamada `trackflow-network`.
   - Vincular el archivo `.env` en ambos servicios.
2. Ajustar las URLs inter-servicio para que las peticiones backend apunten al nombre del servicio (ej. `http://api:8000`).
3. Ejecutar `docker compose up --build` y verificar el correcto arranque en local.

*Entregable de la Fase*: Archivo `docker-compose.yml` creado y prueba local verificada mediante `docker compose ps`.

---

### Fase 4: Despliegue en Servidor Producción (VPS)
**Objetivo**: Desplegar la pila de contenedores en el servidor VPS de producción.

1. Conectarse mediante SSH al servidor VPS.
2. Sincronizar los cambios con la rama `feature/docker-containerization`.
3. Configurar el archivo `.env` en el servidor VPS con las variables de entorno de producción.
4. Desplegar los servicios mediante `docker compose up -d --build`.
5. Comprobar la disponibilidad pública de los servicios.

*Entregable de la Fase*: Confirmación de despliegue en VPS y comprobación de estado de contenedores en producción.

---

### Fase 5: Documentación y Entrega (Pull Request)
**Objetivo**: Consolidar la entrega para revisión y aprobación final.

1. Recopilar capturas o registros del comando `docker compose ps` local y en el VPS.
2. Crear el Pull Request en GitHub hacia la rama `main` adjuntando las evidencias correspondientes.

*Entregable de la Fase*: Enlace al Pull Request creado y aprobado.