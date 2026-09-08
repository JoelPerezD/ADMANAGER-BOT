"""Punto de entrada del pipeline.

Orquesta las tres capas -extraccion, transformacion y carga- y presenta un
resumen por consola.

Ejemplos de uso:
    python -m src.main --fecha 2026-08-29
    python -m src.main --fecha 2026-08-29 --hasta 2026-09-01
    python -m src.main --fecha 2026-08-29 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from src.config import (
    ACCION_POR_DEFECTO,
    ACCIONES,
    ARCHIVO_REPORTE,
    DIR_ENTRADA,
    ETIQUETAS_STATUS,
    Accion,
)
from src.extract import log_reader
from src.load import csv_writer
from src.transform import parser as operacion_parser
from src.transform import rules

logger = logging.getLogger("reporte_bot")

# Codigos de salida del proceso.
EXITO = 0
ERROR = 1
SIN_ARCHIVO = 2


def parsear_fecha(texto: str) -> date:
    """Valida una fecha en formato ``YYYY-MM-DD`` para argparse."""
    try:
        return date.fromisoformat(texto)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"'{texto}' no es una fecha valida; se espera el formato YYYY-MM-DD."
        ) from error


def construir_argumentos() -> argparse.ArgumentParser:
    """Define la interfaz de linea de comandos."""
    analizador = argparse.ArgumentParser(
        prog="python -m src.main",
        description="Procesa los logs diarios del bot y actualiza la tabla de reporte.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  python -m src.main --fecha 2026-08-29\n"
            "  python -m src.main --fecha 2026-08-29 --hasta 2026-09-01\n"
            "  python -m src.main --fecha 2026-08-29 --dry-run\n"
        ),
    )
    analizador.add_argument(
        "--fecha",
        required=True,
        type=parsear_fecha,
        help="Fecha del log a procesar (YYYY-MM-DD).",
    )
    analizador.add_argument(
        "--hasta",
        type=parsear_fecha,
        help="Fecha final si se quiere procesar un rango; se incluye en el proceso.",
    )
    analizador.add_argument(
        "--accion",
        default=ACCION_POR_DEFECTO,
        choices=sorted(ACCIONES),
        help="Tipo de operacion a extraer del log.",
    )
    analizador.add_argument(
        "--input-dir",
        type=Path,
        default=DIR_ENTRADA,
        help="Carpeta donde viven los archivos .log.",
    )
    analizador.add_argument(
        "--output",
        type=Path,
        default=ARCHIVO_REPORTE,
        help="Ruta del CSV de reporte.",
    )
    analizador.add_argument(
        "--dry-run",
        action="store_true",
        help="Procesa y muestra el resumen, pero no escribe el reporte.",
    )
    analizador.add_argument(
        "--verbose",
        action="store_true",
        help="Muestra el detalle de cada operacion procesada.",
    )
    return analizador


def rango_de_fechas(desde: date, hasta: date | None) -> list[date]:
    """Devuelve las fechas a procesar, ambas inclusive."""
    fin = hasta or desde
    if fin < desde:
        raise ValueError("La fecha final no puede ser anterior a la inicial.")
    return [desde + timedelta(days=dias) for dias in range((fin - desde).days + 1)]


def procesar_fecha(
    fecha: date,
    accion: Accion,
    dir_entrada: Path,
    momento: datetime,
) -> tuple[list[dict[str, str]], Counter, int]:
    """Convierte el log de una fecha en filas del reporte.

    Args:
        fecha: Dia a procesar.
        accion: Tipo de operacion a extraer.
        dir_entrada: Carpeta que contiene los archivos .log.
        momento: Instante de la corrida, para la columna ``updated_at``.

    Returns:
        Las filas listas para cargar, un conteo por codigo de respuesta y el
        numero de operaciones que no se pudieron parsear.

    Raises:
        FileNotFoundError: Si no existe el log de esa fecha.
    """
    ruta = log_reader.ruta_log(fecha, dir_entrada)
    if not ruta.exists():
        raise FileNotFoundError(ruta)

    filas: list[dict[str, str]] = []
    resumen: Counter = Counter()
    descartadas = 0

    for cruda in log_reader.iter_operaciones(ruta, accion):
        operacion = operacion_parser.parsear(cruda, accion)
        if operacion is None:
            descartadas += 1
            continue

        resultado = rules.evaluar(operacion)
        filas.append(operacion.a_fila(resultado, momento))
        resumen[operacion.status_code] += 1
        logger.debug(
            "%s | %s -> %s | HTTP %s | %s",
            operacion.id,
            operacion.solicitante,
            operacion.target,
            operacion.status_code,
            resultado,
        )

    return filas, resumen, descartadas


def imprimir_resumen(
    resumen: Counter,
    carga: csv_writer.ResultadoCarga,
    descartadas: int,
    dry_run: bool,
) -> None:
    """Muestra por consola el desglose de la corrida."""
    print()
    print(f"Operaciones leidas del log : {sum(resumen.values())}")
    print(f"Filas nuevas en el reporte : {carga.nuevas}")
    print(f"Omitidas (ya existentes)   : {carga.omitidas}")
    if descartadas:
        print(f"Descartadas (sin parsear)  : {descartadas}")
    if dry_run:
        print("Modo --dry-run: no se escribio nada en disco.")

    if resumen:
        print()
        print("Desglose por codigo de respuesta:")
        # Se ordena por frecuencia para que lo mas comun quede arriba.
        for status, cantidad in resumen.most_common():
            etiqueta = ETIQUETAS_STATUS.get(status, "Sin clasificar")
            print(f"  {cantidad:5d}  HTTP {status}  {etiqueta}")


def main(argv: list[str] | None = None) -> int:
    """Ejecuta el pipeline y devuelve el codigo de salida del proceso."""
    argumentos = construir_argumentos().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if argumentos.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    accion = ACCIONES[argumentos.accion]
    momento = datetime.now(UTC)

    try:
        fechas = rango_de_fechas(argumentos.fecha, argumentos.hasta)
    except ValueError as error:
        logger.error("%s", error)
        return ERROR

    filas: list[dict[str, str]] = []
    resumen: Counter = Counter()
    descartadas = 0
    procesadas = 0

    for fecha in fechas:
        try:
            filas_fecha, resumen_fecha, descartadas_fecha = procesar_fecha(
                fecha, accion, argumentos.input_dir, momento
            )
        except FileNotFoundError as error:
            logger.warning("No se encontro el log de %s (%s); se omite.", fecha, error)
            continue
        except OSError as error:
            logger.error("No se pudo leer el log de %s: %s", fecha, error)
            return ERROR

        logger.info("%s: %d operaciones de '%s'.", fecha, len(filas_fecha), accion.clave)
        filas.extend(filas_fecha)
        resumen.update(resumen_fecha)
        descartadas += descartadas_fecha
        procesadas += 1

    if procesadas == 0:
        logger.error("No se proceso ningun log. Revisa --fecha y --input-dir.")
        return SIN_ARCHIVO

    try:
        carga = csv_writer.escribir(filas, argumentos.output, dry_run=argumentos.dry_run)
    except OSError as error:
        logger.error("No se pudo escribir el reporte: %s", error)
        return ERROR

    imprimir_resumen(resumen, carga, descartadas, argumentos.dry_run)
    if not argumentos.dry_run:
        print()
        print(f"Reporte actualizado: {argumentos.output}")
    return EXITO


if __name__ == "__main__":
    sys.exit(main())
