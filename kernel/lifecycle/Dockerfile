# Servicio aislado: es el ÚNICO componente con acceso al socket de Docker
# del host (ver docker-compose.yml). Superficie de ataque reducida a
# propósito: si este servicio se ve comprometido, el daño está acotado
# a lo que docker_runner.py permite (contenedores efímeros con límites
# duros), no a acceso arbitrario al agente principal.
FROM python:3.11-slim

RUN groupadd -r sandbox && useradd -r -g sandbox sandbox

WORKDIR /app
RUN pip install --no-cache-dir docker fastapi "uvicorn[standard]"

# El contexto de build de este Dockerfile es la raíz del proyecto
# (ver docker-compose.yml: build.context), no ./kernel/lifecycle, para
# poder copiar también sdk/, code_analysis/, audit/ y utils/ que este
# servicio reutiliza (Permission, validación estática, auditoría, config).
COPY kernel/ ./kernel/
COPY sdk/ ./sdk/
COPY code_analysis/ ./code_analysis/
COPY audit/ ./audit/
COPY utils/ ./utils/
COPY config/ ./config/
WORKDIR /app/kernel/lifecycle

# Nota: este contenedor necesita el grupo del socket de Docker montado,
# por lo que en la práctica puede requerir ejecutarse con el GID del
# socket del host. Evaluar Docker-in-Docker rootless o gVisor como
# alternativa más segura antes de producción (ver plan de Fase 0/5).
EXPOSE 9000
WORKDIR /app

CMD ["uvicorn", "kernel.api.sandbox_api:app", "--host", "0.0.0.0", "--port", "9000"]
