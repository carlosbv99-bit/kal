#!/usr/bin/env bash
# Construye la imagen minimizada de ejecución del sandbox.
#
# Uso:
#   chmod +x scripts/build_sandbox_image.sh
#   ./scripts/build_sandbox_image.sh
#
# Después de construirla, exportar SANDBOX_IMAGE=kal-sandbox-minimal:latest
# (o dejar que kernel/lifecycle/docker_runner.py la use por defecto si ya la
# renombraste como tal) para que DockerSandboxRunner la use en vez de
# python:3.11-slim genérico.

set -euo pipefail

IMAGE_TAG="kal-sandbox-minimal:latest"

echo "== Construyendo ${IMAGE_TAG} =="
docker build -t "${IMAGE_TAG}" -f kernel/lifecycle/images/minimal/Dockerfile .

echo "== Imagen construida. Tamaño: =="
docker images "${IMAGE_TAG}" --format "{{.Repository}}:{{.Tag}}  {{.Size}}"

echo ""
echo "Para usarla, exporta:"
echo "  export SANDBOX_IMAGE=${IMAGE_TAG}"
echo "o agrégalo a tu .env"
