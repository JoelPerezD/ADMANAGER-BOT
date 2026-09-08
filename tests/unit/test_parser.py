"""Pruebas del parseo de operaciones."""

from __future__ import annotations

from src.extract.log_reader import OperacionCruda
from src.transform.parser import (
    UsuarioAD,
    _calcular_duracion,
    _extraer_mensaje_admanager,
    _extraer_timestamp,
    _indexar_usuarios,
    _parsear_disparador,
    parsear,
)
from tests.conftest import (
    registro_adm_raw,
    registro_busqueda,
    registro_disparador,
    usuario_ad,
)

OP_ID = "abc123def456"


# --- Registro disparador ---------------------------------------------------


def test_disparador_extrae_usuarios_y_status(accion):
    registro = registro_disparador(OP_ID, "admsistemas520", "520000228", 200)

    assert _parsear_disparador(registro, accion) == ("admsistemas520", "520000228", 200)


def test_disparador_decodifica_nombres_con_espacios(accion):
    """En la query un espacio viaja como '+': 'Ana+laura' es 'Ana laura'.

    Sin decodificar, el usuario no cruza con su busqueda en ADManager y el
    reporte perderia su nombre y su oficina.
    """
    registro = registro_disparador(OP_ID, "gerencia613", "Ana laura", 404)

    assert "Ana+laura" in registro, "la query debe viajar codificada"
    assert _parsear_disparador(registro, accion) == ("gerencia613", "Ana laura", 404)


def test_disparador_ilegible_devuelve_none(accion):
    assert _parsear_disparador("linea sin formato de peticion", accion) is None


# --- Marcas de tiempo ------------------------------------------------------


def test_extraer_timestamp():
    registro = registro_disparador(OP_ID, "a", "b", 200, timestamp="2026-08-29T14:22:08.337641")

    assert _extraer_timestamp(registro) == "2026-08-29T14:22:08.337641"


def test_extraer_timestamp_de_linea_de_continuacion():
    """Las lineas de continuacion no llevan marca de tiempo."""
    assert _extraer_timestamp("Params to execute POST to SearchUser: {...}\n") == ""


def test_calcular_duracion():
    registros = [
        registro_disparador(OP_ID, "a", "b", 504, timestamp="2026-08-30T10:00:00.000000"),
        registro_disparador(OP_ID, "a", "b", 504, timestamp="2026-08-30T10:00:36.630000"),
    ]

    assert _calcular_duracion(registros) == 36.63


def test_calcular_duracion_con_un_solo_registro():
    """Sin dos marcas de tiempo no hay intervalo que medir."""
    registro = registro_disparador(OP_ID, "a", "b", 200)

    assert _calcular_duracion([registro]) == 0.0


# --- Busquedas en ADManager ------------------------------------------------


def test_indexar_usuarios_cruza_por_el_filtro_no_por_el_orden():
    """El orden de las busquedas varia entre operaciones."""
    registros = [
        registro_busqueda(OP_ID, "520000228", usuario_ad("520000228", oficina="0520")),
        registro_busqueda(OP_ID, "admsistemas520", usuario_ad("admsistemas520", oficina="0999")),
    ]

    usuarios = _indexar_usuarios(registros)

    assert usuarios["admsistemas520"].oficina == "0999"
    assert usuarios["520000228"].oficina == "0520"


def test_indexar_usuarios_marca_como_none_al_no_encontrado():
    """Un usuario inexistente llega como 'UsersList': [] con HTTP 200."""
    registros = [registro_busqueda(OP_ID, "SUPMERMAS", None)]

    assert _indexar_usuarios(registros)["supmermas"] is None


def test_indexar_usuarios_ignora_diferencias_de_mayusculas():
    """El log alterna 'AdmSistemas014' y 'admsistemas014' para el mismo usuario."""
    registros = [registro_busqueda(OP_ID, "AdmSistemas014", usuario_ad("AdmSistemas014"))]

    assert _indexar_usuarios(registros)["admsistemas014"] is not None


def test_indexar_usuarios_omite_respuesta_vacia():
    """ADManager puede responder 200 con el cuerpo vacio; no debe romper nada."""
    registro = (
        "2026-08-29T21:34:07.563835Z | INFO [operation_Id=x] | "
        "ADManagerRawClient.get_users_list_info_from_admanager invoked\n"
        "Params to execute POST to SearchUser: {'filter': '(sAMAccountName:equal:pepe)'}, "
        "Raw Response: , Raw status_code: 200, Raw reason_phrase: \n"
    )

    assert _indexar_usuarios([registro]) == {}


# --- Respuesta de ADManager al reseteo -------------------------------------


def test_extraer_mensaje_admanager():
    mensaje = "LOGON_NAME: nomina599@retailstore.com - No such user matched."
    registros = [registro_adm_raw(OP_ID, mensaje)]

    assert _extraer_mensaje_admanager(registros) == mensaje


def test_extraer_mensaje_admanager_sin_respuesta():
    """Un 403 o un 404 ni siquiera llegan a llamar a ADManager."""
    assert _extraer_mensaje_admanager([registro_disparador(OP_ID, "a", "b", 403)]) == ""


# --- Usuario de AD ---------------------------------------------------------


def test_nombre_completo_une_nombre_y_apellido():
    usuario = UsuarioAD.desde_admanager(usuario_ad("x", nombre="Ana", apellido="Lopez"))

    assert usuario.nombre_completo == "Ana Lopez"


def test_los_marcadores_de_campo_vacio_se_limpian():
    """ADManager usa '-' y '<not set>' para representar un campo sin valor."""
    usuario = UsuarioAD.desde_admanager(
        {"FIRST_NAME": "Ana", "LAST_NAME": "<not set>", "OFFICE": "-", "DESCRIPTION": ""}
    )

    assert usuario.nombre_completo == "Ana"
    assert usuario.oficina == ""


# --- Parseo completo -------------------------------------------------------


def test_parsear_operacion_completa(accion):
    registros = [
        registro_disparador(OP_ID, "admsistemas520", "520000228", 200),
        registro_busqueda(OP_ID, "admsistemas520", usuario_ad("admsistemas520", oficina="0520")),
        registro_busqueda(OP_ID, "520000228", usuario_ad("520000228", oficina="0520")),
    ]

    operacion = parsear(OperacionCruda(id=OP_ID, registros=registros), accion)

    assert operacion is not None
    assert operacion.id == OP_ID
    assert operacion.status_code == 200
    assert operacion.usuario_solicitante.oficina == "0520"
    assert operacion.usuario_target.oficina == "0520"


def test_parsear_devuelve_none_si_el_disparador_es_ilegible(accion, caplog):
    """Una operacion corrupta se descarta con aviso, sin tumbar la corrida."""
    cruda = OperacionCruda(id=OP_ID, registros=["2026-09-01T10:00:00.0Z | INFO | ruido\n"])

    assert parsear(cruda, accion) is None
    assert OP_ID in caplog.text
