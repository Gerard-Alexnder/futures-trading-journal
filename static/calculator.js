"use strict";

const form = document.querySelector("#risk-form");
const checkbox = form.elements.include_slippage;
const ticks = form.elements.slippage_ticks;
const results = document.querySelector("#resultados");
const messages = document.querySelector("#mensajes");
const button = form.querySelector("button");
let pending = null;
let version = 0;

// Formato de presentación sobre cadenas exactas, sin convertir dinero a float.
function money(value) {
    const [whole, fraction = ""] = value.split(".");
    const cents = fraction.padEnd(3, "0");
    let rounded = BigInt(whole) * 100n + BigInt(cents.slice(0, 2));
    if (cents[2] >= "5") rounded += 1n;
    return `$${rounded / 100n}.${String(rounded % 100n).padStart(2, "0")}`;
}

function invalidate() {
    version += 1;
    if (pending) pending.abort();
    pending = null;
    button.disabled = false;
    form.removeAttribute("aria-busy");
    results.hidden = true;
    messages.textContent = "";
    document.querySelector("#slippage-field").hidden = !checkbox.checked;
    ticks.disabled = !checkbox.checked;
    ticks.required = checkbox.checked;
}

form.addEventListener("input", invalidate);
form.addEventListener("change", invalidate);
invalidate();

form.addEventListener("submit", async (event) => {
    event.preventDefault();
    invalidate();
    const currentVersion = version;
    const controller = new AbortController();
    pending = controller;
    button.disabled = true;
    form.setAttribute("aria-busy", "true");
    messages.textContent = "Calculando…";
    const payload = {
        instrument: form.elements.instrument.value,
        risk_budget: form.elements.risk_budget.value,
        stop_points: form.elements.stop_points.value,
        commission: form.elements.commission.value,
        include_slippage: checkbox.checked,
        slippage_ticks: ticks.value,
    };
    try {
        const response = await fetch(form.action, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
            signal: controller.signal,
        });
        const data = await response.json();
        if (currentVersion !== version) return;
        if (!response.ok || !data.ok) {
            messages.textContent = Object.values(data.errors || {}).join(" ") || "No se pudo realizar el cálculo.";
            return;
        }
        const result = data.result;
        for (const field of ["risk_per_contract", "total_risk", "remaining_budget"]) {
            document.getElementById(field).textContent = money(result[field]);
        }
        document.querySelector("#contracts").textContent = `${result.contracts} ${result.instrument}`;
        document.querySelector("#nota-slippage").hidden = !payload.include_slippage;
        const warning = document.querySelector("#advertencia");
        warning.textContent = result.warning || "";
        warning.hidden = !result.warning;
        results.hidden = false;
        messages.textContent = "Cálculo actualizado.";
    } catch (error) {
        if (currentVersion === version && error.name !== "AbortError") {
            messages.textContent = "No se pudo obtener el resultado. Comprueba la conexión e inténtalo de nuevo.";
        }
    } finally {
        if (currentVersion === version) {
            pending = null;
            button.disabled = false;
            form.removeAttribute("aria-busy");
        }
    }
});
