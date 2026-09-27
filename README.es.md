# Kal

🇬🇧 [English](README.md) | 🇪🇸 Español

> Un kernel no le pregunta al código de un agente de IA si es
> confiable — se asegura de que nunca tenga que serlo.

**Un microkernel de seguridad puro para capacidades de agentes de IA — sin agente, sin LLM, sin ML incluido.**

Todo framework de agentes de IA tarde o temprano tiene que responder
la misma pregunta: cuando el código de un agente falla — una llamada a
herramienta mal hecha, una dependencia comprometida, una inyección de
prompt que lo convence de hacer algo que no debería — ¿qué es lo que
realmente lo detiene? Demasiadas veces la respuesta honesta es "nada
incorporado, simplemente confiamos en el código". Kal está construido
alrededor de la respuesta contraria: un microkernel de seguridad que
media todo lo que un agente — o cualquier pieza de código que corra
como una de sus herramientas — puede tocar, impuesto desde afuera de
ese código, de manera que ninguna Skill individual necesite ser
confiable para que todo el sistema se mantenga seguro.

Kal se extrajo de [kal-in](https://github.com/carlosbv99-bit/kal-in)
(el propio agente de referencia de kal) en septiembre de 2026, una vez
que quedó claro que los dos necesitaban poder usarse de forma
independiente: un kernel que media lo que cualquier agente — el propio
agente de referencia de kal-in, o uno de terceros — puede hacer, sin
traer empaquetadas las herramientas de un agente específico. El primer
consumidor de esta separación es
[Likay-OS](https://github.com/Kevindelb/Likay-OS), un sistema
operativo para agentes de IA que necesita un kernel que pueda montar
debajo de *cualquier* agente sin que el kernel choque con el conjunto
de herramientas propio de ese agente.

## Qué hay aquí

- **Access Manager / Cascada de Permisos** (`kernel/permissions/`) —
  acceso por niveles, deny-by-default, a filesystem y red, con
  puertas explícitas de aprobación humana.
- **Sandbox** (`kernel/lifecycle/`) — cada skill no confiable corre en
  un contenedor Docker aislado y non-root, sin importar de dónde vino.
- **Registro de Herramientas** (`kernel/registry/`) — registro
  genérico, versionado, rollback y verificación de firma criptográfica
  para herramientas/skills. Decidir *cuáles* herramientas existen por
  defecto es política del agente, no mecanismo del kernel — este repo
  no registra ninguna.
- **Audit Log** (`audit/`) — registro encadenado por hash, a prueba de
  alteraciones, de cada acción sensible.
- **Kernel Service Bus** (`kernel/api/`) — protocolo genérico de
  despacho por nombre + servidor de socket Unix para que una skill
  sandboxeada pueda llamar a un servicio sin ver nunca una ruta real
  del filesystem.
- **Resource Broker** (`kernel/broker/`) — rastrea y desaloja recursos
  bajo presión de memoria; ciego a cualquier cosa que un agente no
  registre explícitamente con él (ver el roadmap de Likay-OS para
  cerrar esa brecha en agentes mediados externamente).
- **SDK** (`sdk/`) — la superficie pública estable, versionada, 100%
  stdlib, que una Skill o agente usa para hablar con el kernel
  (`Tool`, `ToolManifest`, `Artifact`, `Permission`) — nunca los
  internos del kernel directamente.
- **Análisis estático de código** (`code_analysis/`) — validación a
  nivel AST de código de herramientas propuesto dinámicamente, antes
  de que llegue a un sandbox.

Este repo tiene **cero** dependencia de cualquier LLM, librería de ML,
o framework de agente específico — verificado, no asumido: tanto
`import agent_core` como `import tool_integration` fallan aquí con
`ModuleNotFoundError`.

## Qué NO hay aquí

Todo lo que decide *qué hace un agente* — el loop de razonamiento, las
implementaciones de herramientas (generación de imagen/audio/video,
automatización de navegador, memoria), la selección de modelo, los
prompts — vive en [kal-in](https://github.com/carlosbv99-bit/kal-in),
el propio agente de referencia de kal, construido sobre este kernel.
Un agente de terceros podría construirse igual de bien sobre este
mismo kernel.

## Estado

Extraído preservando el historial de git de cada archivo que se movió
aquí (`git log --follow` sobre cualquier ruta bajo `kernel/`/`sdk/`/
`audit/` muestra su historia desde antes de la separación). 367 tests,
autocontenido, instalando solo `requirements-core.txt` — sin código de
agente, sin librerías de ML.

## Cómo colaborar

Es un proyecto joven, en desarrollo activo, y hay lugar de verdad para
aportar — no hace falta haber escrito un framework de agentes para
tener algo que sumar aquí. Revisión de seguridad, probar el sandbox
contra casos que no se nos ocurrieron, y simplemente hacer preguntas
difíciles sobre el modelo de amenazas son todos aportes genuinamente
útiles.

- Abre un [issue](https://github.com/carlosbv99-bit/kal/issues) para
  proponer algo, reportar un bug, o preguntar por dónde empezar.
- Ver [CONTRIBUTING.es.md](CONTRIBUTING.es.md) para cómo armar un
  entorno de desarrollo, correr los tests, y dónde en el código entra
  un cambio dado.
- Si quieres escribir o hablar sobre este proyecto, este README y el
  código mismo son la fuente primaria — cada afirmación aquí está
  pensada para poder verificarse contra lo que realmente hay en el
  repo. Ese mismo nivel de minuciosidad es el método diario de
  trabajo: cada cambio se revisa y se verifica en coordinación
  permanente con Claude (Anthropic), no solo se documenta después.

Licencia: [Apache 2.0](LICENSE).
