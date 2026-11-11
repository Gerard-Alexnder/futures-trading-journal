"""Pantalla de cuentas; SQL y reglas de negocio permanecen en TradeService."""
import secrets

from flask import current_app, render_template, request, session, redirect, url_for, flash
from werkzeug.exceptions import RequestEntityTooLarge

from database import DatabaseError
from trade_calculations import TradeValidationError
from trade_service import TradeService, NotFoundError, ArchivedAccountError, ConflictError, PersistenceError
from web_support import csrf_token, valid_csrf


def register_account_routes(app):
    def page(error=None, status=200, values=None, available=True):
        accounts = []
        if available:
            try:
                accounts = TradeService(current_app.config['DATABASE']).list_accounts()
                selected = session.get('selected_account_id')
                if selected is not None and not any(a['id'] == selected and a['is_active'] for a in accounts):
                    session.pop('selected_account_id', None)
            except DatabaseError as failure:
                error, status, available = str(failure), 503, False
            except PersistenceError:
                error = 'No se pudo cargar el listado de cuentas. Intenta de nuevo más tarde.'
                status, available = 503, False
        return render_template('accounts.html', accounts=accounts, error=error,
                               values=values or {}, available=available,
                               csrf=csrf_token() if current_app.secret_key else '',
                               new_key=lambda: secrets.token_urlsafe(24),
                               selected=session.get('selected_account_id') if current_app.secret_key else None), status

    def handle(account_id=None, action=None):
        if not current_app.secret_key:
            return page(error='Configura SECRET_KEY en el entorno para habilitar Accounts.', status=503, available=False)
        service = TradeService(current_app.config['DATABASE'])
        values = {}
        try:
            if request.method == 'POST':
                request.max_content_length = 16384
                if not valid_csrf():
                    return page(error='Token CSRF inválido. Recarga la página.', status=403, available=False)
                values = request.form.to_dict()
                if action is None:
                    service.create_account(values.get('name', ''), values.get('account_type', ''),
                                           values.get('platform', '').strip() or None,
                                           request_id=values.get('request_id', ''))
                    flash('Cuenta creada.', 'success')
                elif action == 'select':
                    service.get_account(account_id, require_active=True)
                    session['selected_account_id'] = account_id
                    flash('Cuenta seleccionada.', 'success')
                else:
                    if action == 'archive' and values.get('confirm') != 'yes':
                        raise TradeValidationError('Confirma el archivo de la cuenta.')
                    service.set_account_active(account_id, action == 'reactivate',
                                               request_id=values.get('request_id', ''))
                    if action == 'archive' and session.get('selected_account_id') == account_id:
                        session.pop('selected_account_id', None)
                    flash('Estado de cuenta actualizado.', 'success')
                return redirect(url_for('accounts'), code=303)
            return page()
        except RequestEntityTooLarge:
            return page(error='El formulario supera el tamaño permitido.', status=413, available=False)
        except NotFoundError:
            return page(error='Cuenta inexistente.', status=404)
        except ArchivedAccountError:
            return page(error='La cuenta está archivada. Reactívala antes de seleccionarla.', status=409)
        except ConflictError as error:
            return page(error=str(error), status=409, values=values)
        except TradeValidationError as error:
            return page(error=str(error), status=422, values=values)
        except DatabaseError as error:
            return page(error=str(error), status=503, available=False)
        except PersistenceError:
            return page(error='No se pudo acceder a los datos. Intenta de nuevo; si persiste, ejecuta uv run --no-sync python -m database verify (con --path si corresponde).', status=503, available=False)

    app.add_url_rule('/accounts', endpoint='accounts', view_func=handle, methods=['GET', 'POST'])
    for action in ('select', 'archive', 'reactivate'):
        app.add_url_rule('/accounts/<int:account_id>/' + action, endpoint='account_' + action,
                         view_func=handle, defaults={'action': action}, methods=['POST'])
