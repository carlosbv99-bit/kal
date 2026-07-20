/**
 * Validación de rutas propuestas por propose_project_files (ver
 * tool_integration/adapters/vscode_files.py) — sin import de `vscode`,
 * testeable con Node normal (mismo patrón que applyEditFormat.ts).
 *
 * Defensa en profundidad: el backend YA rechaza rutas absolutas o con
 * '..' antes de proponer nada (tool_integration/adapters/vscode_files.py
 * ::_validate_relative_path) — esto es el mismo chequeo repetido del
 * lado de la extensión, que es quien de verdad escribe al disco real y
 * no debería confiar ciegamente en que el backend lo hizo bien.
 */
import * as path from "path";
import { ChatResult, ProjectFilesArtifact } from "./kalClient";

export interface ProjectFile {
  path: string;
  content: string;
}

/**
 * true si `targetFsPath` queda dentro de `rootFsPath` (o es el propio
 * root). Puro (solo usa el módulo `path` de Node) — vivía antes
 * duplicado dentro de projectFiles.ts; se movió acá para que
 * readWorkspaceFile.ts (mismo chequeo de defensa en profundidad, ahora
 * para LECTURA en vez de escritura) lo reuse sin repetir la lógica.
 */
export function isWithinRoot(rootFsPath: string, targetFsPath: string): boolean {
  const normalizedRoot = path.resolve(rootFsPath);
  const normalizedTarget = path.resolve(targetFsPath);
  return normalizedTarget === normalizedRoot || normalizedTarget.startsWith(normalizedRoot + path.sep);
}

/**
 * BUG REAL ENCONTRADO EN USO (2026-07-20): el modelo puede llamar a
 * propose_project_files más de una vez en el mismo turno (p.ej.
 * revisando su propio primer intento) — max_tool_repeats lo acota,
 * pero antes de este fix se mostraba la PRIMERA propuesta de
 * `result.steps`, no la ÚLTIMA. Cualquier revisión posterior (más
 * completa, con un bug corregido, etc.) quedaba descartada en
 * silencio — el usuario nunca la veía. Se usa la ÚLTIMA porque
 * representa el intento más reciente/refinado del modelo antes de
 * responder.
 */
export function findProjectFilesArtifact(result: ChatResult): ProjectFilesArtifact | undefined {
  let found: ProjectFilesArtifact | undefined;
  for (const step of result.steps) {
    if (step.artifact && (step.artifact as ProjectFilesArtifact).modality === "project_files") {
      found = step.artifact as ProjectFilesArtifact;
    }
  }
  return found;
}

/** null si el path es válido; un mensaje de error legible si no. */
export function validateRelativeFilePath(rawPath: string): string | null {
  if (!rawPath || !rawPath.trim()) {
    return "tiene una ruta vacía";
  }
  const normalized = rawPath.replace(/\\/g, "/");
  if (normalized.startsWith("/") || /^[a-zA-Z]:/.test(normalized)) {
    return `'${rawPath}' es una ruta absoluta — se esperaba una ruta relativa al proyecto`;
  }
  if (normalized.split("/").includes("..")) {
    return `'${rawPath}' intenta salir de la carpeta del proyecto ('..')`;
  }
  return null;
}

/** Primer archivo inválido de la lista, o null si todos son válidos. */
export function findFirstInvalidPath(files: ProjectFile[]): string | null {
  for (const file of files) {
    const error = validateRelativeFilePath(file.path);
    if (error !== null) {
      return error;
    }
  }
  return null;
}
