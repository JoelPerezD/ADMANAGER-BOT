"""Integracion entre el lector de logs y el parser.

Se apoya en logs de ejemplo recortados de datos reales, con el formato completo
del bot: registros multilinea y operaciones intercaladas.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.extract.log_reader import iter_operaciones, iter_registros, ruta_log
from src.transform.parser import parsear
from src.transform.rules import evaluar

FIXTURE_29 = "2026-08-29.log"
FIXTURE_30 = "2026-08-30.log"


@pytest.fixture
def operaciones_29(dir_fixtures, accion):
    """Las seis operaciones del log de ejemplo del 2026-08-29, ya parseadas."""
    ruta = dir_fixtures / FIXTURE_29
    parseadas = [parsear(cruda, accion) for cruda in iter_operaciones(ruta, accion)]
    return {operacion.id: operacion for operacion in parseadas if operacion}


def test_ruta_log_usa_la_fecha_como_nombre(dir_fixtures):
    assert ruta_log(date(2026, 8, 29), dir_fixtures).name == FIXTURE_29


def test_los_registros_multilinea_se_mantienen_unidos(dir_fixtures):
    """El volcado 'Raw Response:' continua en lineas sin operation_Id.

    Si el lector partiera por lineas, ese JSON quedaria huerfano y se perderian
    la oficina y el nombre de todos los usuarios.
    """
    registros = list(iter_registros(dir_fixtures / FIXTURE_29))

    multilinea = [r for r in registros if "Raw Response:" in r]
    assert multilinea, "el log de ejemplo debe contener volcados de ADManager"
    for registro in multilinea:
        assert "\n" in registro.rstrip("\n"), "el registro debe abarcar varias lineas"
        assert registro.startswith("2026-"), "todo registro empieza con su marca de tiempo"


def test_las_operaciones_intercaladas_se_reagrupan(dir_fixtures, accion):
    """El bot atiende peticiones en paralelo, asi que los registros se mezclan."""
    operaciones = list(iter_operaciones(dir_fixtures / FIXTURE_29, accion))

    assert len(operaciones) == 6
    for operacion in operaciones:
        identificadores = {r.split("operation_Id=")[1].split("]")[0] for r in operacion.registros}
        assert identificadores == {operacion.id}


def test_cada_operacion_arranca_con_su_disparador(dir_fixtures, accion):
    for operacion in iter_operaciones(dir_fixtures / FIXTURE_29, accion):
        assert accion.endpoint in operacion.disparador


def test_reseteo_exitoso(operaciones_29):
    operacion = operaciones_29["b192579b98e2f5c469a96eb7e19241cf"]

    assert operacion.status_code == 200
    assert operacion.solicitante == "admsistemas970"
    assert operacion.usuario_solicitante.oficina == "0970"
    assert operacion.usuario_target.oficina == "0970"
    assert evaluar(operacion) == "Reseteo ejecutado correctamente."


def test_rechazo_por_oficinas_distintas(operaciones_29):
    operacion = operaciones_29["895db57ed39c8499d426c89d9f924394"]

    assert operacion.status_code == 403
    assert operacion.usuario_solicitante.oficina != operacion.usuario_target.oficina
    assert "no pertenecen a la misma oficina" in evaluar(operacion)


def test_rechazo_por_solicitante_no_autorizado(operaciones_29):
    operacion = operaciones_29["d32c59a919d9fdb94a540707db1a6e3b"]

    assert operacion.status_code == 403
    assert operacion.usuario_solicitante.descripcion == "Capital Humano"
    assert "no es gerente ni administrador" in evaluar(operacion)


def test_target_inexistente(operaciones_29):
    operacion = operaciones_29["21c515e3be1d2adcff57ce6957104d0c"]

    assert operacion.status_code == 404
    assert operacion.usuario_solicitante is not None
    assert operacion.usuario_target is None
    assert evaluar(operacion) == "No se encontró al usuario objetivo en ADManager."


def test_error_interno_con_respuesta_vacia_de_admanager(operaciones_29):
    """ADManager devolvio un cuerpo vacio; el bot termino en 500."""
    operacion = operaciones_29["610113353adb8a0c1c67a3d3b5c41989"]

    assert operacion.status_code == 500
    assert operacion.usuario_solicitante is None
    assert evaluar(operacion) == "Error interno inesperado del bot durante el procesamiento."


def test_servicio_no_disponible_concatena_el_error_de_admanager(operaciones_29):
    operacion = operaciones_29["c6f5a3a95ed29e480cd335c3b0930812"]

    assert operacion.status_code == 503
    assert evaluar(operacion) == (
        "Servicio no disponible. Error reportado por ADManager: "
        "LOGON_NAME: sgsupmercado507@retailstore.com - No such user matched. "
        "Verify the LDAP attribute in search query or could be a privilege issue."
    )


def test_timeout_mide_la_duracion_real(dir_fixtures, accion):
    ruta = dir_fixtures / FIXTURE_30
    operaciones = {
        operacion.id: operacion
        for cruda in iter_operaciones(ruta, accion)
        if (operacion := parsear(cruda, accion))
    }

    operacion = operaciones["e0db310cd2b9f65d7322fb3f585b8caa"]

    assert operacion.status_code == 504
    assert operacion.duracion_segundos > 35
    assert "no se pudo ejecutar" in evaluar(operacion)


def test_target_con_espacios_cruza_con_su_busqueda(dir_fixtures, accion):
    """'Ana+laura' en la URL es 'Ana laura' en el filtro de ADManager."""
    ruta = dir_fixtures / FIXTURE_30
    operaciones = {
        operacion.id: operacion
        for cruda in iter_operaciones(ruta, accion)
        if (operacion := parsear(cruda, accion))
    }

    operacion = operaciones["e41b991d0c4a4b7643c6da6fbe05957d"]

    assert operacion.target == "Ana laura"
    assert operacion.usuario_solicitante is not None, "el solicitante si existe en AD"
    assert operacion.usuario_target is None, "el objetivo no existe en AD"
    assert evaluar(operacion) == "No se encontró al usuario objetivo en ADManager."


def test_solo_se_extraen_las_operaciones_de_la_accion_pedida(dir_fixtures, accion):
    """El log real trae otros endpoints que no deben colarse al reporte."""
    for operacion in iter_operaciones(dir_fixtures / FIXTURE_29, accion):
        assert "users_admin/resetuser" in operacion.disparador
