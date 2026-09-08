"""Pruebas de la escritura idempotente del reporte."""

from __future__ import annotations

import codecs
import csv
from pathlib import Path

import pytest

from src.config import CODIFICACION_REPORTE, COLUMNAS
from src.load.csv_writer import escribir, leer_ids_existentes


def fila(identificador: str, resultado: str = "Reseteo ejecutado correctamente.") -> dict[str, str]:
    """Fila minima con todas las columnas del reporte."""
    return {
        "id": identificador,
        "timestamp": "2026-09-01T10:00:00.000000",
        "solicitante": "admsistemas100",
        "target": "100000001",
        "acción": "Reseteo de usuario",
        "sistema": "ADManager",
        "nombre completo del usuario solicitante": "Ana Lopez",
        "nombre completo del usuario target": "Luis Perez",
        "oficina del usuario solicitante": "0100",
        "oficina del usuario target": "0100",
        "resultado final": resultado,
        "updated_at": "2026-09-08T12:00:00+00:00",
    }


@pytest.fixture
def reporte(tmp_path: Path) -> Path:
    return tmp_path / "salida" / "tabla_reporte_bot.csv"


def leer(reporte: Path) -> list[dict[str, str]]:
    with reporte.open(newline="", encoding=CODIFICACION_REPORTE) as archivo:
        return list(csv.DictReader(archivo))


def test_crea_el_archivo_con_cabecera(reporte):
    resultado = escribir([fila("a"), fila("b")], reporte)

    assert resultado.nuevas == 2
    assert resultado.omitidas == 0
    assert [f["id"] for f in leer(reporte)] == ["a", "b"]


def test_crea_los_directorios_que_falten(reporte):
    """La carpeta de salida puede no existir en la primera corrida."""
    assert not reporte.parent.exists()

    escribir([fila("a")], reporte)

    assert reporte.exists()


def test_escribe_las_columnas_en_orden(reporte):
    escribir([fila("a")], reporte)

    with reporte.open(newline="", encoding=CODIFICACION_REPORTE) as archivo:
        assert tuple(next(csv.reader(archivo))) == COLUMNAS


def test_incluye_bom_para_excel(reporte):
    """Sin BOM, Excel abre los acentos de las cabeceras como caracteres raros."""
    escribir([fila("a")], reporte)

    assert reporte.read_bytes().startswith(codecs.BOM_UTF8)


def test_no_duplica_identificadores_ya_cargados(reporte):
    escribir([fila("a"), fila("b")], reporte)

    resultado = escribir([fila("a"), fila("b"), fila("c")], reporte)

    assert resultado.nuevas == 1
    assert resultado.omitidas == 2
    assert [f["id"] for f in leer(reporte)] == ["a", "b", "c"]


def test_no_altera_las_filas_existentes(reporte):
    """Reprocesar una fecha nunca debe modificar lo ya cargado."""
    escribir([fila("a"), fila("b")], reporte)
    contenido_previo = reporte.read_bytes()

    escribir([fila("c")], reporte)

    assert reporte.read_bytes().startswith(contenido_previo)


def test_reejecucion_identica_deja_el_archivo_intacto(reporte):
    escribir([fila("a"), fila("b")], reporte)
    antes = reporte.read_bytes()

    resultado = escribir([fila("a"), fila("b")], reporte)

    assert resultado.nuevas == 0
    assert reporte.read_bytes() == antes


def test_descarta_duplicados_dentro_del_mismo_lote(reporte):
    resultado = escribir([fila("a"), fila("a")], reporte)

    assert resultado.nuevas == 1
    assert resultado.omitidas == 1


def test_dry_run_no_escribe_nada(reporte):
    resultado = escribir([fila("a")], reporte, dry_run=True)

    assert resultado.nuevas == 1
    assert not reporte.exists()


def test_no_deja_archivos_temporales(reporte):
    escribir([fila("a")], reporte)
    escribir([fila("b")], reporte)

    assert list(reporte.parent.glob("*.tmp")) == []


def test_leer_ids_de_un_reporte_inexistente(reporte):
    """La primera corrida no necesita ningun paso de inicializacion."""
    assert leer_ids_existentes(reporte) == set()


def test_leer_ids_existentes(reporte):
    escribir([fila("a"), fila("b")], reporte)

    assert leer_ids_existentes(reporte) == {"a", "b"}


def test_conserva_los_ceros_a_la_izquierda_de_las_oficinas(reporte):
    """La oficina es un codigo de texto: '0100' no debe volverse '100'."""
    escribir([fila("a")], reporte)

    assert leer(reporte)[0]["oficina del usuario solicitante"] == "0100"


def test_escapa_los_mensajes_con_comas(reporte):
    """Los errores de ADManager traen comas y puntos que romperian el CSV."""
    mensaje = "Servicio no disponible. Error: No such user matched, verify the LDAP attribute."

    escribir([fila("a", resultado=mensaje)], reporte)

    assert leer(reporte)[0]["resultado final"] == mensaje
