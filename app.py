from decimal import Decimal

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from calculations import ValidationError, calculate_risk
from contracts import CONTRACTS

app = Flask(__name__)


@app.route("/")
def inicio():
    return render_template("index.html")


@app.route("/journal")
def journal():
    return render_template("journal.html")


@app.route("/calendar")
def calendar():
    return render_template("calendar.html")


@app.route("/calculator")
def calculator():
    return render_template("calculator.html", contracts=CONTRACTS)


@app.route("/accounts")
def accounts():
    return render_template("accounts.html")


@app.route("/settings")
def settings():
    return render_template("settings.html")


@app.route("/api/calculate-risk", methods=["POST"])
def calculate_risk_api():
    if not request.is_json:
        return jsonify(ok=False, errors={"form": "Envía los datos como JSON."}), 415
    # Evita cuerpos excesivos antes de procesar el JSON (límite solo de esta API).
    request.max_content_length = 4096
    try:
        data = request.get_json()
    except RequestEntityTooLarge:
        return jsonify(ok=False, errors={"form": "La solicitud supera 4096 bytes."}), 413
    except BadRequest:
        return jsonify(ok=False, errors={"form": "El JSON no es válido."}), 400
    try:
        result = calculate_risk(data)
    except ValidationError as error:
        return jsonify(ok=False, errors=error.errors), 400
    # Se serializan decimales exactos sin símbolos; la interfaz aplica el formato.
    serialized = {
        key: format(value, "f") if isinstance(value, Decimal) else value
        for key, value in result.items()
    }
    return jsonify(ok=True, result=serialized)


if __name__ == "__main__":
    app.run(debug=True)
