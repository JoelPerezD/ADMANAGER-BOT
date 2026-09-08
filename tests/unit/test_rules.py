"""Pruebas de las reglas que traducen el codigo HTTP a un mensaje legible."""

from __future__ import annotations

import pytest

from src.config import ACCIONES
from src.transform.parser import Operacion, UsuarioAD
from src.transform.rules import evaluar

ACCION = ACCIONES["reseteo_usuario"]

# Perfiles reutilizados: un solicitante autorizado y un objetivo de su oficina.
GERENTE = UsuarioAD(
    sam_account_name="gerencia100",
    nombre="Ana",
    apellido="Lopez",
    oficina="0100",
    ou_name="OAT/Tiendas/BackOffice",
    descripcion="Gerente Tienda",
)
EMPLEADO = UsuarioAD(
    sam_account_name="100000001",
    nombre="Luis",
    apellido="Perez",
    oficina="0100",
    ou_name="Tienda/POS/Intelexion Tienda",
    descripcion="Cajero",
)


def construir_operacion(
    status: int,
    solicitante: UsuarioAD | None = GERENTE,
    target: UsuarioAD | None = EMPLEADO,
    mensaje_admanager: str = "",
    duracion: float = 1.0,
) -> Operacion:
    """Arma una operacion ya parseada para evaluar una regla concreta."""
    return Operacion(
        id="op-de-prueba",
        timestamp="2026-09-01T10:00:00.000000",
        solicitante=solicitante.sam_account_name if solicitante else "desconocido",
        target=target.sam_account_name if target else "desconocido",
        status_code=status,
        accion=ACCION,
        usuario_solicitante=solicitante,
        usuario_target=target,
        mensaje_admanager=mensaje_admanager,
        duracion_segundos=duracion,
    )


# --- 200 -------------------------------------------------------------------


def test_200_reporta_exito():
    assert evaluar(construir_operacion(200)) == "Reseteo ejecutado correctamente."


# --- 202 -------------------------------------------------------------------


def test_202_detecta_oficina_corporativa():
    target = UsuarioAD("x", "Luis", "Perez", "Corporativo", "OAT/Tiendas/BackOffice", "Cajero")

    resultado = evaluar(construir_operacion(202, target=target))

    assert resultado == "Solicitud aceptada: la oficina del usuario objetivo es corporativa."


def test_202_detecta_corporativo_con_acentos_y_mayusculas():
    """La marca se busca sobre el valor normalizado del campo OFFICE."""
    target = UsuarioAD("x", "Luis", "Perez", "OFICINA CORPORATIVO", "OU", "Cajero")

    assert "corporativa" in evaluar(construir_operacion(202, target=target))


def test_202_sin_marca_corporativa_usa_mensaje_generico():
    resultado = evaluar(construir_operacion(202))

    assert resultado == "Solicitud aceptada para procesamiento posterior."


# --- 403 -------------------------------------------------------------------


def test_403_por_solicitante_no_autorizado():
    solicitante = UsuarioAD("x", "Ana", "Lopez", "0100", "OAT/Tiendas/BackOffice", "Supervisor")

    resultado = evaluar(construir_operacion(403, solicitante=solicitante))

    assert resultado == "Acceso denegado: el solicitante no es gerente ni administrador."


def test_403_por_oficinas_distintas():
    target = UsuarioAD("x", "Luis", "Perez", "0999", "Tienda/POS/Intelexion Tienda", "Cajero")

    resultado = evaluar(construir_operacion(403, target=target))

    assert resultado == (
        "Acceso denegado: el solicitante y el usuario objetivo no pertenecen a la misma oficina."
    )


def test_403_por_ou_restringida():
    target = UsuarioAD("x", "Luis", "Perez", "0100", "OAT/Cedis/BY", "Cajero")

    resultado = evaluar(construir_operacion(403, target=target))

    assert resultado == (
        "Acceso denegado: el usuario objetivo pertenece a la OU restringida OAT/Cedis/BY."
    )


def test_403_ou_restringida_ignora_mayusculas():
    """El OU del log y el literal se comparan ambos normalizados."""
    target = UsuarioAD("x", "Luis", "Perez", "0100", "OAT/CEDIS/BY", "Cajero")

    assert "OU restringida" in evaluar(construir_operacion(403, target=target))


def test_403_concatena_todas_las_razones():
    """Cuando concurren varias causas, el reporte las enumera todas."""
    solicitante = UsuarioAD("x", "Ana", "Lopez", "0100", "OAT/Tiendas/BackOffice", "Supervisor")
    target = UsuarioAD("y", "Luis", "Perez", "0999", "OAT/Cedis/BY", "Cajero")

    resultado = evaluar(construir_operacion(403, solicitante=solicitante, target=target))

    assert resultado == (
        "Acceso denegado: el solicitante no es gerente ni administrador; "
        "el solicitante y el usuario objetivo no pertenecen a la misma oficina; "
        "el usuario objetivo pertenece a la OU restringida OAT/Cedis/BY."
    )


def test_403_sin_datos_reporta_causa_no_identificable():
    """Sin los usuarios en AD no se puede atribuir ninguna razon concreta."""
    resultado = evaluar(construir_operacion(403, solicitante=None, target=None))

    assert "sin una causa identificable" in resultado


def test_403_con_oficina_vacia_no_asume_que_coinciden():
    """Dos oficinas vacias no son 'la misma oficina': ante la duda, se niega."""
    solicitante = UsuarioAD("x", "Ana", "Lopez", "", "OAT/Tiendas/BackOffice", "Gerente Tienda")
    target = UsuarioAD("y", "Luis", "Perez", "", "Tienda/POS/Intelexion Tienda", "Cajero")

    resultado = evaluar(construir_operacion(403, solicitante=solicitante, target=target))

    assert "no pertenecen a la misma oficina" in resultado


# --- 404 -------------------------------------------------------------------


def test_404_target_no_encontrado():
    resultado = evaluar(construir_operacion(404, target=None))

    assert resultado == "No se encontró al usuario objetivo en ADManager."


def test_404_solicitante_no_encontrado():
    resultado = evaluar(construir_operacion(404, solicitante=None))

    assert resultado == "No se encontró al usuario solicitante en ADManager."


def test_404_ninguno_encontrado():
    resultado = evaluar(construir_operacion(404, solicitante=None, target=None))

    assert resultado == (
        "No se encontró al usuario solicitante ni al usuario objetivo en ADManager."
    )


# --- Resto de codigos ------------------------------------------------------


def test_429_reporta_tokens_agotados():
    assert evaluar(construir_operacion(429)) == (
        "No se pudo completar: se agotaron los tokens de ADManager."
    )


def test_500_reporta_error_interno():
    assert evaluar(construir_operacion(500)) == (
        "Error interno inesperado del bot durante el procesamiento."
    )


def test_503_concatena_el_error_de_admanager():
    mensaje = "LOGON_NAME: nomina599@retailstore.com - No such user matched."

    resultado = evaluar(construir_operacion(503, mensaje_admanager=mensaje))

    assert resultado == f"Servicio no disponible. Error reportado por ADManager: {mensaje}"


def test_503_sin_detalle_del_error():
    resultado = evaluar(construir_operacion(503))

    assert resultado == "Servicio no disponible. ADManager no devolvió un detalle del error."


def test_504_reporta_el_timeout_con_su_duracion():
    resultado = evaluar(construir_operacion(504, duracion=39.64))

    assert resultado == (
        "Tiempo de espera agotado: la comunicación superó los 35 segundos "
        "(duración: 39.64 s). Se da por hecho que el reseteo no se pudo ejecutar."
    )


def test_504_da_por_hecho_que_el_reseteo_fallo():
    """Regla de negocio: el reporte nunca sugiere que el reseteo pudo aplicarse."""
    resultado = evaluar(construir_operacion(504, duracion=36.63))

    assert "no se pudo ejecutar" in resultado
    assert "pudo haberse aplicado" not in resultado


@pytest.mark.parametrize("status", [201, 418, 502])
def test_codigo_desconocido_no_lanza_excepcion(status):
    """Un codigo nuevo se reporta como no clasificado, sin perder la fila."""
    assert evaluar(construir_operacion(status)) == (
        f"Resultado no clasificado (código HTTP {status})."
    )
