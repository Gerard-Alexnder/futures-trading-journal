"""Registro inicial de operaciones; no expone edición ni altas posteriores."""
from decimal import Decimal

from flask import current_app, jsonify, render_template, request, session
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from contracts import CONTRACTS
from database import DatabaseError
from trade_calculations import TradeValidationError
from trade_service import (TradeService, DraftValidationError, NotFoundError,
                           ArchivedAccountError, ConflictError, PersistenceError)
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

    def api_error(message, status, errors=None):
        return jsonify(ok=False, errors=errors or {'fields': {'form': message}, 'rows': {}}), status

    def process(create=False):
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
            allowed = {'account_id', 'symbol', 'direction', 'strategy', 'notes', 'mode', 'executions'}
            if create:
                allowed.add('request_id')
            if set(data) - allowed:
                return api_error('La solicitud contiene campos desconocidos.', 400)
            required = {'account_id', 'symbol', 'direction', 'executions', 'mode'} | ({'request_id'} if create else set())
            missing = required - data.keys()
            if missing:
                return api_error('Faltan campos obligatorios.', 400,
                                 {'fields': {name: 'Campo requerido.' for name in sorted(missing)}, 'rows': {}})
            service = TradeService(current_app.config['DATABASE'])
            result = (service.create_trade_with_executions(**data) if create else service.preview_trade(**data))
            return jsonify(ok=True, result=json_decimals(result)), 200
        except RequestEntityTooLarge:
            return api_error('La solicitud supera 512 KiB.', 413)
        except BadRequest:
            return api_error('El JSON no es válido.', 400)
        except NotFoundError:
            return api_error('Cuenta inexistente.', 404, {'fields': {'account_id': 'Cuenta inexistente.'}, 'rows': {}})
        except ArchivedAccountError:
            return api_error('La cuenta está archivada.', 409,
                             {'fields': {'account_id': 'Selecciona una cuenta activa.'}, 'rows': {}})
        except ConflictError as error:
            return api_error(str(error), 409)
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
