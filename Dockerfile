FROM python:3.11-slim

# Usuario no-root desde el inicio (principio de menor privilegio)
RUN groupadd -r agent && useradd -r -g agent agent

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# El agente principal NO necesita ser root ni tener el socket de Docker
# montado directamente salvo el proceso orquestador del sandbox.
# Ver docker-compose.yml para el aislamiento del servicio de sandbox.
RUN chown -R agent:agent /app
USER agent

EXPOSE 8000

CMD ["uvicorn", "agent_core.orchestrator:app", "--host", "0.0.0.0", "--port", "8000"]
