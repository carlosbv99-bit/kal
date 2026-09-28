# Servicio aislado: es el ÚNICO componente con acceso al socket de Docker
# del host (ver docker-compose.yml). Superficie de ataque reducida a
# propósito: si este servicio se ve comprometido, el daño está acotado
# a lo que docker_runner.py permite (contenedores efímeros con límites
# duros), no a acceso arbitrario al agente principal.
FROM python:3.11-slim

RUN groupadd -r sandbox && useradd -r -g sandbox sandbox

WORKDIR /app

# VULNERABILIDAD REAL ENCONTRADA EN AUDITORÍA EXTERNA (M-7, 2026-09-27):
# el usuario `sandbox` de arriba se creaba pero nunca se ACTIVABA (sin
# `USER sandbox`) — este servicio, el ÚNICO con acceso al socket de
# Docker del host, corría como root. Cualquier RCE acá (código
# ejecutable vía /execute, con un denylist AST evadible como única
# barrera adicional — ver code_analysis/ast_validator.py) pasaba
# directo de "proceso comprometido" a "root con el socket de Docker",
# es decir root del host. `USER sandbox` cierra esto — pero el
# contenedor SIGUE necesitando pertenecer al grupo dueño del socket de
# Docker del host para poder usarlo; eso varía por host y no se puede
# hardcodear acá, así que quien despliegue esto debe agregar
# `--group-add <GID del socket de Docker del host>` (o el equivalente
# `group_add:` en docker-compose.yml) al arrancar este contenedor —
# el grupo `sandbox` creado arriba es precisamente el punto de
# extensión pensado para eso.
COPY requirements-core.txt .
RUN pip install --no-cache-dir -r requirements-core.txt

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

# Evaluar Docker-in-Docker rootless o gVisor como alternativa más
# segura antes de producción (ver plan de Fase 0/5) — USER sandbox de
# abajo es la mitigación de hoy, no la solución final.
#
# BUG REAL ENCONTRADO VERIFICANDO ESTE FIX (2026-09-27): agregar SOLO
# `USER sandbox` sin esto rompía el servicio por completo — /app quedó
# root:root por los COPY de arriba, y utils/logger.py crea logs/ (con
# mkdir relativo al cwd) al importarse, así que el proceso ni siquiera
# arrancaba (`PermissionError: [Errno 13] Permission denied: 'logs'`).
# Verificado con un build real: sin este chown, `docker run ... python
# -c "from kernel.api.sandbox_api import app"` falla; con él, importa
# bien y corre como `sandbox`, no como root (`whoami` confirmado).
RUN chown -R sandbox:sandbox /app
EXPOSE 9000
USER sandbox

CMD ["uvicorn", "kernel.api.sandbox_api:app", "--host", "0.0.0.0", "--port", "9000"]
