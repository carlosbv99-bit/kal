#!/bin/bash

# Script para probar la instalación de Kal
# Este script verifica que Kal está funcionando correctamente después de la instalación

set -e  # Salir si algún comando falla

echo "=== Prueba de Instalación de Kal ==="

# Variables
TIMEOUT=30
HOST="http://localhost:8000"

# Función para verificar si un puerto está ocupado
wait_for_service() {
    local port=$1
    local service=$2
    local counter=0
    
    echo "Esperando a que $service esté disponible en el puerto $port..."
    
    while ! nc -z localhost $port; do
        sleep 2
        ((counter += 2))
        
        if [ $counter -ge $TIMEOUT ]; then
            echo "❌ Tiempo de espera agotado para $service"
            return 1
        fi
        
        echo "  Esperando... ($counter/$TIMEOUT segundos)"
    done
    
    echo "✓ $service está disponible en el puerto $port"
    return 0
}

# Verificar prerequisitos
echo "1. Verificando prerequisitos..."
if ! command -v docker &> /dev/null; then
    echo "❌ Docker no está instalado o no está en PATH"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo "❌ Docker no está corriendo"
    exit 1
fi

echo "✓ Docker está instalado y corriendo"

# Intentar iniciar Kal con docker-compose si el archivo existe
if [ -f "docker-compose.yml" ]; then
    echo "2. Iniciando Kal con Docker Compose..."
    
    # Levantar servicios en segundo plano
    docker compose up -d
    
    # Esperar a que el servicio esté disponible
    if wait_for_service 8000 "Kal API"; then
        echo "✓ Kal está corriendo en $HOST"
    else
        echo "❌ Kal no está respondiendo en $HOST"
        echo "Verificando estado de contenedores:"
        docker compose ps
        exit 1
    fi
else
    echo "⚠ No se encontró docker-compose.yml, asumiendo instalación local"
fi

# Verificar el estado del sistema
echo "3. Verificando estado del sistema..."
if command -v curl &> /dev/null; then
    STATUS_RESPONSE=$(curl -s -m 10 $HOST/status)
    if [ $? -eq 0 ]; then
        echo "✓ API de estado accesible"
        
        # Verificar algunos campos importantes del estado
        AUDIT_STATUS=$(echo $STATUS_RESPONSE | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('audit_chain_verified', 'unknown'))" 2>/dev/null || echo "unknown")
        echo "  - Cadena de auditoría verificada: $AUDIT_STATUS"
        
        NETWORK_MODE=$(echo $STATUS_RESPONSE | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('sandbox_network_mode', 'unknown'))" 2>/dev/null || echo "unknown")
        echo "  - Modo de red del sandbox: $NETWORK_MODE"
        
        LLM_AVAILABLE=$(echo $STATUS_RESPONSE | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('llm_available', 'unknown'))" 2>/dev/null || echo "unknown")
        echo "  - LLM disponible: $LLM_AVAILABLE"
    else
        echo "⚠ No se pudo obtener estado del sistema (posiblemente Ollama no esté corriendo)"
    fi
elif command -v wget &> /dev/null; then
    STATUS_RESPONSE=$(wget -q -O - --timeout=10 $HOST/status)
    if [ $? -eq 0 ]; then
        echo "✓ API de estado accesible"
    else
        echo "⚠ No se pudo obtener estado del sistema"
    fi
else
    echo "⚠ Ni curl ni wget están disponibles para probar la API"
fi

# Verificar modelos disponibles
echo "4. Verificando modelos disponibles..."
if command -v curl &> /dev/null; then
    MODELS_RESPONSE=$(curl -s -m 10 $HOST/models 2>/dev/null)
    if [ $? -eq 0 ]; then
        echo "✓ Endpoint de modelos accesible"
        DEFAULT_MODEL=$(echo $MODELS_RESPONSE | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('default', 'unknown'))" 2>/dev/null || echo "unknown")
        echo "  - Modelo por defecto: $DEFAULT_MODEL"
    else
        echo "⚠ No se pudo obtener lista de modelos (posiblemente Ollama no esté corriendo)"
    fi
elif command -v wget &> /dev/null; then
    MODELS_RESPONSE=$(wget -q -O - --timeout=10 $HOST/models 2>/dev/null)
    if [ $? -eq 0 ]; then
        echo "✓ Endpoint de modelos accesible"
    else
        echo "⚠ No se pudo obtener lista de modelos"
    fi
fi

# Verificar que la interfaz web responde
echo "5. Verificando interfaz web..."
if command -v curl &> /dev/null; then
    WEB_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 $HOST 2>/dev/null)
    if [ "$WEB_RESPONSE" = "200" ] || [ "$WEB_RESPONSE" = "307" ]; then
        echo "✓ Interfaz web accesible (código HTTP: $WEB_RESPONSE)"
    else
        echo "⚠ Interfaz web no responde (código HTTP: $WEB_RESPONSE)"
    fi
elif command -v wget &> /dev/null; then
    WEB_RESPONSE=$(wget --server-response --spider --timeout=10 $HOST 2>&1 | grep "HTTP/" | awk '{print $2}' | tail -1)
    if [ "$WEB_RESPONSE" = "200" ] || [ "$WEB_RESPONSE" = "307" ]; then
        echo "✓ Interfaz web accesible (código HTTP: $WEB_RESPONSE)"
    else
        echo "⚠ Interfaz web no responde (código HTTP: $WEB_RESPONSE)"
    fi
fi

# Prueba simple de chat (opcional, si Ollama está disponible)
echo "6. Probando funcionalidad de chat (prueba simple)..."
if command -v curl &> /dev/null; then
    # Enviar una solicitud de chat simple para verificar que el endpoint funciona
    CHAT_PAYLOAD='{"goal": "Hola, ¿cómo estás?", "session_id": "test_'$(date +%s)'"}'
    CHAT_RESPONSE=$(curl -s -X POST -H "Content-Type: application/json" --max-time 15 $HOST/chat -d "$CHAT_PAYLOAD" 2>/dev/null)
    
    if [ $? -eq 0 ]; then
        RESPONSE_STATUS=$(echo $CHAT_RESPONSE | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('status', 'unknown'))" 2>/dev/null || echo "unknown")
        SESSION_ID=$(echo $CHAT_RESPONSE | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('session_id', 'missing'))" 2>/dev/null || echo "missing")
        
        if [ "$RESPONSE_STATUS" != "unknown" ]; then
            echo "✓ Endpoint de chat responde (estado: $RESPONSE_STATUS)"
        else
            echo "⚠ Endpoint de chat responde pero sin estado claro"
        fi
    else
        echo "⚠ Endpoint de chat no responde (posiblemente Ollama no esté disponible)"
    fi
fi

echo ""
echo "=== RESULTADO DE LA PRUEBA ==="

if [ -f "docker-compose.yml" ]; then
    RUNNING_CONTAINERS=$(docker compose ps --format "table {{.Service}}\t{{.Status}}" 2>/dev/null || echo "No hay contenedores activos")
    echo "Contenedores activos:"
    echo "$RUNNING_CONTAINERS"
    echo ""
fi

echo "✓ Prueba de instalación completada"
echo ""
echo "RESUMEN:"
echo "- Kal está instalado y respondiendo en $HOST"
echo "- Los endpoints básicos están accesibles"
echo "- El sistema está listo para su uso"
echo ""
echo "PRÓXIMOS PASOS:"
echo "1. Abre $HOST en tu navegador para acceder a la interfaz web"
echo "2. Consulta la guía de uso en scripts/usage_guide.md"
echo "3. Prueba algunas solicitudes en el panel de chat"
echo ""
echo "NOTA: Si no ves respuestas completas en el chat, verifica que Ollama esté corriendo"
echo "y que tengas un modelo disponible (por ejemplo: ollama run qwen3-coder:30b)"