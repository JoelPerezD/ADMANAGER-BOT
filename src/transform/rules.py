"""Traduccion del codigo HTTP a la columna ``resultado final``.

El reporte no guarda codigos numericos, sino un mensaje legible. La conversion se
resuelve con una tabla ``status -> funcion`` en lugar de una cadena de ``if``:
dar de alta un codigo nuevo es anadir una entrada, y cada regla se puede probar
de forma aislada.

Todas las comparaciones de negocio usan :func:`~src.utils.texto.normalizar` en
**ambos** lados. Los literales viven en :mod:`src.config` y ya estan normalizados
en origen, de modo que no existe forma de comparar un dato del log en minusculas
contra un literal en mayusculas.
"""

from __future__ import annotations

from collections.abc import Callable

from src.config import (
    MARCA_CORPORATIVA,
    MENSAJES,
    OU_RESTRINGIDA,
    PREFIJOS_AUTORIZADOS,
    RAZONES_DENEGADO,
    SEPARADOR_RAZONES,
    UMBRAL_TIMEOUT_SEGUNDOS,
)
from src.transform.parser import Operacion, UsuarioAD
from src.utils.texto import empieza_con_alguno, normalizar

#: Firma de una regla: recibe la operacion y devuelve el texto del resultado.
Regla = Callable[[Operacion], str]


def _regla_fija(clave_mensaje: str) -> Regla:
    """Envuelve un mensaje de :data:`~src.config.MENSAJES` como regla.

    La mayoria de los codigos de estado (exito, error interno, sin tokens...)
    no dependen de los datos de la operacion: no hace falta una funcion por
    cada uno, solo declarar que mensaje les corresponde en la tabla de reglas.
    """
    return lambda _: MENSAJES[clave_mensaje]


# --- Predicados de negocio -------------------------------------------------


def _es_autorizado(solicitante: UsuarioAD) -> bool:
    """Indica si el solicitante puede resetear usuarios.

    Solo pueden hacerlo los perfiles cuyo ``DESCRIPTION`` empieza por "gerente" o
    "admin" (por ejemplo ``"Gerente Tienda"`` o ``"Administrador De Sistemas"``).
    """
    return empieza_con_alguno(solicitante.descripcion, PREFIJOS_AUTORIZADOS)


def _comparten_oficina(solicitante: UsuarioAD, target: UsuarioAD) -> bool:
    """Indica si ambos usuarios pertenecen a la misma oficina.

    Si alguna de las dos oficinas viene vacia no se puede afirmar que coincidan,
    asi que se responde ``False``: ante la duda, no se concede el permiso.
    """
    oficina_solicitante = normalizar(solicitante.oficina)
    oficina_target = normalizar(target.oficina)
    return bool(oficina_solicitante) and oficina_solicitante == oficina_target


def _esta_en_ou_restringida(target: UsuarioAD) -> bool:
    """Indica si el usuario objetivo pertenece a la OU restringida."""
    return normalizar(target.ou_name) == OU_RESTRINGIDA


def _tiene_oficina_corporativa(target: UsuarioAD) -> bool:
    """Indica si la oficina del usuario objetivo es corporativa."""
    return MARCA_CORPORATIVA in normalizar(target.oficina)


# --- Una funcion por codigo de estado --------------------------------------


def _resultado_aceptado(operacion: Operacion) -> str:
    """202: la solicitud se acepta porque la oficina del objetivo es corporativa."""
    target = operacion.usuario_target
    if target is not None and _tiene_oficina_corporativa(target):
        return MENSAJES["corporativo"]
    return MENSAJES["aceptado_generico"]


def _resultado_denegado(operacion: Operacion) -> str:
    """403: se concatenan todas las razones por las que se nego el reseteo."""
    solicitante = operacion.usuario_solicitante
    target = operacion.usuario_target
    razones: list[str] = []

    # Cada condicion se evalua solo si hay datos para hacerlo: sin el usuario en
    # AD no se puede afirmar que incumpla la regla.
    if solicitante is not None and not _es_autorizado(solicitante):
        razones.append(RAZONES_DENEGADO["no_autorizado"])

    hay_ambos_usuarios = solicitante is not None and target is not None
    if hay_ambos_usuarios and not _comparten_oficina(solicitante, target):
        razones.append(RAZONES_DENEGADO["oficina_distinta"])

    if target is not None and _esta_en_ou_restringida(target):
        razones.append(RAZONES_DENEGADO["ou_restringida"])

    if not razones:
        razones.append(RAZONES_DENEGADO["sin_causa"])

    return MENSAJES["denegado_prefijo"] + SEPARADOR_RAZONES.join(razones) + "."


def _resultado_no_encontrado(operacion: Operacion) -> str:
    """404: se precisa cual de los dos usuarios no existe en ADManager."""
    falta_solicitante = operacion.usuario_solicitante is None
    falta_target = operacion.usuario_target is None

    if falta_solicitante and falta_target:
        return MENSAJES["no_encontrado_ambos"]
    if falta_solicitante:
        return MENSAJES["no_encontrado_solicitante"]
    # Si el objetivo falta -y tambien cuando el log no permite distinguirlo- se
    # reporta el objetivo, que es el caso observado en la totalidad de los 404.
    return MENSAJES["no_encontrado_target"]


def _resultado_servicio_no_disponible(operacion: Operacion) -> str:
    """503: se concatena el error exacto que devolvio ADManager."""
    if operacion.mensaje_admanager:
        return MENSAJES["servicio_no_disponible"] + operacion.mensaje_admanager
    return MENSAJES["servicio_no_disponible_sin_detalle"]


def _resultado_timeout(operacion: Operacion) -> str:
    """504: se agoto el tiempo de espera de la comunicacion.

    Por regla de negocio el reporte da por hecho que el reseteo no se ejecuto.
    """
    return MENSAJES["timeout"].format(
        umbral=UMBRAL_TIMEOUT_SEGUNDOS,
        duracion=operacion.duracion_segundos,
    )


#: Reglas de la accion "reseteo de usuario", indexadas por codigo HTTP.
REGLAS_RESETEO: dict[int, Regla] = {
    200: _regla_fija("ok"),
    202: _resultado_aceptado,
    403: _resultado_denegado,
    404: _resultado_no_encontrado,
    429: _regla_fija("sin_tokens"),
    500: _regla_fija("error_interno"),
    503: _resultado_servicio_no_disponible,
    504: _resultado_timeout,
}

# --- Reglas de la accion "registro_sap" -------------------------------------
#
# Mensajes tomados literal del PDF "2026-08-25 StatusCodes Alta SAP V2". El
# 403 agrupa deliberadamente "conflicto con el puesto solicitado" (City Club,
# Soriana, gerente) en un unico mensaje generico: el propio documento indica
# descartar esas tres causas por separado. El 202 (ticket creado y no
# cerrado / ticket no creado) y las causas del 400 distintas al numero de
# empleado no numerico (tratamiento invalido, puesto inexistente) no son
# distinguibles todavia con los campos que el parser captura hoy del
# disparador; quedan con el mensaje que da la mayor cobertura del PDF hasta
# que se amplie el parser.


def _resultado_sap_solicitud_invalida(operacion: Operacion) -> str:
    """400: numero de empleado no numerico, o razon indeterminada."""
    if not operacion.target.isdigit():
        return MENSAJES["sap_400_numero_empleado"]
    return MENSAJES["sap_400_desconocido"]


def _resultado_sap_denegado(operacion: Operacion) -> str:
    """403: causas verificables con ADManager; el resto cae en "conflicto
    con el puesto solicitado", tal como pide el PDF.
    """
    solicitante = operacion.usuario_solicitante
    target = operacion.usuario_target

    if solicitante is not None and _tiene_oficina_corporativa(solicitante):
        return MENSAJES["sap_403_oat"]

    hay_ambos_usuarios = solicitante is not None and target is not None
    if hay_ambos_usuarios and not _comparten_oficina(solicitante, target):
        return MENSAJES["sap_403_oficina_distinta"]

    return MENSAJES["sap_403_conflicto_puesto"]


def _resultado_sap_no_encontrado(operacion: Operacion) -> str:
    """404: precisa cual de los dos usuarios no existe."""
    falta_solicitante = operacion.usuario_solicitante is None
    falta_target = operacion.usuario_target is None

    if falta_solicitante and falta_target:
        return f"{MENSAJES['sap_404_solicitante']} {MENSAJES['sap_404_target']}"
    if falta_solicitante:
        return MENSAJES["sap_404_solicitante"]
    return MENSAJES["sap_404_target"]


#: Reglas de la accion "registro_sap", indexadas por codigo HTTP.
REGLAS_SAP: dict[int, Regla] = {
    200: _regla_fija("sap_200"),
    202: _regla_fija("sap_202"),
    208: _regla_fija("sap_208"),
    400: _resultado_sap_solicitud_invalida,
    401: _regla_fija("sap_401"),
    403: _resultado_sap_denegado,
    404: _resultado_sap_no_encontrado,
    500: _regla_fija("sap_500"),
    503: _regla_fija("sap_503"),
}


#: Tabla de reglas por accion. Una accion nueva registra aqui su propia tabla.
REGLAS_POR_ACCION: dict[str, dict[int, Regla]] = {
    "reseteo_usuario": REGLAS_RESETEO,
    "registro_sap": REGLAS_SAP,
}


def evaluar(operacion: Operacion) -> str:
    """Calcula el texto de la columna ``resultado final``.

    Un codigo desconocido nunca lanza excepcion: se reporta como no clasificado
    para que la operacion siga apareciendo en el reporte.
    """
    reglas = REGLAS_POR_ACCION.get(operacion.accion.clave, {})
    regla = reglas.get(operacion.status_code)
    if regla is None:
        return MENSAJES["no_clasificado"].format(status=operacion.status_code)
    return regla(operacion)
