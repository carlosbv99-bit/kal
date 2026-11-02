"""
Tests que verifican que la documentación no mienta.

Motivo concreto, no teórico: el README afirma el tamaño de la suite y que el
repo no tiene dependencias de LLM/ML, y **ninguna de las dos cosas estaba
verificada por nada**. La primera ya se había desincronizado (decía 367 y la
suite tenía más). Una afirmación que nadie chequea es una afirmación que se
pudre, que es el mismo problema que un control de seguridad que no cubre nada.

Estos tests fallan si:

- alguno de los cuatro documentos no dice el número REAL de tests, o si además
  quedó otro número envejecido con la misma forma;
- la afirmación "sin agente, sin LLM, sin ML" deja de ser cierta porque
  `agent_core`/`tool_integration` empezaron a importarse, o porque
  `requirements-core.txt` ganó un paquete de LLM/ML.

Sobre el número: se compara contra la COLECCIÓN, no contra los tests que pasan.
La colección es determinista y no depende de esta máquina; cuántos pasan sí
depende de si Docker está disponible y de si el daemon vive en otro mount
namespace. El estado de la suite lo reporta CI, no un README.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

DOCS_CON_NUMERO = {
    "README.md": "{n} tests",
    "README.es.md": "{n} tests",
    "CONTRIBUTING.md": "{n} tests today",
    "CONTRIBUTING.es.md": "{n} tests hoy",
}

MODULOS_DEL_HOST = ("agent_core", "tool_integration")

PAQUETES_PROHIBIDOS = (
    "torch", "diffusers", "transformers", "langchain", "llama-index", "llama_index",
    "openai", "anthropic", "ollama", "scikit-learn", "sklearn", "chromadb",
    "sentence-transformers", "vllm", "accelerate", "peft",
)

_PATRON_NUMERO = re.compile(r"\d{2,4} tests?(?: today| hoy)?")


def _total_por_coleccion() -> int:
    """Cuenta los tests colectados, en un subproceso.

    `--collect-only` no ejecuta nada, así que no hay recursión; y al no
    ejecutar, tampoco depende de Docker.
    """
    resultado = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
    )
    assert resultado.returncode == 0, (
        "no se pudo colectar la suite:\n" + resultado.stderr[-2000:]
    )
    coincidencia = re.search(r"(\d+) tests? collected", resultado.stdout)
    assert coincidencia is not None, (
        "no encontré el total en la salida de --collect-only:\n" + resultado.stdout[-2000:]
    )
    return int(coincidencia.group(1))


def test_los_docs_dicen_el_numero_real_de_tests():
    total = _total_por_coleccion()
    problemas: list[str] = []

    for nombre, plantilla in DOCS_CON_NUMERO.items():
        texto = (RAIZ / nombre).read_text(encoding="utf-8")
        esperado = plantilla.format(n=total)
        if esperado not in texto:
            problemas.append(f"{nombre}: no dice «{esperado}»")
            continue
        # Y que no quede OTRO número envejecido en el mismo archivo: es
        # exactamente cómo se desincronizó la vez anterior.
        otros = sorted({m.group(0) for m in _PATRON_NUMERO.finditer(texto)} - {esperado})
        if otros:
            problemas.append(f"{nombre}: además dice {otros}")

    assert problemas == [], (
        f"La documentación no coincide con la suite (tiene {total} tests).\n  "
        + "\n  ".join(problemas)
        + "\n\nActualizá esos archivos al número real: es el mismo número que "
        "reporta `python -m pytest --collect-only -q`."
    )


def test_el_repo_sigue_sin_codigo_de_agente_ni_de_llm():
    """La afirmación que define al repo, y que hasta ahora era solo prosa:
    «sin agente, sin LLM, sin ML incluido»."""
    codigo = (
        "import importlib\n"
        f"for modulo in {MODULOS_DEL_HOST!r}:\n"
        "    try:\n"
        "        importlib.import_module(modulo)\n"
        "    except ModuleNotFoundError:\n"
        "        continue\n"
        "    raise SystemExit('IMPORTA ' + modulo)\n"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True
    )
    assert resultado.returncode == 0, (
        "el kernel ahora importa código del host: "
        f"{resultado.stdout.strip() or resultado.stderr[-800:]}"
    )

    requirements = (RAIZ / "requirements-core.txt").read_text(encoding="utf-8").casefold()
    encontrados = [
        paquete
        for paquete in PAQUETES_PROHIBIDOS
        if re.search(r"(?m)^\s*" + re.escape(paquete) + r"\b", requirements)
    ]
    assert encontrados == [], (
        f"requirements-core.txt ganó dependencias de LLM/ML: {encontrados}. "
        "La afirmación del README dejaría de ser cierta."
    )
