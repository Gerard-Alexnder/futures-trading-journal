"""Registro inicial y detalle de posiciones; sin edición histórica."""
from decimal import Decimal

from flask import current_app, jsonify, render_template, request, session
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from contracts import CONTRACTS
from database import DatabaseError
from trade_calculations import TradeValidationError
from trade_service import (TradeService, DraftValidationError, NotFoundError,
                           ArchivedAccountError, ConflictError, PersistenceError, StaleRevisionError, TradeClosedError)
from web_support import csrf_token, valid_csrf


def json_decimals(value):
    if isinstance(value, Decimal):
        return format(value, 'f')
    if isinstance(value, dict):
        return {key: json_decimals(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_decimals(item) for item in value]
    return value


def register_journal_routes(app):
    @app.get('/journal/new', endpoint='journal_new')
    def new_trade():
        accounts, error, status = [], None, 200
        if not current_app.secret_key:
            error, status = 'Configura SECRET_KEY para registrar operaciones.', 503
        else:
            try:
                accounts = [a for a in TradeService(current_app.config['DATABASE']).list_accounts() if a['is_active']]
            except DatabaseError as failure:
                error, status = str(failure), 503
            except PersistenceError:
                error, status = 'No se pudo consultar las cuentas. Intenta de nuevo más tarde.', 503
        selected = session.get('selected_account_id') if current_app.secret_key else None
        return render_template('journal_new.html', accounts=accounts, contracts=CONTRACTS,
                               selected=selected, error=error,
                               csrf=csrf_token() if current_app.secret_key else ''), status

    def api_error(message, status, errors=None, code='request_error'):
        return jsonify(ok=False, code=code, errors=errors or {'fields': {'form': message}, 'rows': {}}), status

    @app.get('/journal/<int:trade_id>', endpoint='journal_detail')
    def detail(trade_id):
        snapshot, error, status = None, None, 200
        try:
            if not current_app.secret_key:
                raise DatabaseError('Configura SECRET_KEY para utilizar Journal.')
            snapshot = json_decimals(TradeService(current_app.config['DATABASE']).get_trade(trade_id))
        except NotFoundError:
            error, status = 'Operación inexistente.', 404
        except DatabaseError as failure:
            error, status = str(failure), 503
        except (PersistenceError, TradeValidationError):
            error, status = 'No se pudo consultar la operación. Solicita una verificación de los datos.', 503
        if request.accept_mimetypes.best == 'application/json':
            return api_error(error, status) if error else jsonify(ok=True, result=snapshot)
        return render_template('journal_detail.html', trade=snapshot, error=error,
                               tick=CONTRACTS[snapshot['symbol']]['tick_size'] if snapshot else None,
                               csrf=csrf_token() if current_app.secret_key else ''), status

    def process(create=False, trade_id=None):
        request.max_content_length = 512 * 1024
        try:
            if not current_app.secret_key:
                return api_error('Configura SECRET_KEY.', 503)
            if not request.is_json:
                return api_error('Envía un objeto JSON.', 400)
            if not valid_csrf():
                return api_error('Token CSRF inválido. Recarga la página después de conservar tu borrador.', 403)
            data = request.get_json()
            if not isinstance(data, dict):
                return api_error('Envía un objeto JSON.', 400)
            allowed = ({'expected_revision', 'executions'} if trade_id is not None else
                       {'account_id', 'symbol', 'direction', 'strategy', 'notes', 'mode', 'executions'})
            if create:
                allowed.add('request_id')
            if set(data) - allowed:
                return api_error('La solicitud contiene campos desconocidos.', 400)
            required = ({'expected_revision', 'executions'} if trade_id is not None else
                        {'account_id', 'symbol', 'direction', 'executions', 'mode'}) | ({'request_id'} if create else set())
            missing = required - data.keys()
            if missing:
                return api_error('Faltan campos obligatorios.', 400,
                                 {'fields': {name: 'Campo requerido.' for name in sorted(missing)}, 'rows': {}})
            service = TradeService(current_app.config['DATABASE'])
            if trade_id is not None:
                result = (service.append_execution_batch(trade_id, **data) if create else
                          service.preview_execution_batch(trade_id, **data))
            else:
                result = (service.create_trade_with_executions(**data) if create else service.preview_trade(**data))
            return jsonify(ok=True, result=json_decimals(result)), 200
        except RequestEntityTooLarge:
            return api_error('La solicitud supera 512 KiB.', 413)
        except BadRequest:
            return api_error('El JSON no es válido.', 400)
        except NotFoundError:
            if trade_id is not None:
                return api_error('Operación inexistente.', 404, code='not_found')
            return api_error('Cuenta inexistente.', 404, {'fields': {'account_id': 'Cuenta inexistente.'}, 'rows': {}})
        except ArchivedAccountError:
            return api_error('La cuenta está archivada.', 409,
                             {'fields': {'account_id': 'Selecciona una cuenta activa.'}, 'rows': {}}, code='account_inactive')
        except StaleRevisionError as error:
            return api_error(str(error), 409, code='stale_revision')
        except TradeClosedError as error:
            return api_error(str(error), 409, code='trade_closed')
        except ConflictError as error:
            return api_error(str(error), 409, code='idempotency_conflict')
        except DraftValidationError as error:
            return api_error(str(error), 422, error.errors)
        except TradeValidationError as error:
            return api_error(str(error), 422)
        except DatabaseError as error:
            return api_error(str(error), 503)
        except PersistenceError:
            return api_error('No se pudo guardar o consultar la operación. Reintenta sin cambiar el borrador.', 503)

    app.add_url_rule('/api/journal/preview', endpoint='journal_preview', view_func=lambda: process(False), methods=['POST'])
    app.add_url_rule('/api/journal', endpoint='journal_create', view_func=lambda: process(True), methods=['POST'])

    app.add_url_rule('/api/journal/<int:trade_id>/executions/preview', endpoint='execution_preview',
                     view_func=lambda trade_id: process(False, trade_id), methods=['POST'])
    app.add_url_rule('/api/journal/<int:trade_id>/executions', endpoint='execution_create',
                     view_func=lambda trade_id: process(True, trade_id), methods=['POST'])
