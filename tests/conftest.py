"""Fixtures y constructores compartidos por la suite de pruebas."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote_plus

import pytest

from src.config import ACCIONES

#: Carpeta con los logs de ejemplo recortados de datos reales.
DIR_FIXTURES = Path(__file__).parent / "fixtures" / "logs"

#: Marca de tiempo base para los logs sinteticos.
TIMESTAMP_BASE = "2026-09-01T10:00:00.000000"


@pytest.fixture
def accion():
    """Accion de reseteo, que es la unica registrada por ahora."""
    return ACCIONES["reseteo_usuario"]


@pytest.fixture
def dir_fixtures() -> Path:
    """Carpeta con los logs de ejemplo."""
    return DIR_FIXTURES


# --- Constructores de log sintetico ---------------------------------------


def usuario_ad(
    sam: str,
    nombre: str = "Nombre",
    apellido: str = "Apellido",
    oficina: str = "0100",
    ou_name: str = "OAT/Tiendas/BackOffice",
    descripcion: str = "Administrador De Sistemas",
) -> dict[str, str]:
    """Construye un usuario con la forma que devuelve ADManager."""
    return {
        "SAM_ACCOUNT_NAME": sam,
        "FIRST_NAME": nombre,
        "LAST_NAME": apellido,
        "OFFICE": oficina,
        "OU_NAME": ou_name,
        "DESCRIPTION": descripcion,
    }


def registro_disparador(
    op_id: str,
    solicitante: str,
    target: str,
    status: int,
    timestamp: str = TIMESTAMP_BASE,
) -> str:
    """Genera la llamada al endpoint del bot, con la query URL-encoded."""
    return (
        f"{timestamp}Z | INFO [operation_Id={op_id}] | HTTP Request: "
        f"http://apitools.com:8000/v3/users_admin/resetuser"
        f"?sAMAccountName_requester={quote_plus(solicitante)}"
        f"&sAMAccountName_target={quote_plus(target)}"
        f' "HTTP/1.1" {status}\n'
    )


def registro_busqueda(
    op_id: str,
    consultado: str,
    datos: dict[str, str] | None,
    timestamp: str = TIMESTAMP_BASE,
) -> str:
    """Genera una busqueda en ADManager como registro multilinea.

    Args:
        consultado: ``sAMAccountName`` que aparece en el ``filter``.
        datos: Usuario devuelto, o ``None`` para simular que no existe.
    """
    lista = [datos] if datos else []
    cuerpo = json.dumps(
        {"UsersList": lista, "count": len(lista), "statusMessage": "", "status": "SUCCESS"}
    )
    return (
        f"{timestamp}Z | INFO [operation_Id={op_id}] | "
        f"ADManagerRawClient.get_users_list_info_from_admanager invoked\n"
        f"Params to execute POST to SearchUser: {{'domainName': 'retailstore.com', "
        f"'range': 2, 'startIndex': 1, "
        f"'filter': '(sAMAccountName:equal:{consultado})'}}, Raw Response: {cuerpo}\n"
        f"\n, Raw status_code: 200, Raw reason_phrase: \n"
    )


def registro_adm_raw(
    op_id: str,
    status_message: str,
    status: str = "0",
    timestamp: str = TIMESTAMP_BASE,
) -> str:
    """Genera la respuesta de ADManager al intento de reseteo."""
    cuerpo = f"[{{'statusMessage': '{status_message}', 'status': '{status}'}}]"
    return (
        f"{timestamp}Z | INFO [operation_Id={op_id}] | "
        f"ADM-Raw response | status: 200 | body: {cuerpo}\n"
    )


def construir_log(*operaciones: list[str]) -> str:
    """Une varias operaciones en el texto de un archivo .log."""
    return "".join("".join(registros) for registros in operaciones)


def operacion_simple(
    op_id: str,
    status: int,
    solicitante: str = "admsistemas100",
    target: str = "100000001",
    datos_solicitante: dict[str, str] | None = None,
    datos_target: dict[str, str] | None = None,
) -> list[str]:
    """Arma una operacion completa: disparador y las dos busquedas en AD."""
    if datos_solicitante is None:
        datos_solicitante = usuario_ad(solicitante)
    if datos_target is None:
        datos_target = usuario_ad(target, descripcion="Cajero")

    return [
        registro_disparador(op_id, solicitante, target, status),
        registro_busqueda(op_id, solicitante, datos_solicitante),
        registro_busqueda(op_id, target, datos_target),
    ]


@pytest.fixture
def escribir_log(tmp_path: Path):
    """Devuelve una funcion que guarda texto de log en un archivo temporal."""

    def _escribir(nombre: str, contenido: str) -> Path:
        destino = tmp_path / "input"
        destino.mkdir(exist_ok=True)
        ruta = destino / nombre
        ruta.write_text(contenido, encoding="utf-8")
        return ruta

    return _escribir
