"""Pruebas end-to-end: se ejecuta la CLI completa sobre logs de ejemplo."""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import pytest

from src.config import CODIFICACION_REPORTE
from src.main import ERROR, EXITO, SIN_ARCHIVO, main

RAIZ = Path(__file__).resolve().parents[2]

#: Operaciones que contiene cada log de ejemplo.
OPERACIONES_29 = 6
OPERACIONES_30 = 2


@pytest.fixture
def reporte(tmp_path: Path) -> Path:
    return tmp_path / "tabla_reporte_bot.csv"


def ejecutar(dir_fixtures: Path, reporte: Path, *extra: str) -> int:
    """Lanza la CLI con las rutas de la prueba."""
    return main(
        [
            "--fecha",
            "2026-08-29",
            "--input-dir",
            str(dir_fixtures),
            "--output",
            str(reporte),
            *extra,
        ]
    )


def leer(reporte: Path) -> list[dict[str, str]]:
    with reporte.open(newline="", encoding=CODIFICACION_REPORTE) as archivo:
        return list(csv.DictReader(archivo))


def test_primera_corrida_genera_el_reporte(dir_fixtures, reporte):
    assert ejecutar(dir_fixtures, reporte) == EXITO

    filas = leer(reporte)
    assert len(filas) == OPERACIONES_29
    assert all(fila["sistema"] == "ADManager" for fila in filas)
    assert all(fila["acción"] == "Reseteo de usuario" for fila in filas)


def test_los_identificadores_son_unicos(dir_fixtures, reporte):
    ejecutar(dir_fixtures, reporte)

    filas = leer(reporte)
    assert len({fila["id"] for fila in filas}) == len(filas)


def test_todas_las_filas_traen_resultado_legible(dir_fixtures, reporte):
    """El reporte nunca guarda codigos HTTP numericos."""
    ejecutar(dir_fixtures, reporte)

    for fila in leer(reporte):
        resultado = fila["resultado final"]
        assert resultado, "ninguna fila puede quedarse sin resultado"
        assert not resultado.strip().isdigit()


def test_reejecutar_la_misma_fecha_no_duplica_ni_altera(dir_fixtures, reporte):
    """Este es el requisito central: la corrida debe ser idempotente."""
    ejecutar(dir_fixtures, reporte)
    contenido = reporte.read_bytes()

    assert ejecutar(dir_fixtures, reporte) == EXITO

    assert reporte.read_bytes() == contenido
    assert len(leer(reporte)) == OPERACIONES_29


def test_procesar_otra_fecha_solo_anexa(dir_fixtures, reporte):
    ejecutar(dir_fixtures, reporte)
    contenido_previo = reporte.read_bytes()

    codigo = main(
        [
            "--fecha",
            "2026-08-30",
            "--input-dir",
            str(dir_fixtures),
            "--output",
            str(reporte),
        ]
    )

    assert codigo == EXITO
    assert reporte.read_bytes().startswith(contenido_previo)
    assert len(leer(reporte)) == OPERACIONES_29 + OPERACIONES_30


def test_rango_de_fechas(dir_fixtures, reporte):
    codigo = ejecutar(dir_fixtures, reporte, "--hasta", "2026-08-30")

    assert codigo == EXITO
    assert len(leer(reporte)) == OPERACIONES_29 + OPERACIONES_30


def test_rango_reprocesado_no_duplica(dir_fixtures, reporte):
    """Reprocesar un rango que ya incluye fechas cargadas es seguro."""
    ejecutar(dir_fixtures, reporte)

    ejecutar(dir_fixtures, reporte, "--hasta", "2026-08-30")

    assert len(leer(reporte)) == OPERACIONES_29 + OPERACIONES_30


def test_dry_run_no_crea_el_reporte(dir_fixtures, reporte, capsys):
    assert ejecutar(dir_fixtures, reporte, "--dry-run") == EXITO

    assert not reporte.exists()
    assert "dry-run" in capsys.readouterr().out


def test_resumen_por_consola(dir_fixtures, reporte, capsys):
    ejecutar(dir_fixtures, reporte)

    salida = capsys.readouterr().out
    assert "Operaciones leidas del log : 6" in salida
    assert "Filas nuevas en el reporte : 6" in salida
    assert "HTTP 503  Servicio no disponible" in salida


def test_log_inexistente_devuelve_codigo_dedicado(dir_fixtures, reporte):
    codigo = main(
        [
            "--fecha",
            "1999-01-01",
            "--input-dir",
            str(dir_fixtures),
            "--output",
            str(reporte),
        ]
    )

    assert codigo == SIN_ARCHIVO
    assert not reporte.exists()


def test_rango_invertido_es_un_error(dir_fixtures, reporte):
    codigo = ejecutar(dir_fixtures, reporte, "--hasta", "2026-08-01")

    assert codigo == ERROR


def test_fecha_invalida_la_rechaza_argparse(dir_fixtures, reporte):
    with pytest.raises(SystemExit):
        ejecutar(dir_fixtures, reporte.with_name("otro.csv"), "--fecha", "29-08-2026")


def test_ejecucion_como_modulo(dir_fixtures, reporte):
    """El pipeline debe correr tal cual se documenta en el README."""
    proceso = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.main",
            "--fecha",
            "2026-08-29",
            "--input-dir",
            str(dir_fixtures),
            "--output",
            str(reporte),
        ],
        cwd=RAIZ,
        capture_output=True,
        text=True,
    )

    assert proceso.returncode == EXITO, proceso.stderr
    assert len(leer(reporte)) == OPERACIONES_29
