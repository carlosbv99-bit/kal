# Guía de Uso de Kal - Agente IA Autónomo

## Introducción

Kal es un agente de IA autónomo con auto-reparación, memoria en tres niveles y capacidades multimodales (imagen/audio/video). Está diseñado con seguridad como restricción transversal, no como característica adicional.

## Inicio Rápido

### 1. Preparación del Entorno

Antes de iniciar Kal, asegúrate de tener todo listo:

```bash
# Verificar que el entorno esté listo
./scripts/verify_environment.sh
```

### 2. Iniciar Kal

#### Opción A: Docker Compose (Recomendada)
```bash
# Construir imágenes
docker compose build

# Iniciar servicios
docker compose up
```

#### Opción B: Ejecución Local
```bash
# Instalar dependencias
pip install -r requirements.txt

# Iniciar Kal
./scripts/run_kal.sh
```

Kal estará disponible en `http://localhost:8000`

## Características Principales

### 1. Interfaz Web
- Panel de chat para interactuar con el agente
- Indicadores de estado de seguridad en tiempo real
- Panel lateral con tareas recientes, búsqueda en memoria y herramientas

### 2. Seguridad
- Todo código generado se ejecuta en contenedores Docker aislados
- Red aislada por defecto (sin acceso externo)
- Validación AST para prevenir código peligroso
- Registro inmutable de todas las decisiones autónomas

### 3. Memoria en Tres Niveles
- **Corto plazo**: RAM, para contexto de la tarea actual
- **Mediano plazo**: SQLite, para información que persiste entre tareas
- **Largo plazo**: ChromaDB, para conocimiento persistente con embeddings locales

### 4. Capabilities Multimodales
- Generación de imágenes (local con Diffusers + SDXL-Turbo)
- Generación de audio (local con Piper TTS)
- Composición de video (imágenes + audio + FFmpeg)

## Ejemplos de Uso

### Conversación Básica
1. Ve a `http://localhost:8000`
2. Escribe un mensaje en el cuadro de chat
3. El agente responderá con texto o ejecutará herramientas según sea necesario

### Generación de Imagen
Pide al agente que genere una imagen, por ejemplo:
- "Genera una imagen de un zorro en el bosque"
- "Crea un logo para una empresa de tecnología"

### Edición de Imágenes
- Sube una imagen usando el botón de adjuntar
- Pide al agente que edite la imagen, por ejemplo:
  - "Quita el fondo de esta imagen"
  - "Combina estas dos imágenes"

### Navegación Web
Si tienes dominios permitidos configurados:
- "Busca información sobre inteligencia artificial en wikipedia.org"

## Configuración Avanzada

### Modelos de LLM
Por defecto, Kal usa el modelo declarado en `llm.default_model` de
`config/config.yaml`. Puedes cambiarlo:
- En `config/config.yaml`: `llm.default_model`
- O usando el selector en la interfaz web

### Dominios Permitidos para Navegación
Para habilitar navegación web, agrega dominios en `config/config.yaml`:
```yaml
browser:
  allowed_domains: ["wikipedia.org", "github.com"]
```

### Backends Multimodales
Puedes cambiar entre backends locales y API:
- En `config/config.yaml`, bajo `multimodal.image.backend` o `multimodal.audio.backend`
- Opciones: `local` (por defecto) o `api` (requiere API keys)

## Depuración

### Verificar Estado del Sistema
Visita `http://localhost:8000/status` para ver:
- Cadena de auditoría verificada
- Modo de red del sandbox
- Aprobaciones pendientes
- Circuitos abiertos
- Disponibilidad del LLM

### Logs
- Logs de aplicación: directorio `logs/`
- Logs de auditoría: `logs/audit.log`
- Logs de Docker: `docker compose logs`

### Problemas Comunes
- **Sin respuesta del chat**: Verifica que Ollama esté corriendo y tenga un modelo disponible
- **Errores de sandbox**: Verifica que Docker esté corriendo y que no haya circuitos abiertos
- **Errores de multimodal**: Verifica que los modelos necesarios estén descargados

## API REST

Kal también expone una API REST:

- `POST /chat`: Envía un objetivo al agente
- `GET /status`: Obtiene estado del sistema
- `GET /models`: Lista modelos disponibles
- `GET /memory/search`: Busca en la memoria
- `GET /audit/tail`: Últimas entradas de auditoría
- `POST /uploads`: Sube imágenes propias

## Seguridad

### Principios de Seguridad
- **Deny-by-default**: Todo lo que no está explícitamente permitido está bloqueado
- **Sandboxing**: Todo código generado se ejecuta en contenedores aislados
- **Aprobaciones Humanas**: Operaciones sensibles requieren aprobación humana
- **Auditoría**: Todas las decisiones autónomas se registran de forma inmutable

### Control de Acceso
- Las herramientas nuevas requieren aprobación humana antes de activarse
- Los permisos se aplican solo durante la ejecución de herramientas
- Las modificaciones al núcleo requieren revisión humana

## Contribuciones

Después de instalar y probar Kal, puedes explorar:
- Añadir nuevas herramientas en `tool_integration/adapters/`
- Crear nuevas habilidades en el directorio `skills/`
- Extender el sistema de memoria en `agent_core/memory/`
- Mejorar las estrategias de manejo de errores en `error_handling/`

## Recursos Adicionales

- Documentación completa: Lee el archivo `README.md`
- Código fuente: Directorio `agent_core/` para la lógica central
- Tests: Directorio `tests/` para ejemplos de uso de componentes
- Configuración: `config/config.yaml` para personalizar el comportamiento

¡Disfruta explorando las capacidades de Kal!