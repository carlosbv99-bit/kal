"""
Kernel Service Bus: protocolo genérico por el que una skill AISLADA
(corriendo dentro de un contenedor Docker efímero, sin red, sin
memoria compartida con el proceso principal) puede pedirle algo a un
servicio de confianza que vive en el proceso principal — sin nunca
importar código del kernel, sin nunca recibir una referencia a un
objeto Python real.

Por qué esto existe: 4 de las 6 herramientas de primera parte
(image_gen, image_editing, audio_gen, speech_to_text) cargan un modelo
pesado de forma perezosa (hasta 14GB) y lo mantienen caliente en
memoria entre llamadas — posible hoy porque viven en un proceso que
nunca muere. Una skill aislada corre en un contenedor EFÍMERO (uno
nuevo por llamada) — sin este bus, cada llamada de una skill que
necesite ese modelo tendría que recargarlo entero desde disco cada vez.

Analogía de diseño (no un patrón inventado para este proyecto): mismo
principio que LSP (Language Server Protocol, JSON-RPC sobre stdio) o
el extension host de VS Code — un proceso aislado habla con el host
SOLO por mensajes estructurados, nunca por memoria compartida.

Capas:
  - protocol.py     — formato de mensaje (JSON-RPC 2.0), funciones puras
  - services.py     — los servicios reales (hoy: ImageService)
  - bus.py          — registro de servicios + despacho por nombre
  - socket_server.py — expone el bus a un contenedor vía un socket Unix
                        (tool_integration/sandboxed_skill.py lo arranca
                        por ejecución; tool_integration/kernel_client.py
                        es el SDK minúsculo que la skill usa del otro lado)

Alcance actual (deliberado, no una limitación no revisada): un solo
servicio real, `image.generate`. Audio/STT/inpaint quedan como el
mismo patrón aplicado después, una vez validado con este primero.
Browser/OCR/Antivirus (mencionados en la visión de plataforma) quedan
documentados como extensión futura — ninguno existe todavía como
capacidad real en kal, construirles bus ahora sería infraestructura
sin demanda real.
"""
