from flask import Flask, render_template

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
    return render_template("calculator.html")


@app.route("/accounts")
def accounts():
    return render_template("accounts.html")


@app.route("/settings")
def settings():
    return render_template("settings.html")


if __name__ == "__main__":
    app.run(debug=True)
