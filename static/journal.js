"use strict";
(() => {
    const form = document.querySelector('#trade-form');
    if (!form) return;
    const fields = document.querySelector('#draft-fields');
    const rows = document.querySelector('#execution-rows');
    const template = document.querySelector('#execution-template');
    const preview = document.querySelector('#trade-preview');
    const previewButton = document.querySelector('#preview-trade');
    const addButton = document.querySelector('#add-execution');
    const saveButton = document.querySelector('#save-trade');
    const confirm = document.querySelector('#confirm-trade');
    const message = document.querySelector('#trade-message');
    const errors = document.querySelector('#trade-errors');
    let serial = 0;
    let version = 0;
    let previewRequest = null;
    let previewing = false;
    let saving = false;
    let uncertain = false;
    let saved = false;
    let prepared = null;
    let requestKey = null;
    let previousMode = 'progressive';
    let initialDraft = null;

    function draftState() {
        // Valores visibles sin normalizar: también protege notas, fechas y costos aislados.
        // La identidad técnica de una fila no constituye un cambio del borrador.
        return JSON.stringify({
            fields: Object.fromEntries(['account_id', 'symbol', 'direction', 'strategy', 'notes',
                'mode', 'offset', 'custom_offset'].map(name => [name, form.elements[name].value])),
            rows: Array.from(rows.children, row => Object.fromEntries(
                Array.from(row.querySelectorAll('[data-field]'), input => [input.dataset.field, input.value]))),
        });
    }

    function key() {
        return Array.from(crypto.getRandomValues(new Uint8Array(24)), b => b.toString(16).padStart(2, '0')).join('');
    }
    function controls() {
        const progressive = form.elements.mode.value === 'progressive';
        fields.disabled = saving || uncertain || saved;
        previewButton.disabled = previewing || saving || uncertain || saved;
        addButton.hidden = progressive;
        addButton.disabled = previewing || rows.children.length >= 200;
        Array.from(rows.children).forEach((row, i) => {
            row.querySelector('.row-number').textContent = `Fila ${i + 1}`;
            row.querySelector('[data-field=execution_type]').disabled = progressive;
            row.querySelector('[data-action=up]').disabled = progressive || previewing || i === 0;
            row.querySelector('[data-action=down]').disabled = progressive || previewing || i === rows.children.length - 1;
            row.querySelector('[data-action=remove]').disabled = progressive || previewing;
        });
        confirm.disabled = saving || saved;
        saveButton.disabled = !prepared || !confirm.checked || previewing || saving || saved;
    }
    function clearErrors() {
        errors.replaceChildren();
        rows.querySelectorAll('.row-errors').forEach(node => { node.textContent = ''; });
        form.querySelectorAll('[aria-invalid]').forEach(node => node.removeAttribute('aria-invalid'));
    }
    function invalidate() {
        if (saving || uncertain || saved) return;
        version += 1;
        if (previewRequest) previewRequest.abort();
        previewRequest = null;
        previewing = false;
        prepared = null;
        requestKey = null;
        preview.hidden = true;
        confirm.checked = false;
        message.textContent = 'Borrador modificado. Previsualiza antes de guardar.';
        clearErrors();
        controls();
    }
    function addRow() {
        const row = template.content.firstElementChild.cloneNode(true);
        row.dataset.rowId = `row-${++serial}`;
        rows.append(row);
        updateTick();
        controls();
    }
    function updateTick() {
        const tick = form.elements.symbol.selectedOptions[0].dataset.tick;
        rows.querySelectorAll('[data-field=price]').forEach(input => { input.step = tick; input.min = tick; });
    }
    function payload() {
        const custom = form.elements.offset.value === 'custom';
        const offset = custom ? form.elements.custom_offset.value : form.elements.offset.value;
        return {
            account_id: Number(form.elements.account_id.value),
            symbol: form.elements.symbol.value,
            direction: form.elements.direction.value,
            mode: form.elements.mode.value,
            strategy: form.elements.strategy.value.trim() || null,
            notes: form.elements.notes.value.trim() || null,
            executions: Array.from(rows.children).map(row => {
                const result = {row_id: row.dataset.rowId};
                row.querySelectorAll('[data-field]').forEach(input => { result[input.dataset.field] = input.value; });
                result.executed_at += offset;
                return result;
            }),
        };
    }
    function showErrors(data) {
        clearErrors();
        for (const [field, text] of Object.entries(data.fields || {})) {
            const line = document.createElement('p');
            line.textContent = `${field}: ${text}`;
            errors.append(line);
            const input = form.elements.namedItem(field);
            if (input && input.setAttribute) input.setAttribute('aria-invalid', 'true');
        }
        for (const [identity, rowErrors] of Object.entries(data.rows || {})) {
            const row = Array.from(rows.children).find(item => item.dataset.rowId === identity);
            const text = Object.entries(rowErrors).map(([field, detail]) => `${field}: ${detail}`).join(' ');
            if (row) {
                row.querySelector('.row-errors').textContent = text;
                row.querySelectorAll('[data-field]').forEach(input => {
                    if (Object.hasOwn(rowErrors, input.dataset.field)) input.setAttribute('aria-invalid', 'true');
                });
            } else {
                const line = document.createElement('p'); line.textContent = text; errors.append(line);
            }
        }
    }
    // Solo formato de presentación: los importes llegan calculados por Python.
    function money(value) {
        const negative = value.startsWith('-');
        const [whole, fraction = ''] = (negative ? value.slice(1) : value).split('.');
        const digits = fraction.padEnd(3, '0');
        let cents = BigInt(whole) * 100n + BigInt(digits.slice(0, 2));
        if (digits[2] >= '5') cents += 1n;
        return `${negative && cents !== 0n ? '−' : ''}$${cents / 100n}.${String(cents % 100n).padStart(2, '0')}`;
    }
    function showPreview(result) {
        const summary = document.querySelector('#trade-summary'); summary.replaceChildren();
        const labels = [
            ['status', 'Estado'], ['open_quantity', 'Contratos abiertos'], ['average_price', 'Precio promedio abierto'],
            ['gross_pnl', 'P&L bruto realizado'], ['commission', 'Comisiones'], ['fees', 'Otros cargos'], ['net_pnl', 'P&L neto acumulado'],
        ];
        for (const [name, label] of labels) {
            const box = document.createElement('div'); const dt = document.createElement('dt'); const dd = document.createElement('dd');
            dt.textContent = label;
            dd.textContent = ['gross_pnl', 'commission', 'fees', 'net_pnl'].includes(name) ? money(result.summary[name]) : (result.summary[name] ?? '—');
            box.append(dt, dd); summary.append(box);
        }
        const order = document.querySelector('#effective-order'); order.replaceChildren();
        for (const row of result.executions) {
            const item = document.createElement('li');
            item.textContent = `Fila ${row.sequence}: ${row.executed_at} · ${row.execution_type} · ${row.quantity} contratos a ${row.price} · comisión ${row.commission} USD · cargos ${row.fees} USD`;
            order.append(item);
        }
        preview.hidden = false;
    }
    form.addEventListener('input', event => {
        if (event.target !== confirm) invalidate();
    });
    form.addEventListener('change', event => {
        if (event.target === confirm) { controls(); return; }
        if (event.target.name === 'mode') {
            if (form.elements.mode.value === 'progressive') {
                const destructive = rows.children.length > 1 || (rows.firstElementChild && rows.firstElementChild.querySelector('[data-field=execution_type]').value !== 'entry');
                if (destructive && !window.confirm('La modalidad progresiva conservará solo la primera fila como entrada. ¿Continuar?')) {
                    form.elements.mode.value = previousMode; controls(); return;
                }
                while (rows.children.length > 1) rows.lastElementChild.remove();
                if (!rows.children.length) addRow();
                rows.firstElementChild.querySelector('[data-field=execution_type]').value = 'entry';
            }
            previousMode = form.elements.mode.value;
        }
        if (event.target.name === 'offset') {
            const custom = event.target.value === 'custom';
            document.querySelector('#custom-offset-field').hidden = !custom;
            form.elements.custom_offset.required = custom;
        }
        updateTick(); invalidate();
    });
    rows.addEventListener('click', event => {
        const button = event.target.closest('button[data-action]');
        if (!button || button.disabled || saving || uncertain) return;
        const row = button.closest('tr');
        if (button.dataset.action === 'remove') row.remove();
        if (button.dataset.action === 'up' && row.previousElementSibling) rows.insertBefore(row, row.previousElementSibling);
        if (button.dataset.action === 'down' && row.nextElementSibling) rows.insertBefore(row.nextElementSibling, row);
        invalidate();
    });
    addButton.addEventListener('click', () => { if (rows.children.length < 200) { addRow(); invalidate(); } });
    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (saving || uncertain || saved || !form.reportValidity()) return;
        invalidate();
        const draft = payload(); const current = version;
        const controller = new AbortController(); previewRequest = controller; previewing = true; controls();
        message.textContent = 'Previsualizando…';
        try {
            const response = await fetch(form.dataset.preview, {
                method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': document.querySelector('#trade-csrf').value},
                body: JSON.stringify(draft), signal: controller.signal,
            });
            const data = await response.json();
            if (current !== version) return;
            if (!response.ok || !data.ok) { showErrors(data.errors || {}); message.textContent = 'Revisa el borrador. No se guardó ninguna operación.'; return; }
            prepared = draft; requestKey = key(); showPreview(data.result);
            message.textContent = 'Revisa los resultados y el orden UTC antes de confirmar.';
        } catch (error) {
            if (current === version && error.name !== 'AbortError') message.textContent = 'No se pudo previsualizar. El borrador se conserva.';
        } finally {
            if (current === version) { previewing = false; previewRequest = null; controls(); }
        }
    });
    saveButton.addEventListener('click', async () => {
        if (!prepared || !confirm.checked || saving || saved) return;
        saving = true; controls(); message.textContent = 'Guardando…';
        try {
            const response = await fetch(form.dataset.create, {
                method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': document.querySelector('#trade-csrf').value},
                body: JSON.stringify({...prepared, request_id: requestKey}),
            });
            const data = await response.json();
            if (!response.ok || !data.ok) {
                uncertain = response.status >= 500;
                showErrors(data.errors || {});
                message.textContent = uncertain ? 'Resultado no confirmado. Reintenta Guardar sin cambiar el borrador; se usará la misma clave.' : 'No se confirmó el guardado. El borrador se conserva.';
                return;
            }
            uncertain = false; saved = true; form.hidden = true;
            document.querySelector('#saved-result').textContent = `Operación #${data.result.trade_id} registrada correctamente.`;
            document.querySelector('#saved-detail').href = `/journal/${data.result.trade_id}`;
            const confirmation = document.querySelector('#trade-saved'); confirmation.hidden = false; confirmation.focus();
        } catch (error) {
            uncertain = true;
            message.textContent = 'Se perdió la respuesta. Reintenta Guardar sin cambiar el borrador; la misma clave evita duplicados. No recargues esta página.';
        } finally { saving = false; controls(); }
    });
    window.addEventListener('beforeunload', event => {
        if (!saved && (uncertain || saving || draftState() !== initialDraft)) {
            event.preventDefault(); event.returnValue = '';
        }
    });
    addRow(); controls();
    initialDraft = draftState();
})();
