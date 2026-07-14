# Guía: usar kal como agente de IA en VS Code

Esta guía es para quien nunca usó kal antes. Está pensada para
seguirse de arriba a abajo, en orden, sin saltarse pasos. Cada paso
tiene un "✅ Cómo saber que funcionó" — si en algún punto ese
checkpoint no se cumple, pará ahí y revisá la sección
"Problemas comunes" al final antes de seguir.

No hace falta saber programar para completar esta guía: son todos
comandos para copiar y pegar en una terminal, y clics en VS Code.

**Atajo**: si tu sistema es Ubuntu/Debian, `scripts/setup_all.sh`
automatiza toda la Parte 1, 2 y 4.1-4.2 de una sola vez (instala lo
que falte, pidiendo confirmación antes de cada cambio al sistema, y
deja la extensión instalada de forma permanente en VS Code, sin
F5). Se puede volver a correr las veces que quieras — lo que ya está
hecho, lo salta.

```bash
./scripts/setup_all.sh
```

Si preferís entender cada paso a mano (o tu sistema no es
Ubuntu/Debian), seguí el resto de esta guía.

---

## Qué vas a tener al final

Un panel de chat dentro de VS Code donde le podés hablar a kal en
lenguaje natural sobre tu código: pedirle que explique una función,
que la reescriba, o que aplique un cambio directo al archivo con un
botón "Aplicar" (como una edición manual, se puede deshacer con
`Ctrl+Z`).

---

## Parte 1 — Instalar lo que kal necesita

kal corre en tu máquina (no en la nube). Necesita cuatro programas
instalados antes de arrancar por primera vez.

### 1.1. Docker

kal ejecuta cada "skill" (capacidad, como generar una imagen o un QR)
en un contenedor Docker aislado, por seguridad — nunca en tu sistema
directamente.

- Instalar Docker Desktop (o Docker Engine en Linux) siguiendo la
  guía oficial de [docker.com](https://docs.docker.com/get-docker/).
- Abrí Docker y dejalo corriendo en segundo plano.

**✅ Cómo saber que funcionó**: en una terminal, corré:

```bash
docker info
```

Si ves información (versión, contenedores, etc.) y no un error, está
bien. Si dice algo como "Cannot connect to the Docker daemon", Docker
no está corriendo — abrilo y esperá a que termine de iniciar.

### 1.2. Python 3.11 o superior

- Instalar desde [python.org](https://www.python.org/downloads/) (o
  el gestor de paquetes de tu sistema).

**✅ Cómo saber que funcionó**:

```bash
python3 --version
```

Debe mostrar `Python 3.11.x` o más nuevo.

### 1.3. Ollama (el motor de IA local)

kal no manda tu código a ningún servidor externo — usa un modelo de
lenguaje corriendo en tu propia máquina vía Ollama.

- Instalar desde [ollama.com](https://ollama.com/download).
- Descargar un modelo (el proyecto usa `qwen3-coder:30b` por
  default; si tu máquina tiene poca RAM/VRAM, un modelo más chico
  también funciona, solo cambiá `kal.model` más adelante en la Parte
  4):

```bash
ollama pull qwen3-coder:30b
```

Esto puede tardar varios minutos (son varios GB de descarga).

**✅ Cómo saber que funcionó**:

```bash
ollama list
```

Debe aparecer el modelo que descargaste en la lista.

### 1.4. Node.js 18 o superior (solo para la extensión de VS Code)

- Instalar desde [nodejs.org](https://nodejs.org/) (versión LTS).

**✅ Cómo saber que funcionó**:

```bash
node --version
```

Debe mostrar `v18.x` o más nuevo.

---

## Parte 2 — Preparar el proyecto kal

Estos pasos se hacen **una sola vez**.

### 2.1. Instalar las dependencias de Python

Parado en la carpeta raíz del proyecto (donde está `requirements.txt`):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Esto crea un entorno aislado (`.venv`) para no mezclar paquetes de
kal con otros proyectos de Python que tengas.

**✅ Cómo saber que funcionó**: el comando termina sin errores en
rojo. Si más adelante abrís una terminal nueva, acordate de repetir
`source .venv/bin/activate` antes de correr cualquier script de kal
(o `venv\Scripts\activate` en Windows).

### 2.2. (Opcional pero recomendado) Verificar todo de una vez

El proyecto trae un script que chequea Docker, Python, Ollama y
ffmpeg juntos:

```bash
./scripts/verify_environment.sh
```

**✅ Cómo saber que funcionó**: cada línea debe mostrar `✓`. Si ves
`⚠` en Ollama, no es grave si ya lo instalaste en la Parte 1 — puede
que el script no lo detecte por PATH; confirmá con `ollama list` como
en el paso 1.3.

### 2.3. Instalar la extensión de VS Code

```bash
cd vscode-extension
npm install
npm run compile
```

**✅ Cómo saber que funcionó**: no hay errores en rojo al final de
`npm run compile`, y ahora existe una carpeta `vscode-extension/out/`.

---

## Parte 3 — Arrancar kal

Cada vez que quieras usar kal (no solo la primera vez), tenés que
tener estas dos cosas corriendo **antes** de abrir VS Code:

1. **Docker** abierto.
2. **kal mismo**, en una terminal:

```bash
source .venv/bin/activate    # si no está ya activado
./scripts/run_kal.sh
```

Dejá esa terminal abierta — ahí vas a ver los logs de kal mientras
lo uses. No cierres esa ventana mientras trabajás.

**✅ Cómo saber que funcionó**: el script imprime
`Arrancando kal en http://localhost:8000` y se queda esperando (no
vuelve al prompt). Si en cambio ves `ERROR: Docker no está corriendo`,
volvé al paso 1.1.

---

## Parte 4 — Cargar la extensión en VS Code

**La forma más simple**: con kal corriendo (Parte 3), abrí
`http://localhost:8000` en el navegador, pestaña **"Integraciones"**
→ tarjeta "VS Code" → botón **"Instalar"**. Un solo clic compila,
empaqueta e instala la extensión de forma permanente — no hace falta
F5 ni tocar una terminal.

**Si VS Code ya estaba abierto** en ese momento, esa ventana no se
entera sola del cambio: recargala una vez con `Ctrl+Shift+P` →
"Developer: Reload Window" (o cerrá y volvé a abrir VS Code) antes de
buscar los comandos `Kal: ...` en la paleta. Si VS Code todavía no
estaba abierto, no hace falta nada de esto — abrilo después de
instalar y ya va a estar listo.

Si corriste `scripts/setup_all.sh` (el atajo del principio), esta
parte ya está hecha de la misma forma — podés saltar directo a la
Parte 5 (con la misma salvedad del reload si VS Code ya estaba
abierto cuando corriste el script).

Si preferís el modo manual (o ninguna de las dos formas de arriba
pudo instalarla automáticamente), seguí estos pasos:

### 4.1. Abrir el proyecto en modo de desarrollo de la extensión

1. Abrí VS Code.
2. `Archivo → Abrir carpeta...` y elegí `vscode-extension/` (la
   subcarpeta, no la raíz del proyecto).
3. Presioná **F5** (o andá a la pestaña "Run and Debug" en la barra
   lateral izquierda y hacé clic en el botón ▶ verde, con
   "Launch Extension" seleccionado arriba).

Esto abre una **segunda ventana** de VS Code llamada
"Extension Development Host" — es una ventana normal de VS Code, pero
con la extensión de kal ya cargada. Vas a trabajar en **esa** ventana,
no en la primera.

**✅ Cómo saber que funcionó**: se abrió la segunda ventana y no
apareció ningún cuadro de error rojo en la esquina inferior derecha.

### 4.2. Abrir tu proyecto real dentro de esa ventana

En la ventana "Extension Development Host": `Archivo → Abrir
carpeta...` y elegí la carpeta del proyecto en el que querés que kal
te ayude (puede ser cualquier proyecto tuyo, no tiene que ser kal).

### 4.3. Probar el chat

Tres formas de abrirlo, la extensión instalada trae las tres:

- **Ícono en la barra lateral izquierda** (Activity Bar): un ícono
  nuevo con forma de "k", junto a los íconos de otras extensiones
  (Copilot, etc. si las tenés). Un clic abre el chat ahí mismo, fijo
  en la barra lateral — no compite con tus pestañas de código.
- **Ítem en la barra de estado** (abajo a la derecha): "💬 Kal" — un
  clic abre el chat de siempre (en una pestaña al costado).
- **Paleta de comandos**: `Ctrl+Shift+P` → escribí `Kal: Abrir chat` →
  Enter.

Escribí algo simple como "hola, ¿estás funcionando?" y enviá.

Nota: el chat de la barra lateral es una conversación **separada** de
la que abrís con la barra de estado o la paleta — cada una tiene su
propio historial, no comparten contexto.

**✅ Cómo saber que funcionó**: kal responde en el panel en menos de
unos segundos (la primera respuesta puede tardar más si Ollama está
cargando el modelo por primera vez).

Si en cambio el panel se queda cargando indefinidamente o muestra un
error de conexión, revisá la terminal de la Parte 3: ahí va a
aparecer el motivo real (por ejemplo, Ollama no responde).

---

## Parte 5 — Usar kal sobre tu código

Con un archivo de código abierto en la ventana "Extension Development
Host":

### 5.1. Preguntar sobre una selección

1. Seleccioná un fragmento de código (por ejemplo, una función).
2. `Ctrl+Shift+P` → `Kal: Preguntar sobre la selección`.
3. Se abre el chat con esa selección adjunta (vas a ver una etiqueta
   tipo 📎 con el nombre del archivo). Escribí tu pregunta, por
   ejemplo "¿qué hace esta función?" o "¿tiene algún bug?".

### 5.2. Pedir que aplique un cambio directo

1. Seleccioná el fragmento que querés modificar. **Importante**:
   seleccioná un bloque completo y balanceado (si abrís una llave `{`
   dentro de la selección, su `}` de cierre también tiene que estar
   dentro). Si no, kal va a avisarte con un diálogo antes de
   continuar.
2. `Ctrl+Shift+P` → `Kal: Aplicar cambios a la selección`.
3. Escribí la instrucción, por ejemplo "convertí esto a async/await".
4. kal te muestra un diff (antes/después). Si te convence, hacé clic
   en "Aplicar" — el cambio queda escrito en el archivo, y se puede
   deshacer con `Ctrl+Z` como cualquier edición manual. Si no te
   convence, "Descartar" no toca nada.

**✅ Cómo saber que funcionó**: el archivo cambió en el editor
después de "Aplicar", y `Ctrl+Z` lo revierte si te arrepentís.

---

## Problemas comunes

**"kal.serverUrl" / el chat no conecta**
Confirmá que la terminal de la Parte 3 sigue abierta y sin errores.
Si cerraste esa terminal, el backend de kal se apagó — volvé a
correr `./scripts/run_kal.sh`.

**Las respuestas tardan mucho o nunca llegan**
Es casi siempre Ollama: confirmá con `ollama list` que el modelo está
descargado, y con `curl http://localhost:11434/api/tags` que Ollama
está respondiendo. Un modelo grande (`qwen3-coder:30b`) puede tardar
si tu máquina no tiene suficiente RAM/VRAM — podés cambiar a un
modelo más chico en VS Code: `Archivo → Preferencias → Configuración`,
buscar `kal.model`, y poner el nombre de otro modelo que ya hayas
descargado con `ollama pull`.

**Docker tira error al primer uso de una skill (generar imagen, QR, etc.)**
La primera vez que se usa una skill, kal construye su imagen de
Docker — puede tardar un par de minutos. Mirá la terminal de la
Parte 3, ahí se ve el progreso real.

**Cerré la ventana del chat sin querer**
No pasa nada grave, pero perdés el hilo de esa conversación (cada
panel de chat es una conversación independiente). Abrí uno nuevo con
`Kal: Abrir chat`.
