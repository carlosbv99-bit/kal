#!/bin/bash

# Script para verificar que el entorno está listo para ejecutar Kal
# Este script verifica que todas las dependencias necesarias están instaladas

set -e  # Salir si algún comando falla

echo "=== Verificación de entorno para Kal ==="

# Variables
MISSING_DEPS=()

# Verificar Docker
echo "Verificando Docker..."
if ! command -v docker &> /dev/null; then
    MISSING_DEPS+=("Docker")
else
    DOCKER_VERSION=$(docker --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
    echo "  ✓ Docker instalado (v$DOCKER_VERSION)"
    
    # Verificar que Docker esté corriendo
    if ! docker info &> /dev/null; then
        echo "  ⚠ Docker está instalado pero no está corriendo"
        echo "  Por favor inicia Docker antes de continuar"
    else
        echo "  ✓ Docker está corriendo"
    fi
fi

# Verificar Python 3.11+
echo "Verificando Python..."
if ! command -v python3 &> /dev/null; then
    MISSING_DEPS+=("Python3")
elif [[ $(python3 --version 2>&1) =~ ([0-9]+)\.([0-9]+) ]]; then
    PY_MAJOR=${BASH_REMATCH[1]}
    PY_MINOR=${BASH_REMATCH[2]}
    if [ $PY_MAJOR -lt 3 ] || ([ $PY_MAJOR -eq 3 ] && [ $PY_MINOR -lt 11 ]); then
        MISSING_DEPS+=("Python 3.11 o superior")
    else
        PYTHON_VERSION=$(python3 --version)
        echo "  ✓ Python instalado ($PYTHON_VERSION)"
    fi
else
    MISSING_DEPS+=("Python3")
fi

# Verificar pip
echo "Verificando pip..."
if ! command -v pip &> /dev/null; then
    MISSING_DEPS+=("pip")
else
    echo "  ✓ pip instalado"
fi

# Verificar Ollama
echo "Verificando Ollama..."
if ! command -v ollama &> /dev/null; then
    echo "  ⚠ Ollama no encontrado (opcional para inicio, necesario para chat)"
else
    OLLAMA_VERSION=$(ollama --version 2>&1 | head -n1)
    echo "  ✓ Ollama instalado ($OLLAMA_VERSION)"
fi

# Verificar ffmpeg
echo "Verificando ffmpeg..."
if ! command -v ffmpeg &> /dev/null; then
    MISSING_DEPS+=("ffmpeg")
else
    FFMPEG_VERSION=$(ffmpeg -version 2>&1 | head -n1 | cut -d' ' -f3)
    echo "  ✓ ffmpeg instalado (v$FFMPEG_VERSION)"
fi

# Verificar git (opcional pero útil)
echo "Verificando git..."
if ! command -v git &> /dev/null; then
    echo "  ⚠ git no encontrado (opcional pero recomendado)"
else
    GIT_VERSION=$(git --version | cut -d' ' -f3)
    echo "  ✓ git instalado (v$GIT_VERSION)"
fi

# Verificar si estamos en el directorio correcto
echo "Verificando archivos del proyecto..."
REQUIRED_FILES=("requirements.txt" "config/config.yaml" "agent_core/orchestrator.py")
for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$file" ]; then
        echo "  ⚠ Archivo requerido no encontrado: $file"
    fi
done

echo ""
if [ ${#MISSING_DEPS[@]} -eq 0 ]; then
    echo "✓ ¡Todo parece estar listo para ejecutar Kal!"
    echo ""
    echo "SUGERENCIAS:"
    echo "- Si planeas usar el modo chat, asegúrate de tener Ollama corriendo y un modelo instalado"
    echo "- Ejecuta 'docker compose up' para iniciar Kal con Docker (recomendado)"
    echo "- O ejecuta './scripts/run_kal.sh' para iniciar localmente"
else
    echo "❌ Faltan algunas dependencias:"
    for dep in "${MISSING_DEPS[@]}"; do
        echo "  - $dep"
    done
    echo ""
    echo "INSTALACIÓN DEPENDENCIAS:"
    echo "Ubuntu/Debian:"
    echo "  sudo apt update"
    echo "  sudo apt install python3 python3-pip ffmpeg"
    echo "  curl -fsSL https://get.docker.com -o get-docker.sh && sh get-docker.sh"
    echo "  curl -fsSL https://ollama.ai/install.sh | sh  # opcional"
    echo ""
    echo "macOS:"
    echo "  brew install python3 ffmpeg"
    echo "  brew install --cask docker"
    echo "  brew install ollama  # opcional"
    echo ""
    echo "Después de instalar las dependencias, vuelve a ejecutar este script."
fi

echo ""
echo "PARA CONTINUAR:"
echo "1. Asegúrate de que Docker esté corriendo"
echo "2. Si tienes Ollama, inicia un modelo: 'ollama run qwen3-coder:30b'"
echo "3. Inicia Kal: 'docker compose up' o './scripts/run_kal.sh'"