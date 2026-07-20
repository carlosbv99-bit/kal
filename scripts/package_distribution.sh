#!/bin/bash

# Script para empaquetar Kal para distribución a otros equipos
# Este script crea un archivo ZIP con todos los archivos necesarios para ejecutar Kal en otra máquina

set -e  # Salir si algún comando falla

echo "=== Empaquetando Kal para distribución ==="

# Variables
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$PROJECT_ROOT/dist"
PACKAGE_NAME="kal-distribution-$(date +%Y%m%d-%H%M%S)"
PACKAGE_PATH="$DIST_DIR/$PACKAGE_NAME.zip"

# Crear directorio de distribución
mkdir -p "$DIST_DIR"

# Directorios y archivos a incluir
#
# "sandbox" y "kernel_bus" quedaron eliminados de esta lista: la
# reestructuración de arquitectura de 2026-07-20 los movió a kernel/
# (api/broker/lifecycle/permissions/registry/services) + sdk/ (la base
# pura de la que kernel/ depende). Un `package_distribution.sh` corrido
# ANTES de esta corrección generaba un zip roto: le faltaba
# directamente el núcleo del proyecto (kernel/, sdk/), y arrastraba una
# advertencia inofensiva pero engañosa de "sandbox no encontrado".
INCLUDE_DIRS=(
    "agent_core"
    "audit"
    "code_analysis"
    "config"
    "error_handling"
    "frontend"
    "kernel"
    "sdk"
    "scripts"
    "skills"
    "task_execution"
    "tests"
    "tool_integration"
    "utils"
    "vscode-extension"
)

INCLUDE_FILES=(
    "Dockerfile"
    "docker-compose.yml"
    "README.md"
    "CONTRIBUTING.md"
    "LICENSE"
    "requirements.txt"
    ".env.example"
)

# Crear directorio temporal para la distribución
TEMP_DIR=$(mktemp -d)
DIST_PACKAGE_DIR="$TEMP_DIR/$PACKAGE_NAME"

echo "Creando directorio de empaquetado temporal: $DIST_PACKAGE_DIR"
mkdir -p "$DIST_PACKAGE_DIR"

# Copiar directorios
for dir in "${INCLUDE_DIRS[@]}"; do
    if [ -d "$PROJECT_ROOT/$dir" ]; then
        echo "Copiando directorio: $dir"
        cp -r "$PROJECT_ROOT/$dir" "$DIST_PACKAGE_DIR/"
    else
        echo "Advertencia: Directorio no encontrado: $dir"
    fi
done

# Copiar archivos
for file in "${INCLUDE_FILES[@]}"; do
    if [ -f "$PROJECT_ROOT/$file" ]; then
        echo "Copiando archivo: $file"
        cp "$PROJECT_ROOT/$file" "$DIST_PACKAGE_DIR/"
    else
        echo "Advertencia: Archivo no encontrado: $file"
    fi
done

# Crear directorio de datos con estructura básica
DATA_DIR="$DIST_PACKAGE_DIR/data"
mkdir -p "$DATA_DIR/artifacts/images" "$DATA_DIR/artifacts/audio" "$DATA_DIR/artifacts/video" "$DATA_DIR/artifacts/browser" "$DATA_DIR/artifacts/uploads"
mkdir -p "$DIST_PACKAGE_DIR/logs"

# Crear archivo de instrucciones
cat > "$DIST_PACKAGE_DIR/INSTALLATION_INSTRUCTIONS.txt" << EOF
INSTALACIÓN DE KAL
==================

1. PREREQUISITOS:
   - Docker Engine (v24+ recomendado)
   - Python 3.11
   - Ollama (opcional para chat, necesario para pruebas completas)
   - ffmpeg instalado en el sistema: sudo apt install ffmpeg

2. CONFIGURACIÓN INICIAL:
   - Copia .env.example a .env y completa las credenciales
   - Asegúrate de tener Docker corriendo antes de iniciar Kal

3. OPCIONES DE EJECUCIÓN:
   
   Opción A - Docker Compose (recomendado):
     docker compose build
     docker compose up
   
   Opción B - Ejecución local (solo para desarrollo):
     pip install -r requirements.txt
     ./scripts/run_kal.sh

4. ACCESO:
   - La interfaz web estará disponible en http://localhost:8000
   - El endpoint API REST estará disponible en el mismo puerto

NOTAS IMPORTANTES:
- Todo código generado se ejecuta en contenedores Docker aislados
- El sistema está configurado por defecto con red aislada (sandbox.network_mode: none)
- Para usar modelos diferentes, asegúrate de tenerlos disponibles en Ollama
- El backend multimodal funciona 100% local sin dependencia de APIs externas

Para más detalles, consulta el README.md
EOF

# Crear script de inicio simplificado
cat > "$DIST_PACKAGE_DIR/start_kal.sh" << 'EOF'
#!/bin/bash

# Script de inicio simplificado para Kal

echo "Iniciando Kal..."
echo "Asegúrate de que Docker esté corriendo antes de continuar."

if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker no está disponible. Por favor inicia Docker."
    exit 1
fi

echo "Selecciona el método de inicio:"
echo "1) Docker Compose (recomendado)"
echo "2) Local (requiere instalación de dependencias)"

read -p "Opción (1 o 2): " option

case $option in
    1)
        echo "Construyendo y levantando contenedores..."
        docker compose build
        docker compose up
        ;;
    2)
        if [ ! -f ".env" ]; then
            echo "Creando archivo .env desde ejemplo..."
            cp .env.example .env
            echo "Por favor edita .env con tus configuraciones antes de continuar"
        fi
        
        echo "Instalando dependencias..."
        pip install -r requirements.txt
        
        echo "Iniciando Kal localmente..."
        ./scripts/run_kal.sh
        ;;
    *)
        echo "Opción inválida"
        exit 1
        ;;
esac
EOF

chmod +x "$DIST_PACKAGE_DIR/start_kal.sh"

# Copiar los nuevos archivos de utilidad
cp "$PROJECT_ROOT/scripts/verify_environment.sh" "$DIST_PACKAGE_DIR/scripts/" 2>/dev/null || echo "Advertencia: verify_environment.sh no encontrado en scripts/"
cp "$PROJECT_ROOT/scripts/usage_guide.md" "$DIST_PACKAGE_DIR/scripts/" 2>/dev/null || echo "Advertencia: usage_guide.md no encontrado en scripts/"
cp "$PROJECT_ROOT/scripts/test_installation.sh" "$DIST_PACKAGE_DIR/scripts/" 2>/dev/null || echo "Advertencia: test_installation.sh no encontrado en scripts/"

# Si los archivos no existían en scripts, crearlos directamente en el paquete
if [ ! -f "$DIST_PACKAGE_DIR/scripts/verify_environment.sh" ]; then
    cp "$PROJECT_ROOT/scripts/verify_environment.sh" "$DIST_PACKAGE_DIR/"
    chmod +x "$DIST_PACKAGE_DIR/verify_environment.sh"
fi

if [ ! -f "$DIST_PACKAGE_DIR/scripts/usage_guide.md" ]; then
    cp "$PROJECT_ROOT/scripts/usage_guide.md" "$DIST_PACKAGE_DIR/"
fi

if [ ! -f "$DIST_PACKAGE_DIR/scripts/test_installation.sh" ]; then
    cp "$PROJECT_ROOT/scripts/test_installation.sh" "$DIST_PACKAGE_DIR/"
    chmod +x "$DIST_PACKAGE_DIR/test_installation.sh"
fi

# Empaquetar en ZIP
echo "Empaquetando en ZIP: $PACKAGE_PATH"
cd "$TEMP_DIR"
zip -r "$PACKAGE_PATH" "$PACKAGE_NAME" -x "*.git*" "*__pycache__*" "*.pyc" "*.pyo" "*.pytest_cache*" ".gitignore" ".dockerignore" "*/node_modules/*" "*/out/*" "*.vsix"

# Limpiar directorio temporal
rm -rf "$TEMP_DIR"

echo ""
echo "=== EMPAQUETADO COMPLETADO ==="
echo "Archivo de distribución creado: $PACKAGE_PATH"
echo ""
echo "CONTENIDO DEL PAQUETE:"
echo "- Código fuente completo del proyecto"
echo "- Archivos de configuración"
echo "- Scripts de inicio, verificación y prueba"
echo "- Guía de uso detallada"
echo "- Documentación de instalación"
echo "- Estructura de directorios inicial"
echo ""
echo "INSTRUCCIONES:"
echo "1. Copia el archivo ZIP a la máquina de destino"
echo "2. Extrae el contenido en el directorio deseado"
echo "3. Ejecuta ./verify_environment.sh para comprobar requisitos"
echo "4. Sigue las instrucciones en INSTALLATION_INSTRUCTIONS.txt"
echo "5. Usa ./test_installation.sh para verificar que todo funciona"
echo ""
echo "¡Listo para distribuir!"