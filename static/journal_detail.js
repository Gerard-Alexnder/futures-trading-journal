"use strict";
(() => {
    const form = document.querySelector('#execution-form');
    if (!form) return;
    let current = JSON.parse(document.querySelector('#trade-snapshot').textContent);
    const fields = document.querySelector('#execution-fields');
    const preview = document.querySelector('#execution-preview');
    const confirm = document.querySelector('#execution-confirm');
    const save = document.querySelector('#save-execution');
    const refreshButton = document.querySelector('#refresh-position');
    const message = document.querySelector('#execution-message');
    const errors = document.querySelector('#execution-errors');
    const names = ['execution_type', 'executed_at', 'offset', 'quantity', 'price', 'commission', 'fees'];
    let version = 0, previewing = false, saving = false, refreshing = false;
    let uncertain = false, stale = false, confirmed = false;
    let controller = null, prepared = null, requestId = null;
    const state = () => JSON.stringify(names.map(name => form.elements[name].value));
    let baseline = state();
    const key = () => Array.from(crypto.getRandomValues(new Uint8Array(24)), b => b.toString(16).padStart(2, '0')).join('');
    const readonly = () => !current.account.is_active || current.summary.status === 'closed';

    function controls() {
        form.hidden = readonly();
        fields.disabled = saving || uncertain || refreshing || readonly();
        document.querySelector('#preview-execution').disabled = previewing || saving || uncertain || refreshing || stale;
        document.querySelector('#prepare-exit').disabled = current.summary.open_quantity === 0 || previewing;
        document.querySelector('#prepare-close').disabled = current.summary.open_quantity === 0 || previewing;
        document.querySelector('#prepare-entry').disabled = previewing;
        refreshButton.disabled = saving || uncertain || refreshing;
        confirm.disabled = saving || refreshing;
        save.disabled = !prepared || !confirm.checked || saving || refreshing || stale || readonly();
    }
    function clearErrors() {
        errors.replaceChildren();
        form.querySelectorAll('[aria-invalid]').forEach(node => node.removeAttribute('aria-invalid'));
    }
    function invalidate() {
        if (saving || uncertain || refreshing) return;
        version += 1;
        if (controller) controller.abort();
        controller = null; previewing = false; prepared = null; requestId = null; confirmed = false;
        preview.hidden = true; confirm.checked = false; clearErrors(); controls();
    }
    function showErrors(data) {
        clearErrors();
        const groups = [data.fields || {}, ...Object.values(data.rows || {})];
        for (const group of groups) for (const [field, text] of Object.entries(group)) {
            const line = document.createElement('p'); line.textContent = `${field}: ${text}`; errors.append(line);
            const input = form.elements.namedItem(field);
            if (input && input.setAttribute) input.setAttribute('aria-invalid', 'true');
        }
    }
    function renderCurrent() {
        document.querySelector('#detail-account').textContent = `${current.account.name} · ${current.account.is_active ? 'Activa' : 'Archivada'}`;
        document.querySelector('#detail-strategy').textContent = current.strategy || '—';
        document.querySelector('#detail-notes').textContent = current.notes || '—';
        document.querySelector('#detail-status').textContent = current.summary.status;
        document.querySelector('#detail-revision').textContent = current.revision;
        document.querySelectorAll('[data-summary]').forEach(node => { node.textContent = current.summary[node.dataset.summary] ?? '—'; });
        document.querySelector('#detail-readonly').hidden = !readonly();
        const history = document.querySelector('#detail-history'); history.replaceChildren();
        for (const row of current.executions) {
            const tr = document.createElement('tr');
            for (const field of ['sequence', 'executed_at', 'execution_type', 'quantity', 'price', 'commission', 'fees']) {
                const td = document.createElement('td'); td.textContent = row[field]; tr.append(td);
            }
            history.append(tr);
        }
        document.querySelector('#history-empty').hidden = current.executions.length > 0;
        controls();
    }
    function renderPreview(result) {
        const tbody = document.querySelector('#execution-comparison'); tbody.replaceChildren();
        for (const [field, label] of [['status','Estado'],['open_quantity','Contratos'],['average_price','Promedio'],
            ['gross_pnl','Bruto realizado USD'],['commission','Comisiones USD'],['fees','Cargos USD'],['net_pnl','Neto acumulado USD']]) {
            const tr = document.createElement('tr');
            for (const value of [label, result.current[field] ?? '—', result.projected[field] ?? '—']) {
                const td = document.createElement('td'); td.textContent = value; tr.append(td);
            }
            tbody.append(tr);
        }
        const warning = document.querySelector('#retroactive-warning'); warning.textContent = result.warning || ''; warning.hidden = !result.retroactive;
        const order = document.querySelector('#execution-order'); order.replaceChildren();
        for (const row of result.executions) {
            const li = document.createElement('li');
            li.textContent = `${row.row_id ? 'Nueva' : 'Existente'} · secuencia ${row.sequence} · ${row.executed_at} · ${row.execution_type} ${row.quantity} a ${row.price} · comisión ${row.commission} · cargos ${row.fees}`;
            order.append(li);
        }
        preview.hidden = false;
    }
    function payload() {
        const row = {row_id: 'execution-draft'};
        for (const name of names) if (name !== 'offset') row[name] = form.elements[name].value;
        row.executed_at += form.elements.offset.value;
        return {expected_revision: current.revision, executions: [row]};
    }
    function conflict(data) {
        if (['stale_revision', 'trade_closed', 'account_inactive'].includes(data.code)) {
            stale = true; prepared = null; preview.hidden = true; confirm.checked = false;
            message.textContent = 'La posición o cuenta cambió. Conservamos el borrador. Pulsa Actualizar posición y vuelve a previsualizar; no se reenviará automáticamente.';
        } else message.textContent = 'Revisa los errores. El borrador se conserva.';
        showErrors(data.errors || {});
    }
    async function refresh(reset = false) {
        if (saving || uncertain || refreshing) return;
        if (controller) controller.abort();
        version += 1; previewing = false; prepared = null; preview.hidden = true; confirm.checked = false;
        refreshing = true; controls();
        try {
            const response = await fetch(form.dataset.detail, {headers: {'Accept': 'application/json'}, cache: 'no-store'});
            const data = await response.json();
            if (!response.ok || !data.ok) { stale = true; showErrors(data.errors || {}); return; }
            current = data.result; stale = false; clearErrors();
            if (reset) { form.reset(); baseline = state(); }
            renderCurrent();
            message.textContent = reset ? 'Ejecución confirmada. Detalle e historial actualizados.' : 'Posición actualizada. El borrador se conserva; genera un nuevo preview y confirma de nuevo.';
        } catch (error) {
            stale = true;
            message.textContent = confirmed ? 'El guardado fue confirmado, pero no pudimos actualizar el detalle. Pulsa Actualizar posición.' : 'No se pudo actualizar. El borrador se conserva.';
        } finally { refreshing = false; controls(); }
    }
    form.addEventListener('input', event => { if (event.target !== confirm) invalidate(); });
    form.addEventListener('change', event => { if (event.target === confirm) controls(); else invalidate(); });
    refreshButton.addEventListener('click', () => refresh(confirmed));
    for (const [id, kind] of [['prepare-entry','entry'], ['prepare-exit','exit'], ['prepare-close','exit']]) {
        document.getElementById(id).addEventListener('click', () => {
            form.elements.execution_type.value = kind;
            if (id === 'prepare-close') form.elements.quantity.value = String(current.summary.open_quantity);
            invalidate();
        });
    }
    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (saving || uncertain || refreshing || stale || readonly() || !form.reportValidity()) return;
        invalidate();
        const draft = payload(), stamp = version;
        controller = new AbortController(); const signal = controller.signal;
        previewing = true; controls(); message.textContent = 'Previsualizando sobre la posición actual…';
        try {
            const response = await fetch(form.dataset.preview, {method: 'POST', signal,
                headers: {'Content-Type':'application/json','X-CSRF-Token':document.querySelector('#execution-csrf').value}, body: JSON.stringify(draft)});
            const data = await response.json();
            if (stamp !== version) return;
            if (!response.ok || !data.ok) { conflict(data); return; }
            prepared = draft; requestId = key(); renderPreview(data.result);
            message.textContent = 'Revisa el estado proyectado y confirma antes de guardar.';
        } catch (error) {
            if (stamp === version && error.name !== 'AbortError') message.textContent = 'No se pudo previsualizar. El borrador se conserva.';
        } finally { if (stamp === version) { previewing = false; controller = null; controls(); } }
    });
    save.addEventListener('click', async () => {
        if (!prepared || !confirm.checked || saving || stale || readonly()) return;
        saving = true; controls(); message.textContent = 'Guardando ejecución…';
        let success = false;
        try {
            const response = await fetch(form.dataset.save, {method:'POST',
                headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('#execution-csrf').value},
                body:JSON.stringify({...prepared,request_id:requestId})});
            const data = await response.json();
            if (!response.ok || !data.ok) {
                uncertain = uncertain || response.status >= 500;
                if (uncertain) { showErrors(data.errors || {}); message.textContent = 'Resultado incierto. Reintenta Confirmar ejecución con la misma clave; no recargues ni cambies el borrador.'; }
                else conflict(data);
                return;
            }
            confirmed = true; uncertain = false; success = true; prepared = null; baseline = state();
            message.textContent = `Ejecución confirmada en revisión ${data.result.revision}. Actualizando detalle…`;
        } catch (error) {
            uncertain = true;
            message.textContent = 'Se perdió la respuesta. Reintenta Confirmar ejecución: conservamos contenido y clave para evitar duplicados. No recargues.';
        } finally { saving = false; controls(); }
        if (success) await refresh(true);
    });
    window.addEventListener('beforeunload', event => {
        if (!confirmed && (saving || uncertain || state() !== baseline)) { event.preventDefault(); event.returnValue = ''; }
    });
    renderCurrent();
})();
