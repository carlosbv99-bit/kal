#!/usr/bin/env bash
# Automatiza TODA la Parte 1, 2 y 4.1-4.2 de docs/GUIA_VSCODE.md:
# instala lo que falte en el sistema (Docker, Python, Node, ffmpeg,
# Ollama), prepara el proyecto (venv + pip install), compila la
# extensión de VS Code y la instala de forma permanente (no hace
# falta F5 cada vez).
#
# Es re-ejecutable: cada paso primero verifica si ya está hecho y lo
# salta. Solo pide confirmación antes de instalar algo en el sistema
# (apt/curl) o de descargar un modelo grande de Ollama.
#
# Alcance: Ubuntu/Debian (apt). En otra distro, instalá manualmente
# siguiendo docs/GUIA_VSCODE.md — Parte 1.
#
# Uso:
#   chmod +x scripts/setup_all.sh
#   ./scripts/setup_all.sh

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

OLLAMA_MODEL="qwen3-coder:30b"
MISSING_MANUAL=()

confirm() {
    # confirm "mensaje" — devuelve 0 (sí) o 1 (no). Default: sí.
    read -r -p "$1 [S/n] " reply
    [[ -z "$reply" || "$reply" =~ ^[SsYy]$ ]]
}

section() { echo; echo "== $1 =="; }

# ---------------------------------------------------------------
section "Verificando distribución"
if ! command -v apt-get &> /dev/null; then
    echo "ERROR: este script solo automatiza instalación en Ubuntu/Debian (apt)."
    echo "Instalá manualmente siguiendo docs/GUIA_VSCODE.md — Parte 1, y volvé a"
    echo "correr este script: los pasos de preparación del proyecto (Parte 2 en"
    echo "adelante) funcionan igual una vez que Docker/Python/Node/Ollama existan."
    exit 1
fi
echo "✓ apt-get disponible"

# ---------------------------------------------------------------
section "Docker"
if command -v docker &> /dev/null; then
    echo "✓ Docker ya instalado ($(docker --version))"
else
    echo "Docker no está instalado. Se necesita para que kal ejecute las skills en sandbox."
    if confirm "¿Instalar 'docker.io' vía apt ahora (pide sudo)?"; then
        sudo apt-get update && sudo apt-get install -y docker.io
    else
        MISSING_MANUAL+=("Docker")
    fi
fi

if command -v docker &> /dev/null; then
    if ! docker info &> /dev/null; then
        echo "⚠ Docker está instalado pero el daemon no responde."
        if confirm "¿Arrancarlo ahora con 'sudo systemctl start docker'?"; then
            sudo systemctl start docker
        fi
    fi
    if command -v docker &> /dev/null && ! groups "$USER" | grep -qw docker; then
        echo "⚠ Tu usuario no está en el grupo 'docker' (hoy necesitarías sudo para cada comando docker)."
        if confirm "¿Agregar tu usuario al grupo 'docker' ahora?"; then
            sudo usermod -aG docker "$USER"
            echo "  Hecho. Tenés que CERRAR SESIÓN y volver a entrar (o reiniciar) para que tenga efecto."
        fi
    fi
fi

# ---------------------------------------------------------------
section "Python 3.11+"
PY_OK=false
if command -v python3 &> /dev/null; then
    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
    PY_MAJOR=${PY_VER%%.*}
    PY_MINOR=${PY_VER##*.}
    if [ "$PY_MAJOR" -gt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -ge 11 ]; }; then
        echo "✓ Python $PY_VER ya cumple (>= 3.11)"
        PY_OK=true
    fi
fi
if [ "$PY_OK" = false ]; then
    echo "Python 3.11+ no encontrado."
    if confirm "¿Instalar 'python3', 'python3-venv' y 'python3-pip' vía apt ahora (pide sudo)?"; then
        sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
        PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo "0.0")
        PY_MAJOR=${PY_VER%%.*}; PY_MINOR=${PY_VER##*.}
        if [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; then
            echo "⚠ El Python de los repos de tu distro sigue siendo $PY_VER (< 3.11)."
            echo "  Necesitás una versión más nueva — ver https://www.python.org/downloads/"
            echo "  o el PPA 'deadsnakes' (Ubuntu). Instalación manual, este script no la fuerza."
            MISSING_MANUAL+=("Python 3.11+")
        fi
    else
        MISSING_MANUAL+=("Python 3.11+")
    fi
fi
# python3-venv puede faltar aunque python3 exista
if command -v python3 &> /dev/null && ! python3 -c "import venv" &> /dev/null; then
    if confirm "Falta el módulo 'venv' de Python. ¿Instalar 'python3-venv' vía apt ahora?"; then
        sudo apt-get install -y python3-venv
    fi
fi

# ---------------------------------------------------------------
section "ffmpeg"
if command -v ffmpeg &> /dev/null; then
    echo "✓ ffmpeg ya instalado"
else
    if confirm "¿Instalar 'ffmpeg' vía apt ahora (pide sudo)?"; then
        sudo apt-get update && sudo apt-get install -y ffmpeg
    else
        MISSING_MANUAL+=("ffmpeg")
    fi
fi

# ---------------------------------------------------------------
section "Node.js 18+ (para la extensión de VS Code)"
NODE_OK=false
if command -v node &> /dev/null; then
    NODE_MAJOR=$(node --version | sed 's/^v//' | cut -d. -f1)
    if [ "$NODE_MAJOR" -ge 18 ]; then
        echo "✓ Node $(node --version) ya cumple (>= 18)"
        NODE_OK=true
    else
        echo "⚠ Node $(node --version) instalado, pero es menor a 18."
    fi
fi
if [ "$NODE_OK" = false ]; then
    echo "Se recomienda instalar Node 20 LTS vía NodeSource (el 'nodejs' de los repos de Ubuntu suele estar desactualizado)."
    if confirm "¿Agregar el repositorio de NodeSource e instalar Node 20 ahora (pide sudo, descarga y ejecuta un script oficial de nodesource.com)?"; then
        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
        sudo apt-get install -y nodejs
    else
        MISSING_MANUAL+=("Node.js 18+")
    fi
fi

# ---------------------------------------------------------------
section "Ollama"
if command -v ollama &> /dev/null; then
    echo "✓ Ollama ya instalado ($(ollama --version 2>&1 | head -1))"
else
    echo "Ollama no está instalado. Es el motor de IA local que usa kal para el chat."
    if confirm "¿Instalar Ollama ahora (pide sudo, ejecuta el instalador oficial de ollama.com)?"; then
        curl -fsSL https://ollama.com/install.sh | sh
    else
        MISSING_MANUAL+=("Ollama")
    fi
fi

if command -v ollama &> /dev/null; then
    if ollama list 2>/dev/null | grep -q "$OLLAMA_MODEL"; then
        echo "✓ Modelo '$OLLAMA_MODEL' ya descargado"
    else
        echo "El modelo default de kal ('$OLLAMA_MODEL') no está descargado — son varios GB."
        echo "(Si preferís un modelo más chico que ya tengas, podés saltear esto y configurar"
        echo " 'kal.model' en VS Code más tarde — ver docs/GUIA_VSCODE.md, sección Problemas comunes.)"
        if confirm "¿Descargar '$OLLAMA_MODEL' ahora?"; then
            ollama pull "$OLLAMA_MODEL"
        fi
    fi
fi

# ---------------------------------------------------------------
section "Entorno virtual de Python + dependencias"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "✓ .venv creado"
else
    echo "✓ .venv ya existe"
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "✓ Dependencias de Python instaladas"
deactivate

# ---------------------------------------------------------------
section "Extensión de VS Code"
if command -v node &> /dev/null && command -v npm &> /dev/null; then
    (cd vscode-extension && npm install --silent && npm run compile --silent)
    echo "✓ Extensión compilada"

    if command -v code &> /dev/null; then
        if (cd vscode-extension && npx --yes @vscode/vsce package --no-dependencies \
            --allow-missing-repository --out /tmp/kal-vscode.vsix) 2>/tmp/vsce-error.log; then
            code --install-extension /tmp/kal-vscode.vsix --force
            echo "✓ Extensión empaquetada e instalada en VS Code (comandos 'Kal: ...' disponibles en cualquier ventana, sin F5)"
            rm -f /tmp/kal-vscode.vsix
        else
            echo "⚠ No se pudo empaquetar/instalar automáticamente (detalle en /tmp/vsce-error.log)."
            echo "  Alternativa: abrí vscode-extension/ en VS Code y presioná F5 (ver docs/GUIA_VSCODE.md — Parte 4.1)."
        fi
    else
        echo "⚠ No se encontró el comando 'code' en el PATH — no se puede instalar la extensión automáticamente."
        echo "  En VS Code: Ctrl+Shift+P → 'Shell Command: Install code command in PATH', y volvé a correr este script."
        echo "  Mientras tanto, podés usar la extensión en modo desarrollo: abrí vscode-extension/ y presioná F5."
    fi
else
    echo "⚠ Node/npm no disponibles todavía — no se puede compilar la extensión."
    MISSING_MANUAL+=("Node.js 18+ (para la extensión)")
fi

# ---------------------------------------------------------------
section "Resumen"
if [ ${#MISSING_MANUAL[@]} -eq 0 ]; then
    echo "Todo listo. Próximos pasos:"
    echo "  1. source .venv/bin/activate && ./scripts/run_kal.sh"
    echo "  2. Abrí VS Code sobre el proyecto que quieras editar."
    echo "  3. Ctrl+Shift+P → 'Kal: Abrir chat'"
else
    echo "Quedó pendiente instalar manualmente:"
    for dep in "${MISSING_MANUAL[@]}"; do
        echo "  - $dep"
    done
    echo "Ver docs/GUIA_VSCODE.md — Parte 1 para instrucciones. Podés volver a"
    echo "correr este script después de instalarlo: los pasos ya hechos se saltean."
fi
