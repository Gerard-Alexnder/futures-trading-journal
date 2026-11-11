"""Validación Firefox optativa con WebDriver existente; solo bases temporales.

Ejecutar desde la raíz:
PYTHONPATH=. WEBDRIVER_URL=http://127.0.0.1:4444 uv run --no-sync python tests/browser_journal_validation.py
No instala ni inicia geckodriver. Usa y cierra una sesión del servidor indicado.
"""
import os, secrets, tempfile, threading, json, urllib.request, time, base64
from pathlib import Path

wd=os.environ['WEBDRIVER_URL'].rstrip('/')
def command(path, data=None, method=None):
    req=urllib.request.Request(wd+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'},method=method)
    with urllib.request.urlopen(req,timeout=30) as response:return json.load(response)['value']

with tempfile.TemporaryDirectory(prefix='journal-browser-') as folder:
    db=Path(folder)/'journal.sqlite3'
    os.environ['SECRET_KEY']=secrets.token_hex(32);os.environ['JOURNAL_DATABASE']=str(db)
    from database import initialize
    initialize(db)
    from app import app
    from trade_service import TradeService
    from werkzeug.serving import make_server, WSGIRequestHandler
    service=TradeService(db);account=service.create_account('Personal QA','personal')
    class Quiet(WSGIRequestHandler):
        def log(self,*args,**kwargs):pass
    server=make_server('127.0.0.1',0,app,request_handler=Quiet)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    sid=None
    try:
        sid=command('/session',{'capabilities':{'alwaysMatch':{'browserName':'firefox','moz:firefoxOptions':{'args':['-headless']}}}})['sessionId']
        prefix='/session/'+sid
        def js(script):return command(prefix+'/execute/sync',{'script':script,'args':[]})
        def wait(expression):
            for _ in range(150):
                if js('return '+expression):return
                time.sleep(.05)
            raise AssertionError('Timeout: '+expression+'; '+str(js("return document.querySelector('#trade-message').textContent")))
        command(prefix+'/window/rect',{'width':1366,'height':1000})
        command(prefix+'/url',{'url':f'http://127.0.0.1:{server.server_port}/journal/new'})
        wait("!!document.querySelector('#execution-rows tr')")
        js("""window.form=document.querySelector('#trade-form');
        window.shouldWarn=()=>{const event=new Event('beforeunload',{cancelable:true});window.dispatchEvent(event);return event.defaultPrevented;};""")
        assert not js('return shouldWarn()'), 'Página inicial sin cambios'
        for field, value in [('notes','nota'),('strategy','plan'),('symbol','MNQ'),('direction','short'),('offset','+00:00'),('custom_offset','+05:30')]:
            old=js(f'return form.elements[{json.dumps(field)}].value')
            js(f'form.elements[{json.dumps(field)}].value={json.dumps(value)};')
            assert js('return shouldWarn()'), field
            js(f'form.elements[{json.dumps(field)}].value={json.dumps(old)};')
            assert not js('return shouldWarn()'), 'Revertir '+field
        for field,value in [('executed_at','2026-11-10T10:00'),('quantity','2'),('commission','1'),('fees','1'),('price','20000')]:
            selector=f'[data-field={field}]'
            old=js(f'return document.querySelector({json.dumps(selector)}).value')
            js(f'document.querySelector({json.dumps(selector)}).value={json.dumps(value)};')
            assert js('return shouldWarn()'), field
            js(f'document.querySelector({json.dumps(selector)}).value={json.dumps(old)};')
            assert not js('return shouldWarn()'), 'Revertir '+field
        # Agregar y retirar una fila tampoco debe dejar una marca de cambio irreversible.
        js("form.elements.mode.value='historical';form.elements.mode.dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('#add-execution').click();")
        assert js('return shouldWarn()')
        js("document.querySelector('#execution-rows tr:last-child [data-action=remove]').click();form.elements.mode.value='progressive';form.elements.mode.dispatchEvent(new Event('change',{bubbles:true}));")
        assert not js('return shouldWarn()')
        js("""window.form=document.querySelector('#trade-form');
        form.elements.symbol.value='MNQ'; form.elements.strategy.value='Reversal';
        window.setRow=(row,values)=>{for(const [key,value] of Object.entries(values))row.querySelector(`[data-field=${key}]`).value=value;};
        setRow(document.querySelector('#execution-rows tr'),{executed_at:'2026-11-10T10:00:00',quantity:'2',price:'20000',commission:'2.50'});
        form.dispatchEvent(new Event('input',{bubbles:true}));form.requestSubmit();""")
        wait("!document.querySelector('#trade-preview').hidden")
        assert '−$2.50' in js("return document.querySelector('#trade-summary').textContent")
        # Offset fraccionario explícito: misma hora UTC y mismo resultado.
        js("""window.observed=[];window.baseFetch=window.fetch;
        window.fetch=(url,options)=>{observed.push(JSON.parse(options.body));return baseFetch(url,options);};
        form.elements.offset.value='custom';form.elements.offset.dispatchEvent(new Event('change',{bubbles:true}));
        form.elements.custom_offset.value='+05:30';setRow(document.querySelector('#execution-rows tr'),{executed_at:'2026-11-10T19:30:00'});
        form.dispatchEvent(new Event('input',{bubbles:true}));form.requestSubmit();""")
        wait("!document.querySelector('#trade-preview').hidden")
        assert js("return observed.at(-1).executions[0].executed_at").endswith('+05:30')
        assert '14:00:00.000000Z' in js("return document.querySelector('#effective-order').textContent")
        assert '−$2.50' in js("return document.querySelector('#trade-summary').textContent")
        js("window.fetch=baseFetch;form.elements.offset.value='-04:00';form.elements.offset.dispatchEvent(new Event('change',{bubbles:true}));setRow(document.querySelector('#execution-rows tr'),{executed_at:'2026-11-10T10:00:00'});")
        # Invalidación y cambio de modalidad; mismas tres ejecuciones del caso de aceptación.
        js("form.elements.mode.value='historical';form.elements.mode.dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('#add-execution').click();document.querySelector('#add-execution').click();")
        assert js("return document.querySelector('#trade-preview').hidden")
        js("""let r=document.querySelectorAll('#execution-rows tr');
        setRow(r[1],{execution_type:'exit',executed_at:'2026-11-10T10:01:00',quantity:'1',price:'20050'});
        setRow(r[2],{execution_type:'exit',executed_at:'2026-11-10T10:02:00',quantity:'1',price:'20080'});
        form.dispatchEvent(new Event('input',{bubbles:true}));form.requestSubmit();""")
        wait("!document.querySelector('#trade-preview').hidden")
        assert '$257.50' in js("return document.querySelector('#trade-summary').textContent")
        # Error financiero mantiene todas las filas y sus valores.
        js("let r=document.querySelectorAll('#execution-rows tr');setRow(r[1],{quantity:'3'});form.dispatchEvent(new Event('input',{bubbles:true}));form.requestSubmit();")
        wait("document.querySelectorAll('#execution-rows .row-errors')[1].textContent.length>0")
        assert js("return document.querySelectorAll('#execution-rows tr').length")==3
        assert js("return document.querySelectorAll('[data-field=quantity]')[1].value")=='3'
        assert len(service.list_trades(account))==0
        js("setRow(document.querySelectorAll('#execution-rows tr')[1],{quantity:'1'});form.dispatchEvent(new Event('input',{bubbles:true}));")
        # Respuesta preview obsoleta: se retrasa su entrega y se cambia el precio.
        js("""window.realFetch=window.fetch;window.fetch=async(...args)=>{const response=await realFetch(...args);await new Promise(resolve=>setTimeout(resolve,500));return response;};form.requestSubmit();""")
        time.sleep(.1)
        js("setRow(document.querySelectorAll('#execution-rows tr')[1],{price:'20051'});form.dispatchEvent(new Event('input',{bubbles:true}));")
        time.sleep(.6)
        assert js("return document.querySelector('#trade-preview').hidden")
        js("window.fetch=realFetch;setRow(document.querySelectorAll('#execution-rows tr')[1],{price:'20050'});form.dispatchEvent(new Event('input',{bubbles:true}));form.requestSubmit();")
        wait("!document.querySelector('#trade-preview').hidden")
        for label,width in [('desktop',1366),('mobile',500)]:
            command(prefix+'/window/rect',{'width':width,'height':1000})
            metrics=js('return {width:innerWidth,scroll:document.documentElement.scrollWidth};')
            assert metrics['width']>=metrics['scroll'],metrics
            js("document.querySelector('#execution-rows').scrollIntoView();")
            Path('/tmp/journal-'+label+'.png').write_bytes(base64.b64decode(command(prefix+'/screenshot')))
        # Pérdida de respuesta después de commit: el reintento conserva exactamente el payload.
        js("""window.attempts=[];window.lose=true;
        window.fetch=async(url,options)=>{if(url==='/api/journal'){attempts.push(options.body);const response=await realFetch(url,options);if(lose){lose=false;throw new Error('simulated lost response');}return response;}return realFetch(url,options);};
        document.querySelector('#confirm-trade').checked=true;document.querySelector('#confirm-trade').dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('#save-trade').click();""")
        wait("document.querySelector('#trade-message').textContent.includes('Se perdió')")
        assert len(service.list_trades(account))==1
        assert js("return document.querySelector('#draft-fields').disabled")
        assert js('return shouldWarn()'), 'Proteger un resultado de guardado incierto'
        js("document.querySelector('#save-trade').click();")
        wait("!document.querySelector('#trade-saved').hidden")
        assert js('return attempts.length===2 && attempts[0]===attempts[1]')
        assert len(service.list_trades(account))==1
        trade=service.get_trade(service.list_trades(account)[0]['id'])
        assert str(trade['summary']['net_pnl'])=='257.50'
        assert not js('return shouldWarn()'), 'No advertir después de guardar'
        assert trade['executions'][0]['executed_at']=='2026-11-10T14:00:00.000000Z'
        print('Firefox OK: beforeunload sin cambios/revertido/pendiente/guardado, offset +05:30 y UTC, preview progresivo e histórico, error por fila con borrador conservado, preview obsoleto descartado, escritorio/móvil sin overflow y reintento tras commit sin duplicados.',flush=True)
    finally:
        if sid: command('/session/'+sid,method='DELETE')
        server.shutdown();server.server_close();worker.join()
print('Base temporal eliminada; sin acceso a base personal.',flush=True)
