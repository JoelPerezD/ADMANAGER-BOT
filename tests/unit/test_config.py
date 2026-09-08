"""Pruebas de las constantes de configuracion.

Estas pruebas blindan la simetria de las comparaciones: los literales de negocio
deben estar normalizados en origen, para que nunca se compare un dato del log en
minusculas contra un literal en mayusculas.
"""

from __future__ import annotations

from src.config import (
    ACCIONES,
    COLUMNAS,
    MARCA_CORPORATIVA,
    OU_RESTRINGIDA,
    PREFIJOS_AUTORIZADOS,
)
from src.utils.texto import normalizar


def test_ou_restringida_esta_normalizada():
    """El literal contra el que se compara vive ya en minusculas y sin acentos."""
    assert OU_RESTRINGIDA == "oat/cedis/by"


def test_prefijos_autorizados_estan_normalizados():
    assert PREFIJOS_AUTORIZADOS == ("gerente", "admin")


def test_marca_corporativa_esta_normalizada():
    assert MARCA_CORPORATIVA == "corporativo"


def test_los_literales_son_estables_al_renormalizar():
    """Volver a normalizar un literal no lo cambia: ya estaba normalizado."""
    for literal in (OU_RESTRINGIDA, MARCA_CORPORATIVA, *PREFIJOS_AUTORIZADOS):
        assert normalizar(literal) == literal


def test_columnas_del_reporte():
    """El esquema del CSV es un contrato con quien consume el reporte."""
    assert COLUMNAS == (
        "id",
        "timestamp",
        "solicitante",
        "target",
        "acción",
        "sistema",
        "nombre completo del usuario solicitante",
        "nombre completo del usuario target",
        "oficina del usuario solicitante",
        "oficina del usuario target",
        "resultado final",
        "updated_at",
    )


def test_accion_de_reseteo_registrada():
    """La accion de reseteo apunta al endpoint correcto del bot."""
    accion = ACCIONES["reseteo_usuario"]
    assert accion.endpoint == "users_admin/resetuser"
    assert accion.sistema == "ADManager"
    assert accion.parametro_solicitante == "sAMAccountName_requester"
    assert accion.parametro_target == "sAMAccountName_target"
