# Contribuir con una Skill

🇬🇧 [English](CONTRIBUTING.md) | 🇪🇸 Español

El Skill Market de Kal ([explorarlo acá](https://carlosbv99-bit.github.io/kal/))
es la carpeta `skills/` de este repositorio. Publicar una Skill
significa abrir un pull request contra ella.

## Cómo publicar

1. Forkeá este repo, agregá tu Skill en `skills/<nombre-de-tu-skill>/`
   (`skill.yaml` + tu código — mirá cualquier skill existente en
   `skills/` para el formato del manifiesto).
2. Firmala con tu **propio** keypair, nunca el de otra persona:
   ```
   python3 scripts/sign_skill.py skills/<nombre-de-tu-skill>/ --key-dir <tu-directorio-de-claves>
   ```
   Guardá `<tu-directorio-de-claves>` en un lugar persistente — firmar
   una versión futura con el mismo directorio la atribuye al mismo
   autor.
3. Abrí un pull request.

## Qué se chequea automáticamente, y qué no

Un check de CI (`scripts/validate_skills.py`) corre en cada pull
request y bloquea el merge hasta que pase. Verifica **únicamente la
integridad del paquete**:
- Que tu `skill.yaml` parsea correctamente.
- Que tu `skill.sig` está presente y verifica criptográficamente
  contra el contenido actual de la carpeta de tu Skill.

**No** chequea, ni puede chequear:
- Si tu código hace lo que la descripción dice.
- Si los permisos que declaraste tienen sentido para lo que la Skill
  realmente hace.
- Si la Skill es segura, está bien escrita, o es maliciosa.

Una firma válida prueba que el paquete no fue alterado desde que lo
firmaste — no dice nada sobre si el contenido debería ser confiable.
Por eso cada pull request también recibe una **revisión manual de un
mantenedor** antes de mergear, hoy enteramente un juicio humano, no
automatizado. Esto es un cuello de botella real al tamaño actual de
este proyecto, no una solución que escale — puede evolucionar a medida
que la comunidad crezca.

## Sandbox local, no una API con ruedas de entrenamiento

Las Skills siempre corren en un contenedor Docker efímero y aislado
por cada llamada — sin red, filesystem de solo lectura, non-root, sin
acceso permanente a nada fuera de `/workspace` — sin importar cómo
fueron instaladas. Ver [README.es.md](README.es.md) para la
arquitectura completa.
