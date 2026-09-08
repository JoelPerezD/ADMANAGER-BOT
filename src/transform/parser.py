"""Parseo de una operacion cruda del log a un objeto de dominio.

Convierte los registros de texto que entrega :mod:`src.extract.log_reader` en una
:class:`Operacion`, con los datos de ADManager ya resueltos y listos para que
:mod:`src.transform.rules` evalue las reglas de negocio.

Detalles del formato que resuelve este modulo (verificados sobre los logs reales):

* El solicitante y el usuario objetivo llegan **URL-encoded** en la query del
  endpoint: aparecen valores como ``Ana+laura`` o ``CONSUMOS+INTERNOS+0358``. Sin
  decodificarlos no cruzan con su busqueda en ADManager.
* El orden de las busquedas ``SearchUser`` **varia** entre operaciones, asi que
  cada resultado se indexa por el ``sAMAccountName`` que aparece en su ``filter``,
  nunca por su posicion.
* Un usuario inexistente se reporta con ``"UsersList":[],"count":0`` y HTTP 200:
  el "no encontrado" esta en el cuerpo, no en el status.
"""

from __future__ import annotations

import ast
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from src.config import Accion
from src.extract.log_reader import OperacionCruda
from src.utils.texto import normalizar

logger = logging.getLogger(__name__)

# --- Patrones del log ------------------------------------------------------

#: Llamada al endpoint del bot. Es el primer registro de cada operacion y trae
#: el status final: ``HTTP Request: http://...  "HTTP/1.1" 200``.
PATRON_DISPARADOR = re.compile(r'HTTP Request:\s+(?P<url>\S+)\s+"HTTP/1\.1"\s+(?P<status>\d{3})')

#: Marca de tiempo al inicio de cada registro.
PATRON_TIMESTAMP = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}T[\d:.]+)Z")

#: Usuario consultado en una busqueda de ADManager.
PATRON_FILTRO_USUARIO = re.compile(r"filter':\s*'\(sAMAccountName:equal:(?P<usuario>[^)]+)\)'")

#: Respuesta de ADManager a un reseteo: ``ADM-Raw response | status: 200 | body: [...]``.
PATRON_ADM_RAW = re.compile(
    r"ADM-Raw response\s*\|\s*status:\s*(?P<status>\d+)\s*\|\s*body:\s*(?P<body>.*)", re.S
)

#: Extraccion de emergencia del mensaje de error si el cuerpo no se puede evaluar.
PATRON_STATUS_MESSAGE = re.compile(r"'statusMessage':\s*'(?P<mensaje>(?:[^'\\]|\\.)*)'")

#: Delimitadores del volcado JSON de una busqueda de ADManager.
MARCA_INICIO_JSON = "Raw Response:"
MARCA_FIN_JSON = ", Raw status_code"

#: Valores con los que ADManager representa un campo vacio.
VALORES_VACIOS = frozenset({"", "-", "<not set>"})


def _limpiar(valor: str | None) -> str:
    """Normaliza los marcadores de campo vacio de ADManager a cadena vacia."""
    texto = (valor or "").strip()
    return "" if texto in VALORES_VACIOS else texto


@dataclass(frozen=True)
class UsuarioAD:
    """Datos de un usuario tal y como los devuelve ADManager.

    Solo se conservan los campos que el reporte o las reglas necesitan; el resto
    del volcado de ADManager se descarta.
    """

    sam_account_name: str
    nombre: str
    apellido: str
    oficina: str
    ou_name: str
    descripcion: str

    @property
    def nombre_completo(self) -> str:
        """Nombre y apellido unidos, omitiendo las partes que vengan vacias."""
        return " ".join(parte for parte in (self.nombre, self.apellido) if parte)

    @classmethod
    def desde_admanager(cls, datos: dict) -> UsuarioAD:
        """Construye el usuario a partir de un elemento de ``UsersList``."""
        return cls(
            sam_account_name=_limpiar(datos.get("SAM_ACCOUNT_NAME")),
            nombre=_limpiar(datos.get("FIRST_NAME")),
            apellido=_limpiar(datos.get("LAST_NAME")),
            oficina=_limpiar(datos.get("OFFICE")),
            ou_name=_limpiar(datos.get("OU_NAME")),
            descripcion=_limpiar(datos.get("DESCRIPTION")),
        )


@dataclass(frozen=True)
class Operacion:
    """Una operacion del bot, ya parseada y lista para evaluar reglas.

    Attributes:
        id: ``operation_Id`` del log; clave unica del reporte.
        timestamp: Marca de tiempo del registro disparador, tal cual aparece.
        solicitante: ``sAMAccountName`` del solicitante, ya decodificado.
        target: ``sAMAccountName`` del usuario objetivo, ya decodificado.
        status_code: Codigo HTTP devuelto por el bot.
        accion: Accion a la que pertenece la operacion.
        usuario_solicitante: Datos del solicitante en AD, o ``None`` si no existe.
        usuario_target: Datos del objetivo en AD, o ``None`` si no existe.
        mensaje_admanager: ``statusMessage`` del reseteo, si ADManager reporto uno.
        duracion_segundos: Tiempo entre el primer y el ultimo registro.
    """

    id: str
    timestamp: str
    solicitante: str
    target: str
    status_code: int
    accion: Accion
    usuario_solicitante: UsuarioAD | None
    usuario_target: UsuarioAD | None
    mensaje_admanager: str
    duracion_segundos: float

    def a_fila(self, resultado_final: str, momento: datetime) -> dict[str, str]:
        """Proyecta la operacion a una fila del reporte.

        Args:
            resultado_final: Mensaje legible calculado por las reglas de negocio.
            momento: Instante de la escritura, para la columna ``updated_at``.
        """
        solicitante = self.usuario_solicitante
        target = self.usuario_target
        nombre_solicitante = solicitante.nombre_completo if solicitante else ""
        nombre_target = target.nombre_completo if target else ""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "solicitante": self.solicitante,
            "target": self.target,
            "acción": self.accion.etiqueta,
            "sistema": self.accion.sistema,
            "nombre completo del usuario solicitante": nombre_solicitante,
            "nombre completo del usuario target": nombre_target,
            "oficina del usuario solicitante": solicitante.oficina if solicitante else "",
            "oficina del usuario target": target.oficina if target else "",
            "resultado final": resultado_final,
            "updated_at": momento.isoformat(timespec="seconds"),
        }


# --- Funciones de parseo ---------------------------------------------------


def _parsear_disparador(registro: str, accion: Accion) -> tuple[str, str, int] | None:
    """Extrae solicitante, objetivo y status de la llamada al endpoint.

    ``parse_qs`` decodifica la query, de modo que ``Ana+laura`` vuelve a ser
    ``"Ana laura"`` y cruza con su busqueda en ADManager.
    """
    coincidencia = PATRON_DISPARADOR.search(registro)
    if not coincidencia:
        return None

    parametros = parse_qs(urlsplit(coincidencia.group("url")).query)
    solicitante = parametros.get(accion.parametro_solicitante, [""])[0]
    target = parametros.get(accion.parametro_target, [""])[0]
    return solicitante, target, int(coincidencia.group("status"))


def _extraer_timestamp(registro: str) -> str:
    """Devuelve la marca de tiempo de un registro, o cadena vacia si no la tiene."""
    coincidencia = PATRON_TIMESTAMP.match(registro)
    return coincidencia.group("ts") if coincidencia else ""


def _calcular_duracion(registros: list[str]) -> float:
    """Segundos transcurridos entre el primer y el ultimo registro con timestamp."""
    marcas = [_extraer_timestamp(registro) for registro in registros]
    validas = []
    for marca in marcas:
        if not marca:
            continue
        try:
            validas.append(datetime.fromisoformat(marca))
        except ValueError:
            continue

    if len(validas) < 2:
        return 0.0
    return round((max(validas) - min(validas)).total_seconds(), 2)


def _indexar_usuarios(registros: list[str]) -> dict[str, UsuarioAD | None]:
    """Cruza cada busqueda de ADManager con el usuario que consultaba.

    La clave es el ``sAMAccountName`` normalizado, porque el log no es consistente
    en el uso de mayusculas (aparecen tanto ``admsistemas014`` como
    ``AdmSistemas014``).

    Returns:
        Diccionario ``sAMAccountName normalizado -> UsuarioAD``. El valor es
        ``None`` cuando la busqueda no devolvio ningun usuario (``count: 0``).
    """
    usuarios: dict[str, UsuarioAD | None] = {}

    for registro in registros:
        coincidencia = PATRON_FILTRO_USUARIO.search(registro)
        if not coincidencia or MARCA_INICIO_JSON not in registro:
            continue

        consultado = normalizar(coincidencia.group("usuario"))
        cuerpo = registro.split(MARCA_INICIO_JSON, 1)[1].rsplit(MARCA_FIN_JSON, 1)[0].strip()

        if not cuerpo:
            # ADManager respondio 200 con el cuerpo vacio. No es un fallo del
            # parser: el usuario simplemente queda sin resolver, y suele ser la
            # causa de que el bot termine devolviendo un 500.
            logger.debug("ADManager devolvio una respuesta vacia para %r", consultado)
            continue

        try:
            lista = json.loads(cuerpo).get("UsersList") or []
        except (json.JSONDecodeError, AttributeError):
            logger.warning("Respuesta ilegible de ADManager para %r; se ignora.", consultado)
            continue

        usuarios[consultado] = UsuarioAD.desde_admanager(lista[0]) if lista else None

    return usuarios


def _extraer_mensaje_admanager(registros: list[str]) -> str:
    """Recupera el ``statusMessage`` que ADManager devolvio al intentar el reseteo.

    Es el detalle que exige el mensaje de servicio no disponible (503). El cuerpo
    viene como literal de Python, no como JSON, asi que se evalua con
    ``ast.literal_eval``; si eso falla se cae a una extraccion por expresion
    regular antes de darse por vencido.
    """
    for registro in reversed(registros):
        coincidencia = PATRON_ADM_RAW.search(registro)
        if not coincidencia:
            continue

        cuerpo = coincidencia.group("body").strip()
        try:
            elementos = ast.literal_eval(cuerpo)
        except (ValueError, SyntaxError):
            respaldo = PATRON_STATUS_MESSAGE.search(cuerpo)
            return respaldo.group("mensaje").strip() if respaldo else ""

        if isinstance(elementos, list) and elementos and isinstance(elementos[0], dict):
            return str(elementos[0].get("statusMessage", "")).strip()

    return ""


def parsear(cruda: OperacionCruda, accion: Accion) -> Operacion | None:
    """Convierte una operacion cruda en una :class:`Operacion`.

    Un fallo de parseo nunca interrumpe la corrida: se registra un aviso con el
    ``operation_Id`` afectado y la operacion se descarta.

    Args:
        cruda: Operacion tal como la entrega la capa de extraccion.
        accion: Accion a la que pertenece la operacion.

    Returns:
        La operacion parseada, o ``None`` si no se pudo leer el registro
        disparador (sin el no hay solicitante, objetivo ni status).
    """
    disparador = _parsear_disparador(cruda.disparador, accion)
    if disparador is None:
        logger.warning("Operacion %s: no se pudo leer el registro disparador; se omite.", cruda.id)
        return None

    solicitante, target, status_code = disparador
    usuarios = _indexar_usuarios(cruda.registros)

    return Operacion(
        id=cruda.id,
        timestamp=_extraer_timestamp(cruda.disparador),
        solicitante=solicitante,
        target=target,
        status_code=status_code,
        accion=accion,
        usuario_solicitante=usuarios.get(normalizar(solicitante)),
        usuario_target=usuarios.get(normalizar(target)),
        mensaje_admanager=_extraer_mensaje_admanager(cruda.registros),
        duracion_segundos=_calcular_duracion(cruda.registros),
    )
