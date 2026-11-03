# Futures Trading Journal

Aplicación web personal para organizar operaciones de futuros y, en fases posteriores, gestionar riesgo y analizar estadísticas de trading.

## Estado actual: Fase 1B

Servidor Flask con seis páginas provisionales, navegación compartida y diseño oscuro adaptable a escritorio y móvil. Cada página describe funcionalidades futuras. Todavía no hay almacenamiento, formularios funcionales ni cálculos financieros.

## Tecnologías

- Python 3.14 o superior, según `pyproject.toml`.
- Flask y su motor de plantillas Jinja.
- HTML y CSS, sin frameworks frontend, JavaScript ni recursos externos.
- UV para gestionar dependencias y ejecutar Python.

## Estructura

```text
futures-trading-journal/
├── app.py                 # Servidor Flask y seis rutas
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
│   └── style.css          # Diseño oscuro, navegación y estilos responsive
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
| Risk Calculator | `/calculator` | Planificación de riesgo y tamaño de posición |
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

1. Recorre los seis enlaces del menú y comprueba el título y el texto provisional de cada página.
2. Abre directamente cada ruta de la tabla; solo su enlace del menú debe aparecer activo.
3. Visita `/static/style.css` para comprobar que se sirve el CSS.
4. Prueba anchos de 320 px, 375 px y escritorio: el menú debe reorganizarse sin desplazar horizontalmente toda la página.
5. Recorre los enlaces con `Tab` y `Shift+Tab`, comprueba el foco visible y usa `Enter` para navegar. Comprueba también «Saltar al contenido».

Las respuestas HTTP y la estructura HTML pueden comprobarse automáticamente con el cliente de pruebas de Flask. La apariencia, el foco y la ausencia de desbordamiento visual deben revisarse en un navegador.
