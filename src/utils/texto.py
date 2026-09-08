"""Utilidades de texto compartidas por todo el pipeline.

Todas las comparaciones de negocio (oficinas, descripciones, unidades
organizativas) pasan por :func:`normalizar`. Tener una unica funcion evita que
un acento o una mayuscula cambien el resultado de una regla segun el modulo que
la evalue: el dato del log y el literal declarado en ``config`` se normalizan
siempre con la misma logica.
"""

from __future__ import annotations

import unicodedata


def normalizar(valor: str | None) -> str:
    """Devuelve ``valor`` en minusculas, sin acentos y con espacios colapsados.

    Args:
        valor: Texto a normalizar. Se acepta ``None`` porque los campos de
            ADManager pueden venir ausentes.

    Returns:
        El texto normalizado, o cadena vacia si no habia valor.

    Ejemplos:
        >>> normalizar("  OAT/Cedis/BY ")
        'oat/cedis/by'
        >>> normalizar("Administrador  De  Sistemas")
        'administrador de sistemas'
        >>> normalizar("Mexico") == normalizar("Mexico")
        True
        >>> normalizar(None)
        ''
    """
    if not valor:
        return ""

    # NFKD separa cada letra de su diacritico ("e" + acento) para poder
    # descartar el diacritico y quedarnos con la letra base.
    descompuesto = unicodedata.normalize("NFKD", valor)
    sin_acentos = "".join(
        caracter for caracter in descompuesto if not unicodedata.combining(caracter)
    )

    # split() sin argumentos colapsa cualquier secuencia de espacios en blanco,
    # incluidos tabuladores y saltos de linea.
    return " ".join(sin_acentos.split()).lower()


def empieza_con_alguno(valor: str | None, prefijos: tuple[str, ...]) -> bool:
    """Indica si ``valor``, ya normalizado, empieza por alguno de ``prefijos``.

    Se espera que ``prefijos`` venga normalizado desde ``config``, de forma que
    ambos lados de la comparacion hayan pasado por :func:`normalizar`.

    Ejemplos:
        >>> empieza_con_alguno("Administrador De Sistemas", ("gerente", "admin"))
        True
        >>> empieza_con_alguno("Mozo", ("gerente", "admin"))
        False
    """
    normalizado = normalizar(valor)
    return any(normalizado.startswith(prefijo) for prefijo in prefijos)
