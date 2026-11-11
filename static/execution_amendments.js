"use strict";
(() => {
    const form = document.querySelector('#amendment-form');
    if (!form) return;
    const fields = document.querySelector('#amendment-fields');
    const values = document.querySelector('#amendment-values');
    const preview = document.querySelector('#amendment-preview');
    const confirm = document.querySelector('#confirm-amendment');
    const save = document.querySelector('#save-amendment');
    const message = document.querySelector('#amendment-message');
    const errors = document.querySelector('#amendment-errors');
    const names = ['executed_at','execution_type','quantity','price','commission','fees'];
    let current = JSON.parse(document.querySelector('#trade-snapshot').textContent);
    let selection = null, prepared = null, controller = null, version = 0;
    let busy = false, previewing = false, uncertain = false, stale = false, baseline = '';
    const state = () => JSON.stringify([...names, 'reason'].map(name => form.elements[name].value));
    const key = () => Array.from(crypto.getRandomValues(new Uint8Array(24)), b => b.toString(16).padStart(2,'0')).join('');
    const locked = () => busy || uncertain;
    function controls() {
        fields.disabled = locked() || !current.account.is_active;
        document.querySelector('#preview-amendment').disabled = previewing || locked() || stale || !current.account.is_active;
        save.disabled = !prepared || !confirm.checked || busy || stale || !current.account.is_active;
        confirm.disabled = busy;
        document.querySelector('#cancel-amendment').disabled = locked();
        document.querySelector('#refresh-amendment').disabled = locked();
        window.dispatchEvent(new CustomEvent('journal:amendment-state',{detail:{active:!!selection,locked:locked()}}));
    }
    function invalidate() {
        version++; if (controller) controller.abort(); controller = null;
        previewing = false; prepared = null; preview.hidden = true; confirm.checked = false;
        errors.replaceChildren(); controls();
    }
    function showErrors(data) {
        errors.replaceChildren();
        for (const group of [data.fields || {}, ...Object.values(data.rows || {})]) {
            for (const [name,text] of Object.entries(group)) { const p = document.createElement('p'); p.textContent = `${name}: ${text}`; errors.append(p); }
        }
    }
    function failure(data) {
        invalidate();
        stale = ['stale_revision','account_inactive','not_found'].includes(data.code);
        showErrors(data.errors || {});
        message.textContent = stale ? 'La operación cambió. Conservamos el borrador: actualiza la posición, previsualiza y confirma de nuevo.' : 'El borrador se conserva. Revisa el error y genera un nuevo preview.';
        controls();
    }
    function render(result) {
        const body = document.querySelector('#amendment-summary'); body.replaceChildren();
        for (const [name,label] of [['status','Estado'],['open_quantity','Contratos abiertos'],['average_price','Precio promedio'],['gross_pnl','Bruto USD'],['commission','Comisiones USD'],['fees','Cargos USD'],['net_pnl','Neto USD']]) {
            const tr = document.createElement('tr');
            for (const text of [label,result.current[name] ?? '—',result.projected[name] ?? '—']) { const td = document.createElement('td'); td.textContent = text; tr.append(td); }
            body.append(tr);
        }
        const changes = document.querySelector('#amendment-changes'); changes.replaceChildren();
        for (const [name,label] of [['executed_at','Fecha UTC'],['execution_type','Tipo'],['quantity','Contratos'],['price','Precio'],['commission','Comisión USD'],['fees','Cargos USD'],['is_voided','Anulada (0=no, 1=sí)'],['sequence','Secuencia']]) {
            const p = document.createElement('p'); p.textContent = `${label}: ${result.before_display[name]} → ${result.after_display[name]}`; changes.append(p);
        }
        document.querySelector('#amendment-order').textContent = `Orden vigente (IDs): ${result.current_order.join(', ') || 'vacío'} → ${result.projected_order.join(', ') || 'vacío'}`;
        const warnings = document.querySelector('#amendment-warnings'); warnings.replaceChildren();
        for (const warning of result.warnings) { const p = document.createElement('p'); p.textContent = warning; warnings.append(p); }
        preview.hidden = false;
    }
    window.addEventListener('journal:amend', event => {
        if (selection || locked()) return;
        selection = {id:event.detail.row.id, action:event.detail.action}; current = event.detail.snapshot;
        form.reset(); stale = false;
        for (const name of names) form.elements[name].value = event.detail.row[name];
        const correction = selection.action === 'correction'; values.hidden = !correction;
        for (const name of names) form.elements[name].required = correction;
        document.querySelector('#amendment-title').textContent = `${correction ? 'Corregir' : 'Anular'} ejecución #${selection.id}`;
        message.textContent = ''; form.hidden = false; baseline = state(); invalidate(); form.scrollIntoView();
    });
    window.addEventListener('journal:snapshot', event => {
        current = event.detail;
        if (selection && !locked()) {
            invalidate(); stale = false;
            message.textContent = 'Posición actualizada. Se conserva el borrador; genera un nuevo preview y confirma nuevamente.';
            controls();
        }
    });
    form.addEventListener('input', event => { if (event.target !== confirm && !locked()) invalidate(); });
    form.addEventListener('change', event => { if (event.target === confirm) controls(); else if (!locked()) invalidate(); });
    document.querySelector('#cancel-amendment').addEventListener('click', () => {
        if (locked()) return;
        selection = null; form.hidden = true; invalidate();
    });
    document.querySelector('#refresh-amendment').addEventListener('click', () => {
        if (locked()) return;
        invalidate(); stale = true; controls();
        window.dispatchEvent(new Event('journal:refresh-request'));
    });
    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (!selection || locked() || stale || !current.account.is_active || !form.reportValidity()) return;
        invalidate();
        const payload = {expected_revision:current.revision,reason:form.elements.reason.value};
        if (selection.action === 'correction') payload.replacement = Object.fromEntries(names.map(name => [name,form.elements[name].value]));
        const url = `${form.dataset.base}/${selection.id}/${selection.action}`;
        const stamp = version; controller = new AbortController(); const signal = controller.signal;
        previewing = true; controls(); message.textContent = 'Revalidando toda la historia…';
        try {
            const response = await fetch(url+'/preview', {method:'POST',signal,
                headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('#execution-csrf').value},body:JSON.stringify(payload)});
            const data = await response.json();
            if (stamp !== version) return;
            if (!response.ok || !data.ok) { failure(data); return; }
            prepared = {url, body:JSON.stringify({...payload,preview_token:data.result.preview_token,request_id:key()})};
            render(data.result); message.textContent = 'Revisa y confirma. El preview caduca en diez minutos.';
        } catch (error) {
            if (stamp === version && error.name !== 'AbortError') message.textContent = 'No se pudo previsualizar. El borrador se conserva.';
        } finally { if (stamp === version) { previewing = false; controller = null; controls(); } }
    });
    save.addEventListener('click', async () => {
        if (!prepared || !confirm.checked || busy || stale || !current.account.is_active) return;
        busy = true; controls(); message.textContent = 'Confirmando cambio auditable…';
        let succeeded = false;
        try {
            const response = await fetch(prepared.url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('#execution-csrf').value},body:prepared.body});
            const data = await response.json();
            if (!response.ok || !data.ok) {
                uncertain = uncertain || response.status >= 500;
                if (uncertain) { showErrors(data.errors || {}); message.textContent = 'Resultado incierto. Reintenta con la misma clave; no recargues ni cambies el borrador.'; }
                else failure(data);
                return;
            }
            uncertain = false; succeeded = true; selection = null; prepared = null;
            form.hidden = true; message.textContent = `Cambio confirmado. Evento #${data.result.audit_id}.`;
        } catch (error) {
            uncertain = true; message.textContent = 'Se perdió la respuesta. Reintenta Confirmar cambio auditable con la misma clave. No recargues.';
        } finally { busy = false; controls(); }
        if (succeeded) {
            document.querySelector('#execution-message').textContent = 'Cambio auditable confirmado. Actualizando detalle…';
            window.dispatchEvent(new Event('journal:refresh-request'));
        }
    });
    window.addEventListener('beforeunload', event => {
        if (selection && (locked() || state() !== baseline)) { event.preventDefault(); event.returnValue = ''; }
    });
})();
