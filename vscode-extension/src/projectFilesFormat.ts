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

export interface ProjectFile {
  path: string;
  content: string;
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
