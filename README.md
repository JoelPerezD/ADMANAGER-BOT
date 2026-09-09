# Tabla Reporte del bot de ADManager

En la empresa hay un bot que resetea contraseñas de Active Directory. Funciona
bien, pero lo único que deja atrás es un `.log` enorme por día, pensado para
depurar y no para que nadie lo lea. Cuando alguien pregunta cuántos reseteos se
hicieron ayer, o por qué le rebotó la solicitud de algun usuario, no hay forma de
responder sin abrir el archivo y rastrearlo a mano.

Esto es lo que se realizo para no volver a hacer eso: un pipeline que toma esos logs,
los ordena en un CSV con una fila por operación y traduce el desenlace de cada
una a algo que se entienda leyéndolo. Donde el log dice `403`, el reporte dice
por qué se denegó. La idea es que el archivo se pueda abrir en Excel, filtrar y
sacar conclusiones sin saber nada del bot ni del formato del log.

Pipeline que convierte los logs diarios del bot en una tabla de reporte lista para
analizar: **`tabla_reporte_bot.csv`**.

## ¿Para qué sirve?

El bot atiende solicitudes de reseteo de contraseña: recibe una petición, consulta
al solicitante y al usuario objetivo en **ADManager**, aplica las reglas de
autorización y, si procede, ejecuta el reseteo. Todo eso queda registrado en un
archivo `.log` por día.

Ese log es difícil de leer: un solo día puede pasar de las 9 000 líneas, los
registros de una misma operación no están juntos y el desenlace se guarda como un
código HTTP crudo (`403`, `503`, …). Responder a "¿cuántos reseteos fallaron ayer
y por qué?" obliga a rastrear el archivo a mano.

Este pipeline resuelve eso: por cada operación genera **una fila** con quién la
pidió, sobre quién, y **qué pasó explicado en lenguaje natural**, en lugar del
número.

| En el log | En el reporte |
|---|---|
| `"HTTP/1.1" 403` | `Acceso denegado: el solicitante y el usuario objetivo no pertenecen a la misma oficina.` |
| `"HTTP/1.1" 404` | `No se encontró al usuario objetivo en ADManager.` |
| `"HTTP/1.1" 503` | `Servicio no disponible. Error reportado por ADManager: LOGON_NAME: … - No such user matched.` |

Se puede **reejecutar sobre fechas pasadas sin miedo**: solo añade registros
nuevos, nunca duplica ni modifica los que ya estaban.

## Requisitos

- Python 3.11 o superior
- [`uv`](https://docs.astral.sh/uv/) para gestionar dependencias

El pipeline en sí **no tiene dependencias externas**: funciona solo con la
librería estándar de Python. `uv` se usa para el entorno y las herramientas de
desarrollo (`ruff` y `pytest`).

## Instalación

```bash
# 1. Instalar uv (solo la primera vez)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# 2. Clonar y preparar el entorno
git clone https://github.com/JoelPerezD/ADMANAGER-BOT.git
cd ADMANAGER-BOT
uv sync
```

## Uso

Coloca los archivos `.log` en `data/input/`. Deben llamarse por su fecha:
`2026-08-29.log`.

```bash
# Procesar un día
uv run python -m src.main --fecha 2026-08-29

# Procesar un rango de fechas (ambas incluidas)
uv run python -m src.main --fecha 2026-08-29 --hasta 2026-09-01

# Ver qué haría, sin escribir nada
uv run python -m src.main --fecha 2026-08-29 --dry-run

# Usar otras rutas
uv run python -m src.main --fecha 2026-08-29 \
    --input-dir /ruta/a/logs --output /ruta/al/reporte.csv
```

Salida de ejemplo:

```
INFO 2026-08-29: 433 operaciones de 'reseteo_usuario'.

Operaciones leidas del log : 433
Filas nuevas en el reporte : 433
Omitidas (ya existentes)   : 0

Desglose por codigo de respuesta:
    391  HTTP 200  Reseteo ejecutado correctamente
     30  HTTP 404  Usuario no encontrado
      9  HTTP 403  Acceso denegado
      2  HTTP 503  Servicio no disponible
      1  HTTP 500  Error interno del bot

Reporte actualizado: data/output/tabla_reporte_bot.csv
```

### Opciones

| Opción | Descripción |
|---|---|
| `--fecha` | Fecha del log a procesar (`YYYY-MM-DD`). **Obligatoria.** |
| `--hasta` | Fecha final para procesar un rango. |
| `--accion` | Tipo de operación a extraer. Por defecto `reseteo_usuario`. |
| `--input-dir` | Carpeta de los `.log`. Por defecto `data/input/`. |
| `--output` | Ruta del CSV. Por defecto `data/output/tabla_reporte_bot.csv`. |
| `--dry-run` | Procesa y muestra el resumen sin escribir en disco. |
| `--verbose` | Muestra el detalle de cada operación. |

Códigos de salida: `0` correcto · `1` error · `2` no se encontró ningún log.

## El reporte

| Columna | Contenido |
|---|---|
| `id` | `operation_Id` del log. Clave única de la operación. |
| `timestamp` | Momento de la solicitud. |
| `solicitante` / `target` | `sAMAccountName` de cada usuario. |
| `acción` / `sistema` | `Reseteo de usuario` / `ADManager`. |
| `nombre completo …` | `FIRST_NAME` + `LAST_NAME` de ADManager. |
| `oficina …` | Campo `OFFICE` de ADManager. |
| `resultado final` | Qué pasó, explicado. |
| `updated_at` | Cuándo se escribió la fila en el reporte. |

El CSV se guarda con BOM UTF-8 para que Excel muestre bien los acentos.

### Reglas del "resultado final"

| Código | Resultado |
|---|---|
| **200** | Reseteo ejecutado correctamente. |
| **202** | Solicitud aceptada porque la oficina del objetivo es corporativa. |
| **403** | Acceso denegado, enumerando **todas** las causas aplicables. |
| **404** | Precisa si no se encontró al objetivo, al solicitante o a ninguno. |
| **429** | Se agotaron los tokens de ADManager. |
| **500** | Error interno inesperado del bot. |
| **503** | Servicio no disponible, con el error exacto que devolvió ADManager. |
| **504** | Se superaron los 35 segundos; se da por hecho que el reseteo no se ejecutó. |

Un rechazo (403) puede deberse a varias causas a la vez, y el reporte las
concatena:

- el solicitante no es gerente ni administrador (su `DESCRIPTION` no empieza por
  "gerente" ni "admin");
- solicitante y objetivo no pertenecen a la misma oficina;
- el objetivo pertenece a la OU restringida `OAT/Cedis/BY`.

Todas las comparaciones se hacen **sin acentos y en minúsculas**, en ambos lados.

## Idempotencia

Reprocesar una fecha ya cargada es seguro:

```bash
uv run python -m src.main --fecha 2026-08-29   # 433 filas nuevas
uv run python -m src.main --fecha 2026-08-29   # 0 nuevas, 433 omitidas
```

Funciona así:

1. El `id` es el `operation_Id`, único de forma global en los logs.
2. Antes de escribir se leen los `id` ya presentes y se descartan los repetidos.
3. Las filas nuevas se **añaden al final**: las existentes no se reescriben.
4. La escritura es **atómica** (archivo temporal + `os.replace`), así que una
   interrupción no deja el reporte a medias.

## Estructura

```text
├── data/
│   ├── input/          # archivos .log de entrada (no se versionan)
│   └── output/         # tabla_reporte_bot.csv (no se versiona)
├── notebooks/          # exploración; nunca lógica de producción
├── src/
│   ├── main.py         # CLI y orquestación
│   ├── config.py       # rutas, columnas, acciones y textos
│   ├── extract/        # lectura del .log y agrupación en operaciones
│   ├── transform/      # parseo de campos y reglas de negocio
│   ├── load/           # escritura idempotente del CSV
│   └── utils/          # normalización de texto
└── tests/
    ├── unit/           # funciones aisladas
    ├── integration/    # varios módulos trabajando juntos
    ├── e2e/            # la CLI completa
    └── fixtures/       # logs de ejemplo recortados de datos reales
```

Cada capa tiene una responsabilidad única, así que un cambio de formato en el log
solo toca `extract/` y `transform/`, y un cambio en el destino del reporte solo
toca `load/`.

## Añadir una acción nueva

El pipeline solo procesa los reseteos, pero está preparado para más. Los logs ya
contienen, por ejemplo, el endpoint `v2/sap/register_user`. Para darlo de alta:

1. Registra la acción en `src/config.py`:

   ```python
   ACCIONES = {
       ...,
       "registro_sap": Accion(
           clave="registro_sap",
           endpoint="sap/register_user",
           etiqueta="Registro de usuario",
           sistema="SAP",
           parametro_solicitante="sAMAccountName_requester",
           parametro_target="sAMAccountName_target",
       ),
   }
   ```

2. Añade su tabla de reglas en `src/transform/rules.py`, dentro de
   `REGLAS_POR_ACCION`.

Ni el lector ni el escritor necesitan cambios. Después:

```bash
uv run python -m src.main --fecha 2026-08-29 --accion registro_sap
```

## Desarrollo

```bash
uv run ruff check .          # linting
uv run ruff format .         # formateo
uv run pytest                # toda la suite
uv run pytest tests/unit     # solo las pruebas unitarias
```

Las pruebas de `tests/e2e/test_regresion_datos_reales.py` comprueban los conteos
sobre los logs de producción y se omiten solas si `data/input/` está vacío.

## Notas sobre el formato del log

Tres detalles del log condicionan el diseño, y conviene conocerlos antes de tocar
el código:

1. **Un registro puede ocupar varias líneas.** El volcado `Raw Response:` de
   ADManager continúa en líneas que no repiten el `operation_Id`. Leer línea a
   línea dejaría ese JSON huérfano y el reporte perdería nombres y oficinas.

2. **Las operaciones se intercalan.** El bot atiende peticiones en paralelo: en el
   log del 2026-08-29, 101 de 442 operaciones están partidas en varios bloques.
   Por eso se agrupa por `operation_Id` y no por cercanía en el archivo.

3. **Los usuarios llegan URL-encoded.** En la query aparecen valores como
   `Ana+laura`. Sin decodificarlos no cruzan con su búsqueda en ADManager.

