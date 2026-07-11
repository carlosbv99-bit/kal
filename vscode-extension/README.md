# kal-vscode

Extensión de VS Code para hablar con kal (el agente — ver `../agent_core/`)
desde el editor, con contexto del archivo/selección activa (Hito 1) y
aplicación de cambios propuestos directo al editor vía diff nativo +
`WorkspaceEdit` (Hito 2) — ver `../README.md` para el detalle de por qué
esto NO reusa `agent_core/self_modification.py` (ese pipeline es
específico para que kal modifique su propio repo).

## Requisitos

- Node.js 18+ (probado con v22.14.0) y npm.
- kal corriendo (`../scripts/run_kal.sh`) — la extensión es un cliente
  sobre `agent_core/orchestrator.py` (FastAPI, `:8000` por defecto), no
  reimplementa nada del backend.

## Desarrollo

```bash
cd vscode-extension
npm install
npm run compile      # o: npm run watch
```

Abrir esta carpeta en VS Code y presionar F5 (o "Run and Debug" →
"Launch Extension") para levantar un Extension Development Host con la
extensión cargada. Comandos disponibles (paleta de comandos, `Ctrl+Shift+P`):

- **Kal: Abrir chat** — abre el panel de chat.
- **Kal: Preguntar sobre la selección** — toma el archivo/selección activa
  como contexto, lo precarga en el panel de chat.
- **Kal: Aplicar cambios a la selección** — pide una instrucción de
  cambio, le pide a kal el código reescrito, y muestra un diff nativo
  (antes/después) con botones "Aplicar"/"Descartar". "Aplicar" escribe
  el cambio con `WorkspaceEdit` (undo con `Ctrl+Z` como cualquier
  edición manual).

**Continuidad conversacional**: el panel de chat mantiene un
`session_id` por panel (ver `../README.md`, sección "Continuidad
conversacional") — kal recuerda los turnos anteriores de esa misma
conversación mientras el panel siga abierto. Cerrar el panel y abrir
uno nuevo empieza una conversación de cero. La otra vía, "Aplicar
cambios a la selección", NO participa de esto a propósito — es un
pedido puntual de reescritura de código, no una conversación.

### Regla real encontrada en uso: seleccionar bloques balanceados

Validado a mano contra un proyecto Kotlin real: si seleccionás un
fragmento que **no se abre y cierra a sí mismo** (p.ej. `class Foo {`
y `fun bar() {` sin sus llaves de cierre, porque el cierre real está
mucho más abajo en el archivo), kal recibe un fragmento incompleto y
puede "completarlo" agregando sus propias llaves de cierre — que
después CHOCAN con las llaves reales que ya existían más abajo en el
archivo, rompiendo el balance de todo el archivo al aplicar.

**Ahora hay un aviso automático** (`checkBraceBalance` en
`applyEditFormat.ts`): antes de llamar a kal, si la selección tiene
distinta cantidad de `{`/`}`, `(`/`)` o `[`/`]`, aparece un diálogo
modal avisando y preguntando si continuar igual o cancelar. Es un
conteo simple de caracteres, no un parser real por lenguaje — no
distingue llaves dentro de strings/comentarios, así que puede avisar
de más (falso positivo) en casos raros; por eso es una advertencia
salteable, nunca un bloqueo duro. Si te avisa, la solución más simple
suele ser ampliar o achicar la selección hasta que sea autocontenida.

## Configuración

- `kal.serverUrl` (default `http://localhost:8000`)
- `kal.model` (default vacío = usa el default de `config.yaml`)

## Tests

```bash
npm test    # compila + corre los tests unitarios (node --test, sin dependencias extra)
```

Cubre la lógica pura (`KalClient`, con fetch inyectado — sin red real;
`formatEditorContext` y `buildEditGoal`/`extractCodeBlock`, sin
depender del módulo `vscode`). **Límite honesto**: no hay tests de
integración contra un VS Code real (requeriría `@vscode/test-electron`
+ un display utilizable) — no verificado en el entorno de desarrollo de
este proyecto. Probar de verdad con F5 como se describe arriba.
