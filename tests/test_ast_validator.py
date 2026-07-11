from code_analysis.ast_validator import validate_code


def test_safe_code_passes():
    result = validate_code("x = 1 + 2\nprint(x)")
    assert result.is_safe
    assert result.is_valid_syntax


def test_syntax_error_detected():
    result = validate_code("def broken(:\n    pass")
    assert not result.is_valid_syntax
    assert not result.is_safe


def test_forbidden_call_detected():
    result = validate_code("eval('1+1')")
    assert not result.is_safe
    assert any("eval" in v for v in result.violations)


def test_forbidden_import_detected():
    result = validate_code("import os\nos.system('ls')")
    assert not result.is_safe


def test_forbidden_attribute_detected():
    result = validate_code("x.__globals__")
    assert not result.is_safe


def test_getattr_bypass_of_attribute_check_is_blocked():
    """
    getattr(x, '__subclasses__') no genera un nodo ast.Attribute, así
    que sin bloquear getattr explícitamente, este bypass pasaría el
    chequeo de FORBIDDEN_ATTRIBUTES sin ser detectado.
    """
    result = validate_code("getattr(object(), '__subclasses__')")
    assert not result.is_safe


def test_setattr_is_blocked():
    result = validate_code("setattr(object(), 'x', 1)")
    assert not result.is_safe


def test_globals_locals_vars_are_blocked():
    for call in ("globals()", "locals()", "vars()"):
        result = validate_code(call)
        assert not result.is_safe, f"{call} debería estar bloqueado"


def test_importlib_dynamic_import_is_blocked():
    """
    importlib.import_module('os') permite importar cualquier módulo por
    nombre en runtime, evadiendo el chequeo de `import os` literal.
    """
    result = validate_code("import importlib\nimportlib.import_module('os')")
    assert not result.is_safe


def test_known_residual_gap_documented_not_silently_fixed():
    """
    Este test documenta (no oculta) un hueco conocido: el chequeo actual
    no analiza literales de string para detectar construcción dinámica
    de nombres de atributos prohibidos por concatenación pura de strings
    sin pasar por getattr/setattr (p.ej. una f-string usada luego en un
    mecanismo distinto). Se deja explícito aquí para que cualquier
    cambio futuro al validador sea deliberado, no una regresión
    silenciosa. La garantía real contra esto vive en el aislamiento de
    Docker, no en este validador — ver test_sandbox_escape_resistance.py.
    """
    # Sin getattr/setattr/eval/exec de por medio, no hay forma directa
    # de convertir una string construida dinámicamente en un acceso a
    # atributo o llamada en Python puro — por eso este caso es más
    # teórico que explotable, pero se documenta igual.
    result = validate_code("s = '__subclasses__'\nprint(s)")
    assert result.is_safe  # esto es código inocuo real, no un bypass


def test_class_traversal_trick_blocked_by_static_layer():
    """
    ().__class__.__bases__[0].__subclasses__() es el escape clásico de
    Python (llegar a todas las subclases cargadas, incluida potencialmente
    subprocess.Popen, sin ningún import literal). Usa nodos ast.Attribute
    con nombres literales (__class__, __bases__, __subclasses__), que sí
    están en FORBIDDEN_ATTRIBUTES. Confirma que el filtro barato captura
    al menos la variante no ofuscada de este ataque conocido.
    """
    code = "().__class__.__bases__[0].__subclasses__()"
    result = validate_code(code)
    assert not result.is_safe
