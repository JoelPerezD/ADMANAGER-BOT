"""Escritura idempotente del reporte `tabla_reporte_bot`.

El requisito central es poder reprocesar una fecha pasada sin duplicar ni alterar
lo ya cargado. Se consigue con tres decisiones:

* La columna ``id`` es el ``operation_Id`` del log, que es unico de forma global,
  asi que basta con descartar los identificadores ya presentes.
* Las filas nuevas se **anaden al final**: las existentes no se reescriben ni se
  reordenan, de modo que sus bytes quedan intactos.
* La escritura es **atomica** (archivo temporal + ``os.replace``), para que una
  interrupcion a mitad de la corrida no deje el reporte truncado.
"""

from __future__ import annotations

import codecs
import csv
import io
import os
import shutil
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from src.config import CODIFICACION_REPORTE, COLUMNAS


@dataclass(frozen=True)
class ResultadoCarga:
    """Resumen de lo que hizo una escritura.

    Attributes:
        nuevas: Filas efectivamente anadidas al reporte.
        omitidas: Filas descartadas porque su ``id`` ya estaba en el reporte.
    """

    nuevas: int
    omitidas: int


def leer_ids_existentes(ruta: Path) -> set[str]:
    """Devuelve los ``id`` ya presentes en el reporte.

    Si el archivo aun no existe se devuelve un conjunto vacio, que es lo que
    permite que la primera corrida funcione sin ningun paso de inicializacion.
    """
    if not ruta.exists():
        return set()

    with ruta.open(newline="", encoding=CODIFICACION_REPORTE) as archivo:
        lector = csv.DictReader(archivo)
        return {fila["id"] for fila in lector if fila.get("id")}


def _serializar(filas: Iterable[Sequence[str]]) -> bytes:
    """Convierte filas ya ordenadas en bytes CSV listos para anexar."""
    buffer = io.StringIO(newline="")
    csv.writer(buffer).writerows(filas)
    # Se codifica en utf-8 "a secas": el BOM solo se escribe al crear el archivo.
    return buffer.getvalue().encode("utf-8")


def escribir(filas: Iterable[dict[str, str]], ruta: Path, dry_run: bool = False) -> ResultadoCarga:
    """Anade al reporte unicamente las filas cuyo ``id`` aun no existe.

    Args:
        filas: Filas candidatas, con las claves de :data:`src.config.COLUMNAS`.
        ruta: Ruta del CSV de reporte.
        dry_run: Si es ``True`` calcula el resultado pero no toca el disco.

    Returns:
        El :class:`ResultadoCarga` con el conteo de filas nuevas y omitidas.
    """
    conocidos = leer_ids_existentes(ruta)
    nuevas: list[Sequence[str]] = []
    omitidas = 0

    for fila in filas:
        identificador = fila["id"]
        # `conocidos` se actualiza sobre la marcha para descartar tambien los
        # duplicados que pudieran venir dentro del mismo lote.
        if identificador in conocidos:
            omitidas += 1
            continue
        conocidos.add(identificador)
        nuevas.append([fila.get(columna, "") for columna in COLUMNAS])

    if not dry_run and nuevas:
        _anexar_atomico(ruta, nuevas)

    return ResultadoCarga(nuevas=len(nuevas), omitidas=omitidas)


def _anexar_atomico(ruta: Path, filas: list[Sequence[str]]) -> None:
    """Escribe el reporte completo en un temporal y lo mueve sobre el original.

    El contenido previo se copia byte a byte, de forma que las filas ya
    existentes son literalmente las mismas antes y despues de la operacion.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)

    # El temporal se crea en el mismo directorio para que `os.replace` sea un
    # movimiento atomico dentro del mismo sistema de archivos.
    descriptor, ruta_temporal = tempfile.mkstemp(dir=ruta.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as temporal:
            if ruta.exists():
                with ruta.open("rb") as original:
                    shutil.copyfileobj(original, temporal)
            else:
                # Archivo nuevo: BOM (para que Excel respete los acentos) y cabecera.
                temporal.write(codecs.BOM_UTF8)
                temporal.write(_serializar([COLUMNAS]))

            temporal.write(_serializar(filas))

        os.replace(ruta_temporal, ruta)
    except BaseException:
        Path(ruta_temporal).unlink(missing_ok=True)
        raise
