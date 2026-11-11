"""Firefox existente, sin instalar dependencias.
PYTHONPATH=. WEBDRIVER_URL=http://127.0.0.1:4444 uv run --no-sync python tests/browser_journal_history_validation.py
SQLite temporal; capturas /tmp/history-{desktop,mobile}.png.
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
    with tempfile.TemporaryDirectory(prefix='history-browser-') as folder:
        db=Path(folder)/'journal.sqlite3'
        os.environ['SECRET_KEY']=secrets.token_hex(32);os.environ['JOURNAL_DATABASE']=str(db)
        from database import initialize
        from trade_service import TradeService
        from app import app
        from werkzeug.serving import make_server,WSGIRequestHandler
        assert Path(app.config['DATABASE'])==db
        initialize(db);service=TradeService(db)
        account=service.create_account('Cuenta personal de prueba','personal')
        for index in range(27):
            trade=service.create_trade(account,'MNQ','long',strategy='Entrada y cierre de prueba')
            if index%3:
                service.add_execution(trade,execution_type='entry',quantity=2,price='20000',executed_at='2026-11-10T14:00:00Z',commission='2.50')
            if index%3==2:
                service.add_execution(trade,execution_type='exit',quantity=2,price='20010',executed_at='2026-11-12T14:00:00Z')
        service.set_account_active(account,False)
        class Quiet(WSGIRequestHandler):
            def log(self,*args,**kwargs):pass
        server=make_server('127.0.0.1',0,app,request_handler=Quiet)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();sid=None
        try:
            sid=command('/session',{'capabilities':{'alwaysMatch':{'browserName':'firefox','moz:firefoxOptions':{'args':['-headless']}}}})['sessionId']
            prefix='/session/'+sid
            def js(script):return command(prefix+'/execute/sync',{'script':script,'args':[]})
            def wait(expression):
                for _ in range(100):
                    if js('return '+expression):return
                    time.sleep(.05)
                raise AssertionError(expression)
            base=f'http://127.0.0.1:{server.server_port}'
            command(prefix+'/url',{'url':base+'/journal'})
            wait("document.querySelectorAll('[data-trade-id]').length===25")
            assert 'Archivada' in js('return document.body.textContent')
            for label,width in [('desktop',1366),('mobile',500)]:
                command(prefix+'/window/rect',{'width':width,'height':1000})
                assert js('return document.documentElement.scrollWidth<=innerWidth')
                js("document.querySelector('.history-table').scrollIntoView();")
                Path('/tmp/history-'+label+'.png').write_bytes(base64.b64decode(command(prefix+'/screenshot')))
                for section in ('history-filters','history-statistics'):
                    js(f"document.getElementById('{section}').scrollIntoView();")
                    Path(f'/tmp/history-{label}-{section}.png').write_bytes(base64.b64decode(command(prefix+'/screenshot')))
            first=js("return document.querySelector('[data-stat=net_pnl]').textContent")
            js("Array.from(document.querySelectorAll('.history-pages a')).find(a=>a.textContent==='Siguiente').click();")
            wait("document.querySelectorAll('[data-trade-id]').length===2")
            assert js("return document.querySelector('[data-stat=net_pnl]').textContent")==first
            command(prefix+'/url',{'url':base+'/journal?status=closed&date_from=2026-11-10&date_to=2026-11-10'})
            assert js("return document.querySelectorAll('[data-trade-id]').length")==9
            js("document.querySelector('.history-table a').click();")
            wait("document.querySelector('#detail-status')?.textContent==='closed'")
            command(prefix+'/url',{'url':base+'/journal?date_from=invalid'})
            assert js("return document.querySelector('[name=date_from]').value")=='invalid'
            assert js("return document.querySelector('#history-statistics')===null")
            command(prefix+'/url',{'url':base+'/journal?symbol=ES'})
            assert 'coincidan con estos filtros' in js('return document.body.textContent')
            print('Firefox OK: escritorio/móvil, paginación, métricas globales, archivo, fechas de vida completa, detalle, errores y estado vacío.')
        finally:
            if sid:command('/session/'+sid,method='DELETE')
            server.shutdown();server.server_close();worker.join()


if __name__=='__main__':main()
