# Futures Trading Journal

Aplicación web personal para organizar operaciones de futuros y, en fases posteriores, gestionar riesgo y analizar estadísticas de trading.

## Estado actual: Fase 1A

Esta fase incluye un servidor Flask y una página de bienvenida con diseño oscuro y adaptable a escritorio y móvil. El Dashboard es una sección provisional: todavía no muestra estadísticas ni registra operaciones.

No se han implementado base de datos, navegación, journal, calculadora ni calendario.

## Tecnologías

- Python 3.14 o superior, según `pyproject.toml`.
- Flask, para servir la página web.
- HTML y CSS, sin frameworks frontend ni recursos externos.
- UV, para gestionar dependencias y ejecutar Python.

## Estructura

```text
futures-trading-journal/
├── app.py                 # Servidor Flask y ruta principal
├── main.py                # Archivo inicial de ejemplo; no lo utiliza Flask
├── templates/
│   └── index.html         # Contenido de la página de inicio
├── static/
│   └── style.css          # Colores, tipografía y diseño responsive
├── pyproject.toml         # Configuración y dependencias del proyecto
├── uv.lock                # Versiones de dependencias resueltas por UV
├── .python-version        # Versión de Python seleccionada
└── README.md              # Documentación del proyecto
```

## Ejecutar localmente

Requisitos: tener UV instalado y Python 3.14 disponible.

Desde la carpeta del proyecto:

```bash
uv sync --locked
uv run python app.py
```

`uv sync --locked` instala las dependencias definidas en el proyecto respetando `uv.lock`. UV utiliza el entorno `.venv` del proyecto; no necesitas activarlo manualmente ni usar pip.

Abre <http://127.0.0.1:5000/> en el navegador. Para detener el servidor, presiona `Ctrl+C` en la terminal.

El servidor actual utiliza `debug=True`, útil durante el desarrollo local porque muestra errores y recarga los cambios en Python. Este servidor es para desarrollo local.

## Cómo funciona

Una **ruta** conecta una dirección web con una función Python. En `app.py`, la ruta `/` llama a `inicio()`, que devuelve la página con `render_template("index.html")`.

Una **plantilla HTML** define el contenido y la estructura de una página. Flask busca estas plantillas en `templates/`.

Los **archivos estáticos** son recursos como CSS e imágenes. Flask los sirve desde `static/`. La plantilla usa `url_for('static', filename='style.css')` para generar la dirección de la hoja de estilos.

El CSS controla la apariencia. Sus anchos flexibles y su regla `@media` ajustan el espacio disponible en pantallas pequeñas.

`main.py` contiene el mensaje de ejemplo inicial y se conserva por ahora. El punto de entrada de esta aplicación es `app.py`.

## Comprobación manual

Con el servidor encendido:

- Visita `/`: debe aparecer el título, el mensaje de bienvenida y el Dashboard provisional.
- Visita `/static/style.css`: debe mostrarse la hoja CSS.
- Reduce el ancho del navegador o usa su modo móvil para revisar la adaptación del diseño.
