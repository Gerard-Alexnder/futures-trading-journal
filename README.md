# Futures Trading Journal

Aplicación web personal para organizar operaciones de futuros y, en fases posteriores, gestionar riesgo y analizar estadísticas de trading.

## Estado actual: Fase 3A

Servidor Flask con navegación compartida, diseño oscuro adaptable y calculadora de riesgo funcional en `/calculator`. Las otras cinco páginas siguen siendo provisionales. Existe un servicio Python de cuentas y operaciones con SQLite, todavía sin integración con las páginas. No hay envío de órdenes, conexión a brokers ni autenticación.

## Tecnologías

- Python 3.14 o superior, según `pyproject.toml`.
- Flask y su motor de plantillas Jinja.
- HTML, CSS y JavaScript nativo con `fetch()`, sin frameworks frontend ni recursos externos.
- UV para gestionar dependencias y ejecutar Python.

## Estructura

```text
futures-trading-journal/
├── app.py                 # Seis páginas y endpoint JSON de cálculo
├── contracts.py           # Catálogo de instrumentos con Decimal
├── calculations.py        # Validaciones y cálculos independientes de Flask
├── main.py                # Ejemplo inicial; no lo utiliza Flask
├── templates/
│   ├── base.html          # Estructura y menú compartidos
│   ├── index.html         # Dashboard
│   ├── journal.html       # Trading Journal
│   ├── calendar.html      # Trading Calendar
│   ├── calculator.html    # Risk Calculator
│   ├── accounts.html      # Accounts
│   └── settings.html      # Settings
├── static/
│   ├── style.css          # Diseño oscuro, navegación, formulario y resultados
│   └── calculator.js      # Interacción, fetch y formato de presentación
├── tests/
│   ├── test_calculations.py # Pruebas unitarias de reglas y validaciones
│   └── test_routes.py       # Pruebas de integración Flask
├── pyproject.toml         # Configuración y dependencias
├── uv.lock                # Versiones de dependencias resueltas por UV
├── .python-version        # Versión de Python seleccionada
└── README.md
```

## Ejecutar localmente

Requisitos: UV instalado y Python 3.14 disponible. Desde la carpeta del proyecto:

```bash
uv sync --locked
uv run python app.py
```

UV utiliza el entorno `.venv` del proyecto; no necesitas activarlo manualmente ni usar pip. `uv sync --locked` instala las dependencias respetando `uv.lock`.

Abre <http://127.0.0.1:5000/>. Detén el servidor con `Ctrl+C`.

Si el puerto 5000 está ocupado, detén el servidor que lo utiliza o prueba temporalmente otro puerto:

```bash
uv run python -c 'from app import app; app.run(port=5001, debug=True)'
```

En ese caso abre <http://127.0.0.1:5001/>. El modo `debug=True` facilita el desarrollo local mostrando errores y recargando cambios; el servidor es para desarrollo local.

## Rutas disponibles

| Página | Ruta | Contenido futuro |
|---|---|---|
| Dashboard | `/` | Resumen de operaciones y estadísticas |
| Trading Journal | `/journal` | Historial de operaciones y notas |
| Trading Calendar | `/calendar` | Actividad de trading por fecha |
| Risk Calculator | `/calculator` | Calculadora funcional de riesgo y contratos |
| Accounts | `/accounts` | Información de cuentas de trading |
| Settings | `/settings` | Preferencias generales |

## Cómo funciona

Una **ruta Flask** conecta una dirección con una función Python. Cada función de `app.py` devuelve una plantilla mediante `render_template()`.

La **herencia de plantillas Jinja** permite reutilizar una estructura HTML. Todas las páginas empiezan con `{% extends "base.html" %}` y completan los bloques `titulo` y `contenido`. `base.html` contiene el encabezado, el menú, el enlace al CSS y el pie de página. Así, un cambio en el menú se aplica a todas las páginas sin duplicar HTML.

`url_for()` genera las direcciones a partir de los nombres de las funciones de Flask. El menú compara `request.endpoint` con cada destino para marcar la página activa mediante la clase `activo` y `aria-current="page"`. Esto también funciona al entrar directamente a una URL.

Los **archivos estáticos**, como el CSS, se sirven desde `static/`. Los anchos flexibles, el menú con salto de línea y las reglas `@media` permiten adaptar el diseño a pantallas pequeñas. Los enlaces tienen indicadores de foco para usar el teclado y un enlace inicial permite saltar al contenido.

`main.py` conserva el mensaje de ejemplo inicial. El punto de entrada de Flask es `app.py`.

## Verificación manual

Con el servidor encendido:

1. Recorre los seis enlaces del menú y comprueba sus títulos. Solo Risk Calculator tiene funcionalidad implementada.
2. Abre directamente cada ruta de la tabla; solo su enlace del menú debe aparecer activo.
3. Visita `/static/style.css` para comprobar que se sirve el CSS.
4. Prueba anchos de 320 px, 375 px y escritorio: el menú debe reorganizarse sin desplazar horizontalmente toda la página.
5. Recorre los enlaces con `Tab` y `Shift+Tab`, comprueba el foco visible y usa `Enter` para navegar. Comprueba también «Saltar al contenido».

Las respuestas HTTP y la estructura HTML pueden comprobarse automáticamente con el cliente de pruebas de Flask. La apariencia, el foco y la ausencia de desbordamiento visual deben revisarse en un navegador.


## Risk Calculator

Selecciona ES, MES, NQ o MNQ y completa presupuesto de riesgo en USD, distancia del stop en puntos y comisión por contrato (total de entrada y salida). El slippage está desactivado inicialmente; al activarlo debes indicar ticks enteros para toda la operación por contrato. No se duplican comisión ni slippage.

| Contrato | USD/punto | Tick mínimo (puntos) | USD/tick |
|---|---:|---:|---:|
| ES | 50.00 | 0.25 | 12.50 |
| MES | 5.00 | 0.25 | 1.25 |
| NQ | 20.00 | 0.25 | 5.00 |
| MNQ | 2.00 | 0.25 | 0.50 |

Python calcula con `Decimal`, que representa números decimales sin los errores de aproximación de los números binarios de punto flotante. Las funciones puras reciben datos y devuelven resultados, sin acceder al navegador ni a Flask; por eso se pueden probar de forma aislada.

- Riesgo de mercado = stop × valor por punto.
- Slippage = ticks × valor del tick, o cero si está desactivado.
- Riesgo por contrato = riesgo de mercado + comisión + slippage.
- Contratos = división entera hacia abajo del presupuesto entre riesgo por contrato.
- Riesgo total = contratos × riesgo por contrato.
- Restante = presupuesto − riesgo total.

Los cálculos no redondean importes. La interfaz aplica dos decimales al presentar dinero (mitades hacia arriba) y añade `$`. El total mostrado podría coincidir con el presupuesto por redondeo visual; la comparación interna utiliza los valores exactos.

JavaScript muestra u oculta los ticks y envía los datos; no calcula riesgo. Al editar parámetros oculta resultados, cancela la solicitud anterior e invalida su respuesta. Durante una solicitud se desactiva el botón; un identificador de versión impide que una respuesta antigua sustituya el cálculo actual.

### Límites técnicos y validación

- Importes y distancias: hasta **1 000 000 000** por campo, con hasta **6 decimales**. Riesgo y stop deben ser positivos; comisión puede ser cero. El stop debe ser múltiplo de 0.25 puntos.
- Slippage activado: entero entre 0 y 1 000 000 000 ticks. Desactivado: se ignora cualquier valor residual, incluso inválido.
- Campos numéricos de la API: cadenas de hasta 32 caracteres, punto decimal, sin separadores de miles, signos ni notación científica. Se permiten espacios exteriores. Se rechazan vacíos, `NaN` e infinitos.
- El checkbox es un booleano JSON, no una cadena. Si se omite, se interpreta como `false`.
- Cuerpo JSON: hasta 4096 bytes. Solo se aceptan objetos y los cuatro instrumentos del catálogo. Los multiplicadores se obtienen exclusivamente del servidor; los campos adicionales no alteran el cálculo.

Estos límites superan ampliamente los valores habituales de una operación y acotan el procesamiento. Con estas entradas y precisión interna de 50 dígitos, los productos y presupuestos se mantienen exactos. El menor riesgo por contrato es 0.50 USD, de modo que el máximo posible de contratos es 2 000 000 000.

### API JSON

`POST /api/calculate-risk`, con `Content-Type: application/json`:

```json
{
  "instrument": "MNQ",
  "risk_budget": "100",
  "stop_points": "20",
  "commission": "2.50",
  "include_slippage": true,
  "slippage_ticks": "2"
}
```

Una respuesta válida tiene `ok: true` y `result`. Los importes y el tick mínimo son cadenas decimales exactas sin símbolos ni notación científica; su cantidad de decimales puede variar. `contracts` es un entero y `warning` es texto o `null`. Ejemplo:

```json
{
  "ok": true,
  "result": {
    "instrument": "MNQ",
    "contracts": 2,
    "point_value": "2",
    "tick_size": "0.25",
    "tick_value": "0.50",
    "market_risk": "40",
    "commission": "2.50",
    "slippage_usd": "1.00",
    "risk_per_contract": "43.50",
    "total_risk": "87.00",
    "remaining_budget": "13.00",
    "warning": null
  }
}
```

- HTTP 200: cálculo válido; presupuesto insuficiente devuelve cero contratos y advertencia.
- HTTP 400: JSON inválido o validación fallida.
- HTTP 413: cuerpo excesivo.
- HTTP 415: contenido distinto de JSON.

Los errores tienen la forma `{"ok": false, "errors": {"stop_points": "El stop debe ser múltiplo de 0.25 puntos."}}`. No contienen trazas internas.

### Pruebas automatizadas

Sin dependencias adicionales, desde la raíz:

```bash
uv run python -m unittest discover -s tests -v
```

Se verifican los seis casos requeridos, presupuestos exactos e insuficientes, valores inválidos, límites técnicos, precisión, manipulación del catálogo, slippage y respuestas HTTP. Una matriz de 336 combinaciones comprueba que el riesgo total no excede el presupuesto, que no cabe otro contrato y que activar slippage nunca aumenta los contratos.

### Prueba manual de la calculadora

1. Ejecuta `uv run python app.py` y abre `/calculator`.
2. Selecciona MNQ, riesgo 100, stop 20 y comisión 2.50. Sin slippage: 2 contratos, riesgo por contrato $42.50, total $85.00 y restante $15.00.
3. Activa slippage e introduce 2 ticks: 2 contratos, $43.50 por contrato, $87.00 totales y $13.00 restantes.
4. Desactiva slippage: el campo se oculta y al recalcular vuelve al resultado del paso 2.
5. Prueba NQ, riesgo 200, stop 10 y comisión 5: cero contratos y advertencia de presupuesto insuficiente.
6. Prueba campos vacíos, stop 0.1 y valores negativos: deben impedir el cálculo o mostrar errores claros.
7. Modifica un campo tras calcular: el resultado anterior debe ocultarse. Con red lenta en las herramientas del navegador, edita durante una solicitud y vuelve a calcular; una respuesta antigua no debe reaparecer.
8. Revisa a 320 px, 375 px y escritorio, y navega con teclado. Comprueba foco visible, checkbox, mensajes y ausencia de desplazamiento horizontal.

El resultado es una estimación: el riesgo real puede variar por slippage, ejecución, comisiones, requisitos de margen y reglas de la cuenta. La calculadora no valida margen ni ejecuta operaciones. Requiere JavaScript habilitado. Las comprobaciones visuales y la simulación de red lenta deben realizarse en navegador.

## Fase 3A: persistencia y motor de operaciones

### Módulos y uso

- `database.py`: conexiones, claves foráneas, transacciones, esquema y comandos de inicialización/verificación.
- `trade_calculations.py`: validaciones numéricas y reproducción pura de una historia completa.
- `trade_service.py`: cuentas, operaciones, lotes de ejecuciones y reversiones explícitas, con persistencia atómica.
- `tests/test_database.py`, `tests/test_trade_calculations.py`, `tests/test_trade_service.py`: pruebas adicionales con bases temporales aisladas.

No se crea la base al importar los módulos ni al arrancar Flask. Desde la raíz, con el entorno existente:

```bash
uv run --no-sync python -m database init
uv run --no-sync python -m database verify
```

La ruta predeterminada es `instance/journal.sqlite3`, relativa al código del proyecto, no al directorio de ejecución. Ambos comandos aceptan `--path /ruta/journal.sqlite3`. `init` crea el directorio padre y es idempotente; nunca borra datos existentes. `verify` abre en modo de solo lectura, comprueba versión, presencia de tablas, `integrity_check` y `foreign_key_check`; una ruta inexistente falla sin crear archivos. No constituye una comparación exhaustiva del DDL contra alteraciones externas.

La base y los archivos SQLite auxiliares quedan excluidos de Git. No deben compartirse conexiones entre hilos. El servicio abre y cierra una conexión por llamada; todas activan `foreign_keys`. La inicialización del proyecto personal es una acción explícita del usuario; las pruebas no utilizan esa ruta.

Ejemplo de API Python tras inicializar:

```python
from trade_service import TradeService

service = TradeService()
account_id = service.create_account('Cuenta personal', 'personal', platform='Plataforma')
trade_id = service.create_trade(account_id, 'MNQ', 'long', strategy='Ejemplo')
service.add_executions(trade_id, [
    dict(execution_type='entry', quantity=1, price='20000',
         executed_at='2026-11-10T10:00:00-04:00', commission='1.25'),
    dict(execution_type='exit', quantity=1, price='20050',
         executed_at='2026-11-10T10:05:00-04:00', commission='1.25'),
])
result = service.get_trade(trade_id)
# result['summary']: gross_pnl=Decimal('100.00'), net_pnl=Decimal('97.50')
```

Otras operaciones: `list_accounts`, `set_account_active`, `list_trades(account_id)`, `update_trade_metadata`, `add_execution` y `record_reversal`. `update_trade_metadata` sustituye estrategia y notas; los parámetros omitidos quedan en NULL. Los identificadores devueltos por altas son enteros. Los resultados financieros son `Decimal`; una futura API deberá serializarlos como cadenas.

### Esquema versión 1

Tablas `STRICT` con SQLite ≥3.37; en versiones anteriores se mantienen tipos declarados y comprobaciones explícitas `typeof` para cantidades, secuencias, precios y costos. No se emplea `REAL`.

| Tabla | Columnas |
|---|---|
| `accounts` | `id INTEGER PRIMARY KEY`, `name TEXT`, `account_type TEXT`, `platform TEXT NULL`, `created_at TEXT`, `is_active INTEGER DEFAULT 1` |
| `trades` | `id INTEGER PRIMARY KEY`, `account_id INTEGER`, `symbol TEXT`, `direction TEXT`, `strategy TEXT NULL`, `notes TEXT NULL`, `created_at TEXT` |
| `executions` | `id INTEGER PRIMARY KEY`, `trade_id INTEGER`, `account_id INTEGER`, `executed_at TEXT`, `sequence INTEGER`, `execution_type TEXT`, `quantity INTEGER`, `price_ticks INTEGER`, `commission_microusd INTEGER DEFAULT 0`, `fees_microusd INTEGER DEFAULT 0`, `source TEXT`, `external_execution_id TEXT NULL`, `external_namespace TEXT NULL`, `created_at TEXT` |

Salvo los campos marcados NULL y las claves primarias, todos son `NOT NULL`. Restricciones:

- Tipos de cuenta: `funded`/`personal`; dirección: `long`/`short`; ejecución: `entry`/`exit`; origen: `manual`/`imported`; actividad: 0/1.
- Nombre no vacío, hasta 200 caracteres; plataforma opcional con el mismo límite. El servicio limita estrategia a 200 y notas a 10000 caracteres.
- Símbolos admitidos generados desde las claves de `CONTRACTS` durante la inicialización.
- FK `trades.account_id → accounts.id`, con `ON DELETE RESTRICT`.
- `UNIQUE(trades.id, trades.account_id)` y FK compuesta `executions(trade_id, account_id) → trades(id, account_id)`, también restrictiva.
- Cantidad y secuencia enteras de 1 a 1000000000; precio en ticks entero positivo; costos enteros de 0 a 1000000000000000.
- `UNIQUE(trade_id, sequence)`.
- ID externo y namespace ambos nulos o ambos no vacíos.
- Índice único parcial `(account_id, external_namespace, external_execution_id)` para IDs no nulos.
- Índices de consulta `(account_id, created_at, id)` en trades y `(trade_id, executed_at, sequence)` en executions.

Los nombres de cuenta no son únicos. No se almacenan estado, promedio ni P&L calculados. Las reglas que dependen de varias filas y la normalización de fechas pertenecen al servicio; el SQL directo puede eludirlas y no es una interfaz de escritura soportada. No hay triggers que implementen inmutabilidad ni auditoría.

### Exactitud, promedio y P&L

El catálogo `contracts.py` es la única fuente de tick y multiplicador. El servicio transforma precio / tick a un entero exacto. Costos se almacenan en millonésimas de USD, con seis decimales como máximo; se rechaza una escala mayor incluso si son ceros adicionales. Tampoco se admiten `float`, booleanos, NaN ni infinitos. Precios admiten hasta seis decimales y deben ser múltiplos del tick. Los importes y precios tienen límite de 1000000000, 32 dígitos significativos y entradas de texto de hasta 64 caracteres. Cantidad abierta máxima: 1000000000.

El motor utiliza exclusivamente `Decimal` para cálculos financieros, en contexto local de 50 dígitos y `ROUND_HALF_EVEN`. Para cantidad abierta Q y base de precio B (puntos × contratos), una entrada q a p produce B'=B+p×q y promedio B'/(Q+q). En una salida parcial se retira promedio×q de la base y se conserva el promedio del remanente. Una entrada posterior utiliza esa base remanente.

Bruto de salida: `(salida − promedio) × multiplicador × cantidad` para Long, con signo invertido para Short. Cada ejecución suma sus costos totales: no son costos por contrato ni costos round-trip. Neto acumulado = bruto realizado − comisiones incurridas − cargos incurridos. No se añade slippage estimado sobre precios ejecutados. Una operación abierta puede tener neto negativo sin salidas; su neto parcial no es el resultado final ni incluye valorización no realizada.

Los promedios periódicos se aproximan a 50 dígitos; no se cuantiza a centavos durante el cálculo. Se mantienen también los flujos de entrada y salida, exactos bajo los límites establecidos. Al cerrar, el bruto total se reconcilia con esos flujos y el último resultado realizado absorbe el residuo decimal. La base pasa a cero y el promedio a `None`. `realized_by_execution` expone el bruto de cada ejecución; las entradas aportan cero. Consumidores que sumen estos valores deben usar el mismo contexto de precisión, no el contexto Decimal predeterminado de 28 dígitos.

Las pruebas comparan promedios periódicos con precisión mayor y cierres parciales con un oráculo racional independiente (`Fraction`, solo en pruebas). Tolerancias: 1e-44 para el ejemplo de promedio y 1e-43 para la historia con entradas posteriores. El cierre se verifica exactamente contra los flujos; no se promete una cota universal de error intermedio para historias arbitrariamente extensas. Presentación futura: redondeo monetario `ROUND_HALF_UP`, separado de los cálculos.

Modificar retroactivamente ticks o multiplicadores de `contracts.py` reinterpretaría precios o alteraría el P&L histórico. Las especificaciones actuales deben permanecer estables; futuros cambios requieren versionar el catálogo y migrar explícitamente las referencias históricas.

### Fechas, secuencias y estados

El servicio exige timestamps con zona horaria y los normaliza a UTC con seis decimales: `YYYY-MM-DDTHH:MM:SS.ffffffZ`. `created_at` indica registro; `executed_at`, ejecución económica. No se supone la zona local para fechas sin offset.

Cada alta asigna `max(sequence)+1` dentro de `BEGIN IMMEDIATE`. En lotes se asignan secuencias según el orden de la lista. Nunca se renumeran filas existentes. El procesamiento y las consultas usan siempre `(executed_at, sequence)`, independientemente de IDs o del orden físico en SQLite.

Una inserción histórica obtiene una secuencia mayor, pero se ubica cronológicamente por su timestamp. Si empata con filas existentes, queda después de ellas; esta API no permite insertar delante de una ejecución existente con igual timestamp. Un rollback no reserva números: pueden reutilizarse secuencias de filas que nunca se confirmaron. La futura importación deberá proporcionar el orden correcto del lote para timestamps iguales.

Estados derivados: `pending` sin ejecuciones; `open` con posición; `closed` al llegar a cero después de abrir. Salidas sin posición, sobrecierres y cualquier ejecución posterior al cierre son inválidos. El comando de alta rechaza también inserciones históricas en operaciones ya cerradas.

Las cuentas archivadas conservan lectura del historial, pero bloquean nuevas operaciones, ejecuciones y cambios de notas/estrategia. Reactivar es la excepción administrativa permitida. No se implementan borrado de cuentas ni cambios de dirección, cuenta o símbolo de una operación.

### Atomicidad, errores y evolución

Cada comando de escritura toma `BEGIN IMMEDIATE` antes de leer y validar. Los lotes se reproducen completos antes de insertar. Cualquier fallo revierte toda la transacción, incluido un conflicto externo que ocurra después de insertar la primera fila. Timeout SQLite: cinco segundos; no hay reintentos automáticos. Dos escritores no pueden confirmar cierres basados en la misma posición previa.

Errores: `TradeValidationError`, `NotFoundError`, `ArchivedAccountError`, `ConflictError`, `PersistenceError` y `DatabaseError`. Los errores SQLite originales se conservan como causa para diagnóstico. Un ID externo repetido genera conflicto, incluso si el contenido coincide; no se ignora automáticamente.

`PRAGMA user_version=1` identifica el esquema. Se rechazan versiones desconocidas y bases sin versión que ya contienen tablas. Futuras migraciones deberán ser incrementales, transaccionales y precedidas por una copia de seguridad; `CREATE TABLE IF NOT EXISTS` no sustituye una migración. No hay migraciones de versiones anteriores porque esta es la primera persistencia.

**Fase 3B — correcciones:** `_revalidate` reproduce una historia candidata completa y no prohíbe por sí mismo corregir una operación anteriormente cerrada. La prohibición actual reside en el comando de alta. Un futuro comando deberá cargar la historia bajo transacción, conservar las secuencias de filas sin cambios, construir la historia corregida, validarla completamente y guardar cambios más auditoría de forma atómica. Si cambia el orden de empates, deberá hacerlo explícitamente y auditarlo; no reutilizará silenciosamente el alta normal. Esta fase no expone edición/eliminación de ejecuciones.

**Reversiones explícitas:** `record_reversal(trade_id, closing_execution, opening_execution)` recibe una salida que cierre toda la posición y una entrada contraria con el mismo timestamp. Crea dos operaciones independientes dentro de una transacción; si la segunda parte falla, revierte también el cierre. El llamador proporciona cantidades y costos ya repartidos. No reconstruye órdenes ni divide automáticamente comisiones.

**Fase 3C — procedencia de importaciones:** añadir tabla `external_executions` con cuenta, namespace, ID único, cantidad, costos originales y metadatos de la fuente. Cada original podrá relacionarse con varias filas internas mediante una tabla de asignaciones; la deduplicación residirá en la original. Se migrarán los IDs actualmente presentes en executions a ese modelo, sin copiar el mismo ID a ambas partes ni añadir sufijos artificiales. El namespace identifica proveedor y ámbito real de unicidad, no el nombre del archivo ni el lote de importación.

Para dividir costos: repartir proporcionalmente por contratos en unidades microusd, redondear la primera parte con una regla explícita y asignar el resto exacto a la última. Validar suma de cantidades y de costos contra la ejecución original y confirmar original/asignaciones/operaciones en una transacción. Ejemplo: venta de 5 que cierra Long 3 y abre Short 2; comisión original 1 microusd → primera parte 1, segunda 0 con mitades hacia arriba. Comisión y cargos se reparten por separado. La relación y el reparto automático quedan pendientes de Fase 3C.

### Verificación de Fase 3A

```bash
uv run --no-sync python -W error::ResourceWarning -m unittest discover -s tests -v
```

Las pruebas crean bases reales mediante `TemporaryDirectory`, incluyendo verificaciones CLI y dos conexiones concurrentes. Cubren ejemplos Long/Short, entradas múltiples, cierres parciales, costos, precisión, timestamps empatados e históricos, cuentas archivadas, aislamiento, restricciones SQL, deduplicación, rollback, reversiones, persistencia y regresión completa de calculadora/rutas. No inicializan ni modifican la base personal. No se añadieron dependencias, formularios, importadores ni endpoints.
