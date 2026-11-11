"""Firefox optativo, sin dependencias nuevas; servidor WebDriver existente.

PYTHONPATH=. WEBDRIVER_URL=http://127.0.0.1:4444 uv run --no-sync python tests/browser_position_validation.py
Usa exclusivamente SQLite temporal, secreto efímero y capturas en /tmp.
"""
import base64
import json
import os
import secrets
import tempfile
import threading
import time
import urllib.request
from pathlib import Path


def main():
    webdriver = os.environ['WEBDRIVER_URL'].rstrip('/')
    def command(path, data=None, method=None):
        request = urllib.request.Request(webdriver + path, data=None if data is None else json.dumps(data).encode(),
                                         headers={'Content-Type':'application/json'}, method=method)
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)['value']

    with tempfile.TemporaryDirectory(prefix='positions-browser-') as folder:
        db = Path(folder)/'journal.sqlite3'
        os.environ['SECRET_KEY'] = secrets.token_hex(32)
        os.environ['JOURNAL_DATABASE'] = str(db)
        from database import initialize
        from app import app
        from trade_service import TradeService
        from werkzeug.serving import make_server, WSGIRequestHandler
        initialize(db)
        assert Path(app.config['DATABASE']) == db
        service = TradeService(db)
        account = service.create_account('Personal QA', 'personal')
        def row(kind='entry', quantity='1', price='20000', minute=0, commission='0'):
            return dict(row_id='row', execution_type=kind, quantity=quantity, price=price,
                        executed_at=f'2026-11-10T10:{minute:02}:00-04:00', commission=commission, fees='0')
        trade = service.create_trade_with_executions(account, 'MNQ', 'long', [row(quantity='2',commission='2.50')], request_id='browser-initial-001')['trade_id']
        class Quiet(WSGIRequestHandler):
            def log(self, *args, **kwargs): pass
        server = make_server('127.0.0.1', 0, app, request_handler=Quiet)
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        sid = None
        try:
            sid = command('/session', {'capabilities':{'alwaysMatch':{'browserName':'firefox','moz:firefoxOptions':{'args':['-headless']}}}})['sessionId']
            prefix = '/session/' + sid
            def js(script): return command(prefix+'/execute/sync', {'script':script, 'args':[]})
            def wait(expression):
                for _ in range(150):
                    if js('return '+expression): return
                    time.sleep(.05)
                raise AssertionError(expression + ': ' + str(js("return document.querySelector('#execution-message').textContent")))
            def fill(values):
                js('for(const [name,value] of Object.entries('+json.dumps(values)+')) form.elements[name].value=value;form.dispatchEvent(new Event("input",{bubbles:true}));')
            def preview():
                js('form.requestSubmit();'); wait("!document.querySelector('#execution-preview').hidden")
            def save():
                js("document.querySelector('#execution-confirm').checked=true;document.querySelector('#execution-confirm').dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('#save-execution').click();")
            command(prefix+'/window/rect', {'width':1366,'height':1000})
            command(prefix+'/url', {'url':f'http://127.0.0.1:{server.server_port}/journal/{trade}'})
            js("window.form=document.querySelector('#execution-form');window.shouldWarn=()=>{const e=new Event('beforeunload',{cancelable:true});window.dispatchEvent(e);return e.defaultPrevented;};")
            assert not js('return shouldWarn()')
            fill(dict(executed_at='2026-11-10T19:31:00',offset='+05:30',quantity='1',price='20030',commission='1.25'))
            assert js('return shouldWarn()')
            preview()
            assert '14:01:00.000000Z' in js("return document.querySelector('#execution-order').textContent")
            assert '20010' in js("return document.querySelector('#execution-comparison').textContent")
            for label,width in [('desktop',1366),('mobile',500)]:
                command(prefix+'/window/rect',{'width':width,'height':1000})
                assert js('return document.documentElement.scrollWidth<=innerWidth'), 'overflow '+label
                for section in ('current-title','execution-fields','execution-preview'):
                    js(f"document.getElementById('{section}').scrollIntoView();")
                    Path(f'/tmp/position-{label}-{section}.png').write_bytes(base64.b64decode(command(prefix+'/screenshot')))
            save(); wait("document.querySelector('#detail-revision').textContent==='1'")
            assert not js('return shouldWarn()')
            assert service.get_trade(trade)['summary']['open_quantity']==3
            # Financial failure keeps input. Full-close preset uses current quantity.
            js("document.querySelector('#prepare-close').click();")
            assert js('return form.elements.quantity.value')=='3'
            fill(dict(executed_at='2026-11-10T10:02:00',quantity='4',price='20050',commission='1.25'))
            js('form.requestSubmit();'); wait("document.querySelector('#execution-errors').textContent.includes('history')")
            assert js('return form.elements.quantity.value')=='4'
            fill(dict(quantity='1')); preview(); save()
            wait("document.querySelector('#detail-revision').textContent==='2'")
            assert str(service.get_trade(trade)['summary']['net_pnl'])=='75.00'
            # Another tab modifies metadata after preview: explicit refresh and reconfirmation.
            js("document.querySelector('#prepare-close').click();")
            fill(dict(executed_at='2026-11-10T10:03:00',price='20080',commission='2.50'))
            preview()
            service.update_trade_metadata(trade, notes='Cambio desde otra pestaña')
            save(); wait("document.querySelector('#execution-message').textContent.includes('Conservamos')")
            assert js('return form.elements.quantity.value')=='2'
            assert js("return document.querySelector('#preview-execution').disabled")
            js("document.querySelector('#refresh-position').click();")
            wait("document.querySelector('#detail-revision').textContent==='3'")
            assert not js("return document.querySelector('#execution-confirm').checked")
            assert js('return form.elements.price.value')=='20080'
            # Delayed preview must not survive a field change.
            js("window.baseFetch=fetch;window.fetch=async(...args)=>{const response=await baseFetch(...args);await new Promise(r=>setTimeout(r,400));return response;};form.requestSubmit();")
            time.sleep(.1); fill(dict(price='20081')); time.sleep(.5)
            assert js("return document.querySelector('#execution-preview').hidden")
            js('window.fetch=baseFetch;'); fill(dict(price='20080')); preview()
            # Commit closes trade, response is lost; same key must still return the receipt.
            js("""window.attempts=[];window.lose=true;window.fetch=async(url,options)=>{
                if(url===form.dataset.save){attempts.push(options.body);const response=await baseFetch(url,options);
                if(lose){lose=false;throw new Error('lost response');}return response;}return baseFetch(url,options);};""")
            save(); wait("document.querySelector('#execution-message').textContent.includes('Se perdió')")
            assert service.get_trade(trade)['summary']['status']=='closed'
            assert js("return document.querySelector('#execution-fields').disabled")
            assert js('return shouldWarn()')
            js("document.querySelector('#save-execution').click();")
            wait("document.querySelector('#detail-status').textContent==='closed'")
            assert js('return attempts.length===2 && attempts[0]===attempts[1]')
            assert js('return form.hidden')
            assert not js('return shouldWarn()')
            assert js("return document.querySelectorAll('#detail-history tr').length")==4
            assert str(service.get_trade(trade)['summary']['net_pnl'])=='352.50'
            # Retroactive insertion warning and account archive read-only.
            other = service.create_trade_with_executions(account,'MNQ','long',[
                row(quantity='2'), {**row('exit',price='20050',minute=2),'row_id':'exit'}],request_id='browser-retro-00001')['trade_id']
            command(prefix+'/url',{'url':f'http://127.0.0.1:{server.server_port}/journal/{other}'})
            js("window.form=document.querySelector('#execution-form');")
            fill(dict(executed_at='2026-11-10T10:01:00',price='20030')); preview()
            assert not js("return document.querySelector('#retroactive-warning').hidden")
            assert 'P&L' in js("return document.querySelector('#retroactive-warning').textContent")
            service.set_account_active(account,False)
            js("document.querySelector('#refresh-position').click();")
            wait('form.hidden')
            assert 'Archivada' in js("return document.querySelector('#detail-account').textContent")
            print('Firefox OK: entradas, parcial, cierre, costos, offset +05:30, errores y borradores, preview obsoleto, conflicto con actualización explícita, respuesta perdida y reintento tras cierre, historial actualizado, retroactivos, archivo y escritorio/móvil.',flush=True)
        finally:
            if sid: command('/session/'+sid,method='DELETE')
            server.shutdown(); server.server_close(); worker.join()
    print('SQLite temporal eliminada; base personal no utilizada.',flush=True)


if __name__ == '__main__': main()
