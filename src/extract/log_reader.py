"""Lectura del archivo .log diario y agrupacion en operaciones.

El formato del log tiene dos particularidades que condicionan todo este modulo y
que fueron verificadas sobre los logs reales:

1. **Un registro puede ocupar varias lineas.** El volcado ``Raw Response:`` de
   ADManager continua en lineas que *no* repiten el ``operation_Id``. Por eso no
   se puede iterar linea a linea: una linea que empieza con timestamp abre un
   registro nuevo, y cualquier linea posterior sin timestamp pertenece al
   registro anterior.

2. **Las operaciones se intercalan.** El bot atiende peticiones concurrentes, asi
   que los registros de una misma operacion no son contiguos (en el log del
   2026-08-29, 101 de 442 operaciones estan partidas en varios bloques). Agrupar
   por registros consecutivos fragmentaria casi una de cada cuatro operaciones,
   de modo que se acumulan en un diccionario indexado por ``operation_Id``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.config import FORMATO_NOMBRE_LOG, Accion

#: Una linea que empieza con marca de tiempo ISO abre un registro nuevo.
PATRON_INICIO_REGISTRO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

#: Identificador de correlacion que comparten todos los registros de una operacion.
PATRON_OPERATION_ID = re.compile(r"operation_Id=([0-9a-fA-F]+)")


@dataclass(frozen=True)
class OperacionCruda:
    """Conjunto de registros del log que comparten un mismo ``operation_Id``.

    Attributes:
        id: El ``operation_Id``, que actua como clave unica de la operacion.
        registros: Registros logicos completos, en orden cronologico.
    """

    id: str
    registros: list[str]

    @property
    def disparador(self) -> str:
        """Primer registro de la operacion: la llamada al endpoint del bot."""
        return self.registros[0]


def ruta_log(fecha: date, dir_entrada: Path) -> Path:
    """Construye la ruta del log correspondiente a ``fecha``.

    Cada archivo contiene exactamente un dia, el de su propio nombre, asi que no
    hace falta escanear el directorio completo.

    Ejemplo:
        ``date(2026, 8, 29)`` -> ``data/input/2026-08-29.log``
    """
    return dir_entrada / FORMATO_NOMBRE_LOG.format(fecha=fecha.isoformat())


def iter_registros(ruta: Path) -> Iterator[str]:
    """Reconstruye los registros logicos del archivo, uno a uno.

    Lee el archivo de forma perezosa: nunca carga todas las lineas en memoria.

    Args:
        ruta: Archivo .log a leer.

    Yields:
        Cada registro completo, incluyendo sus lineas de continuacion.
    """
    # `errors="replace"` evita que un byte corrupto aborte una corrida diaria.
    with ruta.open(encoding="utf-8", errors="replace") as archivo:
        acumulado: list[str] = []
        for linea in archivo:
            if PATRON_INICIO_REGISTRO.match(linea) and acumulado:
                yield "".join(acumulado)
                acumulado = [linea]
            else:
                acumulado.append(linea)
        if acumulado:
            yield "".join(acumulado)


def iter_operaciones(ruta: Path, accion: Accion) -> Iterator[OperacionCruda]:
    """Agrupa los registros de ``ruta`` en operaciones de la accion indicada.

    El filtrado se decide con el **primer** registro de cada operacion, que
    siempre es la llamada al endpoint del bot. Gracias a eso, las operaciones que
    no interesan se descartan al vuelo y solo se retienen en memoria las de la
    accion pedida.

    Args:
        ruta: Archivo .log a procesar.
        accion: Accion cuyo ``endpoint`` identifica las operaciones a conservar.

    Yields:
        Una :class:`OperacionCruda` por operacion, en orden de aparicion.
    """
    relevantes: dict[str, list[str]] = {}
    descartadas: set[str] = set()

    for registro in iter_registros(ruta):
        coincidencia = PATRON_OPERATION_ID.search(registro)
        if not coincidencia:
            # Registro sin identificador de correlacion: no se puede atribuir.
            continue

        operation_id = coincidencia.group(1)
        if operation_id in descartadas:
            continue

        if operation_id not in relevantes:
            # Primer registro de esta operacion: aqui se decide si nos interesa.
            if accion.endpoint not in registro:
                descartadas.add(operation_id)
                continue
            relevantes[operation_id] = []

        relevantes[operation_id].append(registro)

    # Los dict de Python conservan el orden de insercion, que aqui equivale al
    # orden cronologico en que aparecio cada operacion.
    for operation_id, registros in relevantes.items():
        yield OperacionCruda(id=operation_id, registros=registros)
