"""Configuracion y constantes del pipeline.

Este modulo concentra todo lo que un analista podria querer ajustar sin tocar la
logica: rutas por defecto, nombres de columnas, textos de los resultados y el
registro de acciones que el pipeline sabe procesar.

Regla importante: los literales que se comparan contra datos del log se guardan
**ya normalizados** con :func:`~src.utils.texto.normalizar`. Asi es imposible que
una mayuscula o un acento se cuele en un solo lado de la comparacion.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.utils.texto import normalizar

# ---------------------------------------------------------------------------
# Rutas por defecto (todas sobreescribibles desde la CLI)
# ---------------------------------------------------------------------------
RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
DIR_ENTRADA = RAIZ_PROYECTO / "data" / "input"
DIR_SALIDA = RAIZ_PROYECTO / "data" / "output"
ARCHIVO_REPORTE = DIR_SALIDA / "tabla_reporte_bot.csv"

#: Los logs se nombran por fecha: ``2026-08-29.log``.
FORMATO_NOMBRE_LOG = "{fecha}.log"

#: ``utf-8-sig`` escribe el BOM para que Excel muestre bien los acentos de las
#: cabeceras al abrir el CSV con doble clic.
CODIFICACION_REPORTE = "utf-8-sig"


# ---------------------------------------------------------------------------
# Esquema del reporte
# ---------------------------------------------------------------------------
#: Orden exacto de las columnas del CSV. `id` es la clave unica del reporte.
COLUMNAS: tuple[str, ...] = (
    "id",
    "timestamp",
    "solicitante",
    "target",
    "acción",
    "sistema",
    "nombre completo del usuario solicitante",
    "nombre completo del usuario target",
    "oficina del usuario solicitante",
    "oficina del usuario target",
    "resultado final",
    "updated_at",
)


# ---------------------------------------------------------------------------
# Literales de negocio (normalizados en origen)
# ---------------------------------------------------------------------------
#: Un solicitante solo puede resetear si su DESCRIPTION empieza por alguno de
#: estos prefijos.
PREFIJOS_AUTORIZADOS: tuple[str, ...] = (normalizar("gerente"), normalizar("admin"))

#: Unidad organizativa restringida: si el target pertenece a ella, se niega.
#: Se compara por igualdad exacta contra ``normalizar(OU_NAME)``.
OU_RESTRINGIDA: str = normalizar("OAT/Cedis/BY")

#: Marca que identifica una oficina corporativa dentro del campo OFFICE.
MARCA_CORPORATIVA: str = normalizar("corporativo")

#: Umbral de timeout declarado por la API del bot, en segundos. Solo se usa
#: para redactar el mensaje del 504; la clasificacion la da el status code.
UMBRAL_TIMEOUT_SEGUNDOS: int = 35


# ---------------------------------------------------------------------------
# Registro de acciones
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Accion:
    """Describe un tipo de operacion que el pipeline sabe extraer del log.

    Attributes:
        clave: Identificador interno; es el valor que se pasa a ``--accion``.
        endpoint: Fragmento de URL que identifica la operacion en el log. Basta
            con que aparezca en el primer registro de la operacion.
        etiqueta: Texto que se escribe en la columna ``acción`` del reporte.
        sistema: Texto que se escribe en la columna ``sistema``.
        parametro_solicitante: Nombre del parametro de query con el solicitante.
        parametro_target: Nombre del parametro de query con el usuario objetivo.
    """

    clave: str
    endpoint: str
    etiqueta: str
    sistema: str
    parametro_solicitante: str
    parametro_target: str


#: Acciones soportadas. Para dar de alta una nueva (por ejemplo el endpoint
#: ``v2/sap/register_user``, que ya aparece en los logs) basta con:
#:   1. anadir una entrada aqui,
#:   2. registrar su tabla de reglas en ``src.transform.rules``,
#: sin tocar el lector ni el escritor.
ACCIONES: dict[str, Accion] = {
    "reseteo_usuario": Accion(
        clave="reseteo_usuario",
        endpoint="users_admin/resetuser",
        etiqueta="Reseteo de usuario",
        sistema="ADManager",
        parametro_solicitante="sAMAccountName_requester",
        parametro_target="sAMAccountName_target",
    ),
}

#: Accion que se procesa si el usuario no indica ninguna.
ACCION_POR_DEFECTO = "reseteo_usuario"


# ---------------------------------------------------------------------------
# Textos de la columna "resultado final"
# ---------------------------------------------------------------------------
MENSAJES: dict[str, str] = {
    "ok": "Reseteo ejecutado correctamente.",
    "corporativo": "Solicitud aceptada: la oficina del usuario objetivo es corporativa.",
    "aceptado_generico": "Solicitud aceptada para procesamiento posterior.",
    "denegado_prefijo": "Acceso denegado: ",
    "no_encontrado_target": "No se encontró al usuario objetivo en ADManager.",
    "no_encontrado_solicitante": "No se encontró al usuario solicitante en ADManager.",
    "no_encontrado_ambos": (
        "No se encontró al usuario solicitante ni al usuario objetivo en ADManager."
    ),
    "sin_tokens": "No se pudo completar: se agotaron los tokens de ADManager.",
    "error_interno": "Error interno inesperado del bot durante el procesamiento.",
    "servicio_no_disponible": "Servicio no disponible. Error reportado por ADManager: ",
    "servicio_no_disponible_sin_detalle": (
        "Servicio no disponible. ADManager no devolvió un detalle del error."
    ),
    "timeout": (
        "Tiempo de espera agotado: la comunicación superó los {umbral} segundos "
        "(duración: {duracion} s). Se da por hecho que el reseteo no se pudo ejecutar."
    ),
    "no_clasificado": "Resultado no clasificado (código HTTP {status}).",
}

#: Etiquetas cortas para el resumen por consola. El detalle completo (duracion
#: del timeout, error concreto de ADManager, razones del rechazo) vive en el CSV;
#: aqui interesa agrupar, no repetir cada variante.
ETIQUETAS_STATUS: dict[int, str] = {
    200: "Reseteo ejecutado correctamente",
    202: "Solicitud aceptada",
    403: "Acceso denegado",
    404: "Usuario no encontrado",
    429: "Sin tokens de ADManager",
    500: "Error interno del bot",
    503: "Servicio no disponible",
    504: "Tiempo de espera agotado",
}

#: Razones acumulables de un rechazo 403, en el orden en que se concatenan.
RAZONES_DENEGADO: dict[str, str] = {
    "no_autorizado": "el solicitante no es gerente ni administrador",
    "oficina_distinta": "el solicitante y el usuario objetivo no pertenecen a la misma oficina",
    "ou_restringida": "el usuario objetivo pertenece a la OU restringida OAT/Cedis/BY",
    "sin_causa": "el bot rechazó la solicitud sin una causa identificable en el log",
}

#: Separador entre razones cuando un 403 cumple varias a la vez.
SEPARADOR_RAZONES = "; "
