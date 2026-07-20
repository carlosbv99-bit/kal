#!/usr/bin/env python3
"""
Script para empaquetar los archivos importantes del proyecto Kal en un archivo ZIP.
Este script recopila todos los archivos clave necesarios para que un especialista
tenga una visión completa del proyecto.
"""

import os
import zipfile
from datetime import datetime
from pathlib import Path


def create_kal_package():
    """Función principal para crear el paquete ZIP del proyecto Kal."""
    
    # Directorio raíz del proyecto
    project_root = Path(__file__).parent
    package_name = f"kal_project_package_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    
    # Lista de archivos y directorios importantes a incluir
    important_files_and_dirs = [
        # Documentación principal
        "README.md",
        "CONTRIBUTING.md",
        "scripts/usage_guide.md",
        
        # Configuración
        "config/config.yaml",
        "Dockerfile",
        "docker-compose.yml",
        
        # Directorios principales
        # "kernel/" ya cubre api/broker/lifecycle/permissions/registry/
        # services (rglob de más abajo trae todo lo de adentro solo) —
        # las entradas separadas que había antes para cada subcarpeta de
        # kernel/ eran redundantes. "sdk/" es la base pura de la que
        # kernel/ depende (Tool/Artifact/Permission) — faltaba por
        # completo antes de esta corrección (2026-07-20): un paquete
        # generado sin esto no podía ni importar una Skill.
        "agent_core/",
        "kernel/",
        "sdk/",
        "skills/",

        # Scripts importantes
        "scripts/run_kal.sh",
        "scripts/setup_all.sh",
        "scripts/verify_environment.sh",
        "scripts/test_installation.sh",
        "scripts/generate_market_page.py",
        "scripts/install_from_market.py",
        "scripts/enable_skill.py",
        "scripts/sign_skill.py",
        "scripts/validate_skills.py",
        "scripts/verify_sandbox.sh",

        # Componentes de seguridad
        "code_analysis/",
        "error_handling/",
        "audit/",

        # Núcleo de integración de herramientas
        "tool_integration/",
        
        # Integración con VS Code
        "vscode-extension/",
        "vscode-extension/README.md",
        "vscode-extension/package.json",
        
        # Pruebas
        "tests/",
        
        # Utilidades
        "utils/",
        
        # Análisis de código
        "code_analysis/",
        
        # Carpeta frontend si existe
        "frontend/",
        
        # Archivos de configuración adicionales
        "requirements.txt",
        "setup.py",
        ".gitignore"
    ]
    
    # Crear el archivo ZIP
    with zipfile.ZipFile(package_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        files_added = 0
        
        for item in important_files_and_dirs:
            full_path = project_root / item
            
            if full_path.exists():
                if full_path.is_file():
                    # Agregar archivo individual
                    zipf.write(full_path, item)
                    print(f"Agregado archivo: {item}")
                    files_added += 1
                elif full_path.is_dir():
                    # Agregar todos los archivos en el directorio
                    for file_path in full_path.rglob('*'):
                        if file_path.is_file():
                            # Calcular ruta relativa dentro del ZIP
                            relative_path = file_path.relative_to(project_root)
                            zipf.write(file_path, relative_path)
                            print(f"Agregado archivo: {relative_path}")
                            files_added += 1
                else:
                    print(f"Advertencia: {item} no existe")
            else:
                print(f"Advertencia: {item} no existe")
    
    print(f"\nPaquete creado exitosamente: {package_name}")
    print(f"Total de archivos agregados: {files_added}")
    print("El paquete contiene los archivos principales del proyecto Kal para análisis por un especialista.")


if __name__ == "__main__":
    create_kal_package()