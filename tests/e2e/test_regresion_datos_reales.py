"""Regresion contra los logs reales, si estan disponibles.

Los conteos que se afirman aqui se obtuvieron analizando los logs de produccion y
son la mejor red de seguridad del proyecto: cualquier cambio en las reglas que
altere la clasificacion hara fallar estas pruebas.

Como ``data/input/`` no se versiona, las pruebas se omiten cuando los logs no
estan presentes (por ejemplo en una copia recien clonada del repositorio).
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import pytest

from src.config import CODIFICACION_REPORTE, DIR_ENTRADA
from src.main import EXITO, main

#: Fechas cubiertas por los logs de produccion analizados.
PRIMERA_FECHA = "2026-08-29"
ULTIMA_FECHA = "2026-09-01"

#: Operaciones de reseteo por codigo de respuesta, verificadas sobre los 4 logs.
CONTEOS_ESPERADOS = {
    "Reseteo ejecutado correctamente.": 1108,
    "No se encontró al usuario objetivo en ADManager.": 79,
    "Error interno inesperado del bot durante el procesamiento.": 1,
}

#: Total de operaciones de reseteo en los cuatro dias.
TOTAL_OPERACIONES = 1238

FECHAS_REALES = ("2026-08-29", "2026-08-30", "2026-08-31", "2026-09-01")
LOGS_REALES = [DIR_ENTRADA / f"{fecha}.log" for fecha in FECHAS_REALES]

pytestmark = pytest.mark.skipif(
    not all(ruta.exists() for ruta in LOGS_REALES),
    reason="Los logs reales no estan en data/input/ (no se versionan).",
)


@pytest.fixture(scope="module")
def filas_reales(tmp_path_factory) -> list[dict[str, str]]:
    """Procesa los cuatro logs reales una sola vez para todo el modulo."""
    reporte = tmp_path_factory.mktemp("real") / "tabla_reporte_bot.csv"
    codigo = main(["--fecha", PRIMERA_FECHA, "--hasta", ULTIMA_FECHA, "--output", str(reporte)])
    assert codigo == EXITO

    with reporte.open(newline="", encoding=CODIFICACION_REPORTE) as archivo:
        return list(csv.DictReader(archivo))


def test_total_de_operaciones(filas_reales):
    assert len(filas_reales) == TOTAL_OPERACIONES


def test_los_operation_id_son_unicos(filas_reales):
    """`operation_Id` es la clave del reporte: si se repitiera, la idempotencia
    descartaria operaciones distintas por creerlas duplicadas."""
    assert len({fila["id"] for fila in filas_reales}) == TOTAL_OPERACIONES


@pytest.mark.parametrize(("resultado", "esperado"), CONTEOS_ESPERADOS.items())
def test_conteo_por_resultado(filas_reales, resultado, esperado):
    conteo = Counter(fila["resultado final"] for fila in filas_reales)

    assert conteo[resultado] == esperado


def test_conteo_de_rechazos(filas_reales):
    """Los 41 rechazos se reparten entre las dos causas observadas."""
    por_oficina = (
        "Acceso denegado: el solicitante y el usuario objetivo no pertenecen a la misma oficina."
    )
    por_perfil = "Acceso denegado: el solicitante no es gerente ni administrador."

    rechazos = [f for f in filas_reales if f["resultado final"].startswith("Acceso denegado")]
    por_causa = Counter(f["resultado final"] for f in rechazos)

    assert len(rechazos) == 41
    assert por_causa[por_oficina] == 28
    assert por_causa[por_perfil] == 13


def test_conteo_de_timeouts(filas_reales):
    timeouts = [f for f in filas_reales if f["resultado final"].startswith("Tiempo de espera")]

    assert len(timeouts) == 6
    for fila in timeouts:
        assert "Se da por hecho que el reseteo no se pudo ejecutar." in fila["resultado final"]


def test_conteo_de_servicio_no_disponible(filas_reales):
    """Los tres 503 incluyen el error exacto que devolvio ADManager."""
    caidas = [f for f in filas_reales if f["resultado final"].startswith("Servicio no disponible")]

    assert len(caidas) == 3
    for fila in caidas:
        assert "No such user matched" in fila["resultado final"]


def test_ninguna_fila_guarda_un_codigo_numerico(filas_reales):
    for fila in filas_reales:
        assert not fila["resultado final"].strip().isdigit()


def test_ninguna_operacion_queda_sin_clasificar(filas_reales):
    sin_clasificar = [f for f in filas_reales if "no clasificado" in f["resultado final"]]

    assert sin_clasificar == []


def test_las_operaciones_exitosas_traen_datos_completos(filas_reales):
    """Un 200 siempre resolvio ambos usuarios en ADManager."""
    exitosas = [f for f in filas_reales if f["resultado final"].startswith("Reseteo ejecutado")]

    for fila in exitosas:
        assert fila["nombre completo del usuario solicitante"]
        assert fila["nombre completo del usuario target"]
        assert fila["oficina del usuario solicitante"]
        assert fila["oficina del usuario target"]


def test_las_oficinas_conservan_su_formato_original(filas_reales):
    """Las oficinas son codigos de texto como '0520', no numeros."""
    oficinas = {f["oficina del usuario solicitante"] for f in filas_reales}

    assert any(oficina.startswith("0") and len(oficina) == 4 for oficina in oficinas)


def test_el_reporte_se_puede_reprocesar_sin_duplicar(tmp_path: Path):
    """Reprocesar los cuatro dias sobre un reporte ya cargado no cambia nada."""
    reporte = tmp_path / "tabla_reporte_bot.csv"
    main(["--fecha", PRIMERA_FECHA, "--hasta", ULTIMA_FECHA, "--output", str(reporte)])
    contenido = reporte.read_bytes()

    main(["--fecha", PRIMERA_FECHA, "--hasta", ULTIMA_FECHA, "--output", str(reporte)])

    assert reporte.read_bytes() == contenido
