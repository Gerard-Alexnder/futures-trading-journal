"""Firefox con WebDriver existente y SQLite temporal; no instala dependencias.
PYTHONPATH=. WEBDRIVER_URL=http://127.0.0.1:4444 uv run --no-sync python tests/browser_execution_corrections_validation.py
Capturas exclusivamente /tmp/corrections-*.png. Secreto efímero sin mostrarlo.
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
    webdriver=os.environ['WEBDRIVER_URL'].rstrip('/')
    def command(path,data=None,method=None):
        request=urllib.request.Request(webdriver+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'},method=method)
        with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)['value']
    with tempfile.TemporaryDirectory(prefix='corrections-browser-') as folder:
        db=Path(folder)/'journal.sqlite3'
        os.environ['SECRET_KEY']=secrets.token_hex(32);os.environ['JOURNAL_DATABASE']=str(db)
        from database import initialize
        from trade_service import TradeService
        from app import app
        from werkzeug.serving import make_server,WSGIRequestHandler
        assert Path(app.config['DATABASE'])==db
        initialize(db);service=TradeService(db)
        account=service.create_account('Personal QA','personal')
        trade=service.create_trade(account,'MNQ','long')
        entry=service.add_execution(trade,execution_type='entry',quantity=2,price='20000',executed_at='2026-11-10T14:00:00Z',commission='2.50')
        close=service.add_execution(trade,execution_type='exit',quantity=2,price='20010',executed_at='2026-11-10T15:00:00Z')
        class Quiet(WSGIRequestHandler):
            def log(self,*args,**kwargs):pass
        server=make_server('127.0.0.1',0,app,request_handler=Quiet)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();sid=None
        try:
            sid=command('/session',{'capabilities':{'alwaysMatch':{'browserName':'firefox','moz:firefoxOptions':{'args':['-headless']}}}})['sessionId']
            prefix='/session/'+sid
            def js(script):return command(prefix+'/execute/sync',{'script':script,'args':[]})
            def wait(expression):
                for _ in range(160):
                    if js('return '+expression):return
                    time.sleep(.05)
                raise AssertionError(expression+'; '+str(js("return document.querySelector('#amendment-message').textContent")))
            def choose(action,execution):js(f"document.querySelector('[data-amend-action={action}][data-execution-id=\"{execution}\"]').click();")
            def fill(values):js('for(const [name,value] of Object.entries('+json.dumps(values)+')) form.elements[name].value=value;form.dispatchEvent(new Event("input",{bubbles:true}));')
            def preview():
                js('form.requestSubmit();');wait("!document.querySelector('#amendment-preview').hidden")
            def save():js("document.querySelector('#confirm-amendment').checked=true;document.querySelector('#confirm-amendment').dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('#save-amendment').click();")
            command(prefix+'/url',{'url':f'http://127.0.0.1:{server.server_port}/journal/{trade}'})
            js("window.form=document.querySelector('#amendment-form');window.shouldWarn=()=>{const e=new Event('beforeunload',{cancelable:true});window.dispatchEvent(e);return e.defaultPrevented;};")
            assert js("return document.querySelector('#execution-form').hidden")
            choose('correction',entry)
            fill({'quantity':'1','reason':'Corregir precio <nota>'})
            js('form.requestSubmit();');wait("document.querySelector('#amendment-errors').textContent.includes('history')")
            assert js('return form.elements.quantity.value')=='1'
            fill({'quantity':'2','price':'20001'});preview()
            service.update_trade_metadata(trade,notes='Cambio concurrente')
            save();wait("document.querySelector('#amendment-message').textContent.includes('La operación cambió')")
            assert js('return form.elements.reason.value')=='Corregir precio <nota>'
            assert js("return document.querySelector('#preview-amendment').disabled")
            js("document.querySelector('#refresh-amendment').click();")
            wait("document.querySelector('#detail-revision').textContent==='3'")
            assert js("return document.querySelector('#amendment-preview').hidden && !document.querySelector('#confirm-amendment').checked")
            js("window.baseFetch=fetch;window.fetch=async(...args)=>{const r=await baseFetch(...args);await new Promise(resolve=>setTimeout(resolve,450));return r;};form.requestSubmit();")
            time.sleep(.1);fill({'reason':'Corregir precio definitivo'});time.sleep(.55)
            assert js("return document.querySelector('#amendment-preview').hidden")
            js('window.fetch=baseFetch;');preview()
            assert '33.50' in js("return document.querySelector('#amendment-summary').textContent")
            assert js('return shouldWarn()')
            for label,width in [('desktop',1366),('mobile',500)]:
                command(prefix+'/window/rect',{'width':width,'height':1000})
                assert js('return document.documentElement.scrollWidth<=innerWidth')
                for section in ('amendment-form','amendment-preview'):
                    js(f"document.getElementById('{section}').scrollIntoView();")
                    Path(f'/tmp/corrections-{label}-{section}.png').write_bytes(base64.b64decode(command(prefix+'/screenshot')))
            save();wait("document.querySelector('#detail-revision').textContent==='4'")
            assert len(service.get_trade(trade)['audit'])==1
            assert not js('return shouldWarn()')
            choose('void',close);fill({'reason':'Anular salida incorrecta'});preview()
            assert 'volverá a open' in js("return document.querySelector('#amendment-warnings').textContent")
            js("""window.attempts=[];window.receipts=[];window.lose=true;window.fetch=async(url,options)=>{
                if(url.endsWith('/void')){attempts.push(options.body);const r=await baseFetch(url,options);receipts.push(await r.clone().json());if(lose){lose=false;throw new Error('lost');}return r;}return baseFetch(url,options);};""")
            save();wait("document.querySelector('#amendment-message').textContent.includes('Se perdió')")
            committed=service.get_trade(trade)
            assert committed['summary']['status']=='open'
            assert js("return document.querySelector('#amendment-fields').disabled")
            assert js('return shouldWarn()')
            js("document.querySelector('#save-amendment').click();")
            wait("document.querySelector('#detail-revision').textContent==='5'")
            assert js('return attempts.length===2 && attempts[0]===attempts[1] && JSON.stringify(receipts[0])===JSON.stringify(receipts[1])')
            assert service.get_trade(trade)==committed
            assert js("return document.querySelectorAll('.voided-execution').length")==1
            assert not js("return document.querySelector('#execution-form').hidden")
            choose('void',entry);fill({'reason':'Anular entrada de prueba'});preview();save()
            wait("document.querySelector('#detail-status').textContent==='pending'")
            assert js("return document.querySelectorAll('#audit-history details').length")==3
            assert service.get_trade(trade)['summary']['net_pnl']==0
            js("document.querySelector('#audit-history details').open=true;document.querySelector('#audit-panel').scrollIntoView();")
            Path('/tmp/corrections-mobile-audit.png').write_bytes(base64.b64decode(command(prefix+'/screenshot')))
            service.set_account_active(account,False)
            js("document.querySelector('#refresh-position').click();")
            wait("document.querySelector('#detail-account').textContent.includes('Archivada')")
            assert js("return document.querySelectorAll('[data-amend-action]').length")==0
            print('Firefox OK: corrección cerrada, error con borrador, conflicto concurrente, nueva confirmación, preview tardío, capturas desktop/móvil, void con respuesta perdida y recibo idéntico, reapertura, pending, auditoría y cuenta archivada.',flush=True)
        finally:
            if sid:command('/session/'+sid,method='DELETE')
            server.shutdown();server.server_close();worker.join()


if __name__=='__main__':main()
