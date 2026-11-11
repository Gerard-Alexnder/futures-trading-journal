# Futures Trading Journal

Aplicación web personal para organizar operaciones de futuros y, en fases posteriores, gestionar riesgo y analizar estadísticas de trading.

## Estado actual: Fase 3B.3

Servidor Flask con navegación compartida, diseño oscuro adaptable y calculadora de riesgo funcional en `/calculator`. Accounts permite gestionar cuentas y `/journal/new` registra operaciones manuales. `/journal/<id>` muestra el detalle y permite continuar posiciones abiertas mediante entradas, salidas parciales y cierre completo. El listado de Journal, Dashboard, Calendar y Settings siguen siendo provisionales. No hay envío de órdenes, conexión a brokers ni autenticación.

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

## Fase 3B.1: Accounts y esquema v2

Accounts ahora permite crear, listar, seleccionar, archivar y reactivar cuentas. El formulario mantiene nombre/plataforma ante errores y escapa contenido. El archivo requiere abrir la confirmación y marcar la casilla. Las cuentas archivadas conservan todos sus datos. La selección es una preferencia de sesión, distinta de `is_active`; se invalida al archivar desde esta sesión o al volver a Accounts si otra sesión archivó la cuenta. El enlace Journal sigue llevando a una página provisional, sin historial filtrado.

### Configuración web

Define `SECRET_KEY` mediante una variable de entorno o el gestor de secretos del despliegue. Utiliza un valor aleatorio persistente de al menos 32 bytes. Puedes generar uno localmente con `uv run --no-sync python -c 'import secrets; print(secrets.token_hex(32))'` y guardarlo de forma privada; no lo publiques ni lo añadas a Git. No hay carga automática de `.env` ni claves predeterminadas o efímeras. Cambiar la clave invalida las sesiones anteriores.

Sin `SECRET_KEY`, Accounts responde 503 con instrucciones; las páginas existentes y la calculadora siguen disponibles. Las cookies de sesión tienen `HttpOnly` y `SameSite=Lax`. Define `SESSION_COOKIE_SECURE=true` para HTTPS (en HTTP local debe permanecer desactivado). No se establece duración permanente: la cookie dura la sesión del navegador, sujeta a la restauración de sesiones propia del navegador. La sesión contiene token CSRF, ID de cuenta seleccionada y mensajes de interfaz; no importes financieros. Las cookies firmadas no son cifradas.

`JOURNAL_DATABASE` permite configurar una ruta diferente; por defecto se usa `instance/journal.sqlite3`. No se crea ni migra la base al arrancar Flask ni al recibir HTTP. Las conexiones ordinarias requieren que el archivo exista y que el esquema sea v2. Si falta o es v1, Accounts muestra el comando administrativo requerido. Usa `--path` en los comandos si configuraste una ruta distinta.

Cada POST nuevo valida CSRF asociado a sesión desde campo oculto o cabecera `X-CSRF-Token`; los tokens no aparecen en URLs. La API `/api/calculate-risk` conserva su comportamiento, porque no persiste datos. Los formularios limitan su cuerpo a 16 KiB. Se distinguen validación (422), inexistentes (404), cuenta archivada/conflicto (409), CSRF (403), tamaño (413) y configuración/persistencia no disponible (503), sin mostrar detalles internos SQLite.

### Administración de la base

Para una **base nueva**:

```bash
uv run --no-sync python -m database init
uv run --no-sync python -m database verify
```

Para una **base existente v1**, detener primero la aplicación y ejecutar explícitamente:

```bash
uv run --no-sync python -m database migrate
uv run --no-sync python -m database verify
```

Estos comandos administrativos no se ejecutan automáticamente. Durante el desarrollo y las pruebas de esta fase no se migró ni modificó la base personal.

`initialize()` crea v2 y verifica v2 existente; rechaza v1 sin migrarla. `verify()` verifica v2 por defecto; el verificador interno admite v1 explícitamente para respaldos/migraciones. `migrate()` admite v1→v2 o v2 sin cambios; rechaza ausencia, versión 0 y versiones desconocidas/futuras. El comando `verify` abre solo lectura.

La migración obtiene una reserva `BEGIN IMMEDIATE`, valida el origen y realiza un respaldo consistente mediante la API SQLite desde una segunda conexión lectora. Se mantiene bloqueada la escritura hasta terminar, para que el respaldo corresponda al estado previo. El respaldo queda junto a la base con nombre `journal.sqlite3.<UTC>.<UUID>.bak` y permisos iniciales 0600. La CLI informa su ruta y la versión final. Repetir sobre v2 no crea otro respaldo. En caso de fallo después del respaldo, los cambios se revierten y el respaldo permanece disponible en ese directorio. Respalda también tu configuración por separado; las copias SQLite contienen datos personales. Para restaurar, detener todos los procesos y usar la copia consistente, evitando archivos WAL/SHM de otra versión. No hay restauración automática ni migración inversa.

La versión 2 conserva las tres tablas financieras, IDs, timestamps, restricciones e índices, y añade:

- `trades.revision INTEGER NOT NULL DEFAULT 0 CHECK(typeof(revision)='integer' AND revision >= 0)` mediante `ALTER TABLE ADD COLUMN`, sin reconstrucción de trades. Es infraestructura reservada; el control optimista y actualización de revisiones de operaciones se implementarán en fases posteriores.
- `write_requests`: `request_key TEXT PRIMARY KEY NOT NULL` (16–128 caracteres), `action TEXT NOT NULL` (1–100), `payload_hash TEXT NOT NULL` (64), `result_json TEXT NOT NULL` y `created_at TEXT NOT NULL`. Índice por `created_at`; tabla STRICT donde está disponible.

El verificador comprueba columnas requeridas, índices principales, presencia de FK, versión e integridad. No es un certificador de equivalencia de todo DDL arbitrariamente modificado; las escrituras SQL externas no son una interfaz soportada. Los precios y costos siguen siendo enteros y el motor financiero no cambió.

### Idempotencia y servicios

`idempotency.execute_once(connection, request_key, action, payload, operation)` se utiliza dentro de la transacción de negocio. El payload debe estar normalizado; se almacena SHA-256 del JSON canónico, no el payload. La operación devuelve únicamente IDs/estados no sensibles. Claves manuales aleatorias (16–128 caracteres ASCII permitidos) son independientes de identificadores externos de ejecuciones. No usar números float ni secretos en payloads futuros.

Misma clave/acción/contenido devuelve el resultado confirmado sin volver a escribir; contenido o acción distintos generan conflicto. Las peticiones concurrentes se serializan con `BEGIN IMMEDIATE`. Si falla el efecto o su registro idempotente, el llamador propaga el error y revierte ambos. No hay limpieza automática de claves; eliminarlas podría permitir repeticiones antiguas. Una repetición confirma el resultado original, no fuerza de nuevo el estado actual si después hubo otra acción legítima.

`TradeService.create_account(..., request_id=None)` y `set_account_active(..., request_id=None)` aceptan la clave opcional para compatibilidad con consumidores Python de Fase 3A. La web la exige siempre. `get_account(account_id, require_active=False)` expone consulta individual y validación de selección. Crear normaliza nombre y plataforma con el servicio; la web transforma plataforma vacía en NULL.

Seleccionar no usa `write_requests`: solo asigna un ID a la sesión después de validar que la cuenta exista y esté habilitada. Repetir esa asignación tiene el mismo resultado y no crea filas. Toda selección requiere CSRF. Crear/archivar/reactivar usan idempotencia y redirección 303; no dependen de JavaScript para evitar duplicación.

Rutas nuevas/activadas: GET/POST `/accounts` y POST `/accounts/<id>/select`, `/archive`, `/reactivate`. No hay eliminación ni edición de datos generales. `account_routes.py` no contiene SQL de negocio; `web_support.py` configura sesiones y CSRF.

### Pruebas y límites

```bash
uv run --no-sync python -W error::ResourceWarning -m unittest discover -s tests -v
git diff --check
```

Las pruebas usan exclusivamente bases temporales. `tests/fixtures/schema_v1.sql` conserva el esquema original de Fase 3A, sin datos personales, para probar migraciones reales. Los tests previos de rutas ahora configuran SECRET_KEY de prueba y base temporal; los tests previos de base esperan v2 y conservan verificaciones de rechazo de versiones futuras. No se eliminaron pruebas.

El diseño CSS contempla móvil y escritorio, pero las pruebas Flask no sustituyen una revisión visual/manual de navegador. La aplicación sigue siendo personal y sin autenticación; no debe exponerse públicamente como si CSRF aportara control de acceso. Siguen pendientes formularios de operaciones, historial funcional, correcciones auditables, importaciones, control de revisión en escrituras de operaciones y reglas avanzadas de cuentas fondeadas. La descripción histórica de esquema v1 anterior se conserva como referencia; v2 es la versión actual requerida.

## Fase 3B.2: registro manual inicial

`/journal/new` (New Trade) registra operaciones en cuentas activas mediante dos modalidades:

- **Progresiva:** exactamente una entrada inicial; queda `open`. Añadir ejecuciones después del guardado mediante interfaz corresponde a 3B.3.
- **Histórica:** tabla de 1–200 ejecuciones, con entradas y salidas. Puede quedar `open` o `closed`; no admite un lote vacío, solo salidas, sobrecierres ni actividad posterior al cierre.

El Journal provisional incluye el enlace al formulario. Tras guardar se muestra una confirmación con el ID; no se añade un detalle completo ni un historial funcional. El esquema sigue en **v2**, sin migraciones nuevas. El motor financiero, catálogo y calculadora no cambian.

### Borrador y fechas

Selecciona cuenta, instrumento, dirección, estrategia opcional (200 caracteres) y notas opcionales (10000). Cada fila contiene tipo, fecha/hora, cantidad entera positiva, precio que respete el tick, comisión total y cargos totales de esa ejecución. Costos admiten hasta seis decimales; no se redondean al persistir. Todos los límites monetarios/técnicos del motor de Fase 3A siguen aplicando.

La tabla permite agregar, eliminar y mover filas con ↑/↓. Estas acciones afectan solo al borrador. El cambio de histórica a progresiva solicita confirmación si descarta filas o transforma una salida en entrada. Las filas conservan su identidad `row_id` al editar o moverlas; la secuencia persistida no la elige directamente el cliente.

El formulario muestra explícitamente un **offset fijo**, inicialmente UTC−04:00 (Santo Domingo), editable incluyendo offsets de media hora mediante «Otro offset». No utiliza silenciosamente la zona del navegador ni transforma `datetime-local` mediante `Date`. Añade el offset seleccionado al texto de cada fila; el servidor valida y normaliza a UTC con seis decimales de segundo. Se admiten hasta seis decimales de segundo en la API y no se truncan fracciones superiores.

El offset es común a las filas del formulario. Para datos que crucen cambios de horario estacional, convierte previamente cada hora a UTC y selecciona UTC+00:00. La API acepta offsets diferentes por fila. El servidor rechaza fechas sin zona, fechas imposibles y offsets fuera de ±14:00. No incorpora reglas IANA/DST ni dependencias de fechas.

La secuencia 1…N se asigna por orden de filas recibidas. El motor ordena por `(executed_at UTC, sequence)`: las fechas distintas se ordenan cronológicamente y los empates conservan exactamente el orden explícito. El preview muestra ese orden, junto a cantidades, precios y costos. Guardado y preview comparten la normalización. No se aceptan campos `sequence`, `source` ni identificadores externos en un borrador manual.

### Servicios y API

Servicios nuevos en `TradeService`:

```text
preview_trade(account_id, symbol, direction, executions,
              strategy=None, notes=None, *, mode='historical')

create_trade_with_executions(account_id, symbol, direction, executions,
                            strategy=None, notes=None, *, request_id,
                            mode='historical')
```

`preview_trade` verifica cuenta activa y ejecuta el motor existente sobre los datos normalizados. Usa `PRAGMA query_only=ON`, no crea operaciones, ejecuciones ni claves idempotentes. Devuelve `summary` y `executions` en el orden efectivo. Para identificar la fila que invalida una historia, reproduce prefijos con el mismo motor; el costo es cuadrático y está acotado a 200 filas.

`create_trade_with_executions` abre una única transacción `BEGIN IMMEDIATE`, verifica la cuenta, resuelve la idempotencia y crea operación + ejecuciones + registro de solicitud conjuntamente. Revalida la historia con el motor, también después de insertar; cualquier fallo revierte todo. Devuelve únicamente `{'trade_id': ...}`. No llama a dos comandos públicos que confirmen transacciones separadas.

Endpoints:

- GET `/journal/new`: formulario con cuentas activas y selección de sesión como preferencia inicial.
- POST `/api/journal/preview`: previsualización sin persistencia.
- POST `/api/journal`: creación atómica e idempotente.

Ambos POST requieren sesión configurada, JSON y cabecera `X-CSRF-Token`. El preview también utiliza CSRF por coherencia con la política de sesión. Límite exclusivo de estas solicitudes: 512 KiB; Accounts conserva 16 KiB y la calculadora 4096 bytes.

Ejemplo de cuerpo para preview:

```json
{
  "account_id": 1,
  "symbol": "MNQ",
  "direction": "long",
  "strategy": "Reversal",
  "notes": null,
  "mode": "progressive",
  "executions": [
    {
      "row_id": "entry-1",
      "execution_type": "entry",
      "executed_at": "2026-11-10T10:00:00-04:00",
      "quantity": "2",
      "price": "20000",
      "commission": "2.50",
      "fees": "0"
    }
  ]
}
```

Creación utiliza el mismo cuerpo más `request_id` aleatorio de 16–128 caracteres admitidos. `account_id` es entero; precios, cantidades y costos de entrada son cadenas. Los importes Decimal de respuesta son cadenas; cantidades resultantes, secuencias y representaciones persistidas en ticks/micro-USD siguen siendo enteros. `average_price` es null al cierre.

Respuestas de éxito: HTTP 200 con `{ok: true, result: ...}`, tanto en creación como en repetición idempotente. Errores: 400 formato/campos requeridos, 403 CSRF, 404 cuenta inexistente, 409 cuenta archivada o conflicto, 413 tamaño, 422 validación y 503 configuración/persistencia. Forma de errores: `{ok: false, errors: {fields: {...}, rows: {row_id: {field: mensaje}}}}`. `history` identifica una incompatibilidad financiera de la fila con las anteriores. No se muestran SQL ni trazas internas.

### Idempotencia, asincronía y resumen

La huella incluye cuenta, símbolo, dirección, estrategia, notas, modalidad y todas las ejecuciones normalizadas con su secuencia. Excluye `row_id` (identidad visual) y fechas de registro generadas. Valores equivalentes como `20000`/`20000.00`, cantidades `2`/`02` y offsets equivalentes producen el mismo contenido normalizado. Cambiar el orden del array cambia sus secuencias y se considera contenido distinto, incluso cuando sus timestamps distintos permitirían el mismo orden cronológico.

La cuenta se comprueba antes de devolver un resultado idempotente: archivar después de guardar bloquea el reintento hasta reactivar. Una clave no omite esta validación. La aplicación sigue siendo personal, sin autenticación; no existe autorización multiusuario.

El navegador invalida el preview al editar o reordenar, cancela solicitudes anteriores y descarta respuestas obsoletas. Guardar requiere confirmar el resumen. Durante guardado se bloquea el borrador; ante pérdida de respuesta o fallo 5xx, se conserva el mismo contenido y clave para reintentar sin duplicados. La clave solo se guarda en memoria: **no recargues ni cierres la página cuando el resultado sea incierto**. La advertencia estándar `beforeunload` compara todos los campos y las filas con el estado inicial: no aparece al abrir el formulario ni al deshacer todos los cambios, protege también cambios aislados en notas/cuenta/offset y se desactiva tras guardar correctamente. La presentación del diálogo depende del navegador y normalmente requiere interacción previa; no garantiza protección al terminar el proceso o cerrar aplicaciones móviles. No se persisten borradores en localStorage ni en SQLite; una recarga puede perderlos.

JavaScript solo presenta resultados del servidor y formatea dinero con redondeo visual; no calcula P&L. El resumen distingue bruto realizado, costos incurridos y neto acumulado. No incluye ganancias no realizadas ni descuento adicional de slippage. El caso MNQ de aceptación produce netos −2.50, 97.50 y 257.50 al previsualizar uno, dos y tres fills, respectivamente; el histórico completo queda cerrado con bruto 260.

### Verificación y alcance

```bash
uv run --no-sync python -W error::ResourceWarning -m unittest discover -s tests -v
git diff --check
```

Las pruebas adicionales de `test_trade_drafts.py` y `test_journal_routes.py` utilizan bases temporales: preview sin cambios en el archivo, progresiva/histórica, equivalencia preview/persistencia, Long/Short, múltiples entradas, costos, offsets/empates, campos inválidos, cuentas, límites, rollback en mitad del lote y al registrar la clave, concurrencia, CSRF y regresiones. No se modifican ni relajan las pruebas anteriores.

La interfaz requiere JavaScript; en móvil la tabla de creación se presenta como tarjetas de campos. No se implementan edición, historial general, auditoría, importaciones ni reglas de cuentas fondeadas. La continuación de operaciones guardadas se describe en la Fase 3B.3.

Validación optativa de JavaScript en Firefox, con un servidor WebDriver ya disponible (no instala dependencias):

```bash
PYTHONPATH=. WEBDRIVER_URL=http://127.0.0.1:4444 uv run --no-sync python tests/browser_journal_validation.py
```

El script usa una base temporal y una clave efímera de prueba. Comprueba la cancelación del evento `beforeunload` para distintos campos, cambios revertidos y guardado confirmado; offsets fraccionarios, errores, respuestas tardías y pérdida de respuesta de guardado. Las capturas de escritorio y ancho móvil se guardan en `/tmp/journal-desktop.png` y `/tmp/journal-mobile.png`. No prueba terminación forzada del navegador ni garantiza que el navegador muestre su diálogo nativo en todas las circunstancias.

## Fase 3B.3 — Gestión de posiciones y detalle

Después de crear una operación, el enlace **Ver operación y gestionar posición** abre `/journal/<id>`. También se puede acceder directamente por ID; el listado general sigue fuera de alcance. El detalle muestra cuenta, instrumento, dirección, estrategia, notas, revisión, resumen financiero e historia completa en orden efectivo. Operaciones cerradas y cuentas archivadas son de solo lectura. Una operación pending admite una primera entrada válida.

La interfaz prepara una ejecución por vez: entrada adicional, salida parcial o cierre completo. El cierre completo toma la cantidad abierta mostrada, pero el servidor vuelve a validar cantidad, revisión e historia. El preview compara estado actual y proyectado; guardar exige confirmación. Se actualizan resumen e historial después del recibo confirmado. No hay cálculos financieros en JavaScript. Los importes mostrados son cadenas Decimal del servidor, sin redondeos monetarios intermedios.

### Servicios y protocolo

```python
service.preview_execution_batch(trade_id, executions, expected_revision=revision)
service.append_execution_batch(trade_id, executions,
                               expected_revision=revision, request_id=request_id)
```

Ambos servicios aceptan entre 1 y 200 filas con el mismo contrato de normalización de 3B.2: `row_id`, `execution_type`, `executed_at` con offset, y cadenas para `quantity`, `price`, `commission`, `fees`. No aceptan secuencias del cliente. La operación determina cuenta, instrumento y dirección. La interfaz envía una fila, mientras el servicio/API admite lotes atómicos.

- GET `/journal/<int:trade_id>`: HTML; con `Accept: application/json`, devuelve el mismo snapshot para actualizar el detalle.
- POST `/api/journal/<int:trade_id>/executions/preview`: `expected_revision` entero y `executions`; devuelve `current`, `projected`, `revision`, `executions` combinadas, `new_executions`, `retroactive` y `warning`.
- POST `/api/journal/<int:trade_id>/executions`: mismo cuerpo más `request_id`; devuelve el recibo estable `{trade_id, execution_ids, revision}`.

Ambos POST requieren CSRF y limitan el cuerpo a 512 KiB. Conservan 400/403/404/409/413/422/503; el error JSON incluye `code` con `stale_revision`, `trade_closed`, `account_inactive` o `idempotency_conflict` para esos conflictos, además de `errors.fields` y `errors.rows`. Un error de historia identifica la nueva fila que falla; si una inserción invalida un fill existente, identifica ese fill y señala las filas del lote para revisar. No se revelan trazas ni SQL de fallos de persistencia.

### Snapshot, revisión e idempotencia

Detalle y preview abren una transacción `BEGIN` con `PRAGMA query_only=ON`; operación, revisión, cuenta e historial pertenecen al mismo snapshot establecido por la primera lectura. No usan `BEGIN IMMEDIATE`, no registran solicitudes y no escriben estados ni revisiones. Las pruebas intercalan un escritor real en otra conexión con WAL habilitado **solo en la base temporal**. No se cambia el modo de journal del proyecto. En el modo rollback-journal habitual, una lectura larga puede retrasar el commit de un escritor hasta que termine.

Las escrituras utilizan `BEGIN IMMEDIATE`. Se obtiene la operación y se exige cuenta activa; se normalizan las filas con su instrumento, se construye el contenido canónico y se consulta `write_requests`. La normalización específica del instrumento ocurre dentro de esa transacción para usar la operación leída allí. Solo una solicitud nueva comprueba revisión/estado, reproduce toda la historia candidata, inserta fills, incrementa revisión con un UPDATE condicionado y registra el recibo, todo dentro de una transacción.

El contenido canónico incluye ID de operación, revisión esperada, tipo, timestamps UTC, cantidades, ticks, micro-USD y **orden relativo del lote**; excluye `row_id` visual y fechas de registro. Las secuencias absolutas se asignan únicamente a solicitudes nuevas. Así, una respuesta perdida se puede reintentar incluso después de cerrar la operación: se devuelve exactamente el recibo anterior, sin insertar, recalcular secuencias ni incrementar revisión. La misma clave con contenido distinto produce 409. Si la cuenta fue archivada después del commit, el reintento se bloquea hasta reactivarla.

`add_execution`, `add_executions`, `update_trade_metadata`, el cierre de la operación original de `record_reversal` y `append_execution_batch` incrementan la revisión una vez por modificación confirmada, incluso cuando hay varias filas. El rollback revierte también ese incremento. Las operaciones recién creadas por 3B.2 y la nueva operación de una reversión empiezan en revisión 0; la operación original de la reversión incrementa una vez.

Ante `stale_revision`, la pantalla conserva el borrador y obliga a **Actualizar posición**, obtener otro preview y confirmar nuevamente. No reenvía automáticamente con otra revisión. Editar invalida el preview y las respuestas tardías se descartan. Ante un resultado incierto, bloquea los campos y mantiene contenido/clave para repetir el mismo guardado. Los borradores y claves están solo en memoria; `beforeunload` advierte de cambios, pero recargar puede perderlos y no hay recuperación persistente.

### Fechas e inserciones retroactivas

El offset se muestra y es editable; inicialmente es −04:00. No se infiere silenciosamente UTC ni se aplica horario estacional. Backend normaliza a UTC con microsegundos. Se aceptan inserciones históricas en pending/open únicamente si la historia combinada completa es válida. Se asignan secuencias `max(sequence existente) + 1...N`, sin modificar filas ni secuencias anteriores. El orden financiero es `(executed_at UTC, sequence)`; ante empate las nuevas filas siguen a las existentes y mantienen su orden de entrada.

Si una fila precede temporalmente al último fill existente, el preview advierte explícitamente que puede recalcular promedios y P&L de salidas posteriores. La interfaz exige preview y confirmación también en ese caso. La API vuelve a validar al guardar, pero no almacena un comprobante de preview: los clientes del servicio/API son responsables de presentar y confirmar la previsualización.

### Caso financiero y validación

MNQ Long, sin otros cargos, utilizando el motor existente:

| Paso | Abiertos | Promedio | Bruto USD | Costos acumulados USD | Neto USD |
|---|---:|---:|---:|---:|---:|
| Entrada 2 @ 20000, comisión 2.50 | 2 | 20000 | 0 | 2.50 | -2.50 |
| Entrada 1 @ 20030, comisión 1.25 | 3 | 20010 | 0 | 3.75 | -3.75 |
| Salida 1 @ 20050, comisión 1.25 | 2 | 20010 | 80 | 5.00 | 75.00 |
| Salida 2 @ 20080, comisión 2.50 | 0 | null | 360 | 7.50 | 352.50 |

El último estado es `closed`. El promedio ponderado y el P&L se calculan exclusivamente con el motor Decimal existente; precios persistidos en ticks y costos en micro-USD. Los costos se descuentan una sola vez. `test_execution_batches.py` y `test_position_routes.py` cubren este caso, Long/Short, snapshots concurrentes, revisiones, reintentos tras cierre/archivo, rollback, retroactivos, empates, errores, CSRF y límites. No se relajan las pruebas anteriores.

```bash
uv run --no-sync python -W error::ResourceWarning -m unittest discover -s tests -v
node --check static/journal_detail.js
node --check static/journal.js
git diff --check
PYTHONPATH=. WEBDRIVER_URL=http://127.0.0.1:4444 uv run --no-sync python tests/browser_position_validation.py
```

La prueba optativa de Firefox utiliza un WebDriver existente, una base temporal y un secreto efímero; no instala dependencias. Verifica acciones de posición, offsets, preservación de borradores, conflictos, respuesta perdida tras cierre, solo lectura y anchos de escritorio/móvil. Guarda capturas `/tmp/position-*.png` para inspección. No equivale a una prueba en un dispositivo móvil físico.

Limitaciones: sin autenticación multiusuario, historial general, edición/eliminación de fills, correcciones auditables, importaciones, estadísticas ni precios de mercado. La historia se reproduce completa y se envía completa al detalle; los 200 fills limitan el lote, no la historia acumulada. La localización de errores por prefijos puede tener costo cuadrático sobre una historia larga. Se mantiene SQLite v2 sin migraciones y no se modifica el catálogo ni el motor financiero.
