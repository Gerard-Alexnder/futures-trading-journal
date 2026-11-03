# Futures Trading Journal

Aplicación web personal para organizar operaciones de futuros y, en fases posteriores, gestionar riesgo y analizar estadísticas de trading.

## Estado actual: Fase 2

Servidor Flask con navegación compartida, diseño oscuro adaptable y calculadora de riesgo funcional en `/calculator`. Las otras cinco páginas siguen siendo provisionales. No hay almacenamiento, ejecución de órdenes, conexión a brokers ni autenticación.

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
