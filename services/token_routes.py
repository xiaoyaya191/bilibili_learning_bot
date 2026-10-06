"""Token dashboard routes protected by the panel's existing authentication."""
import csv
import io
import sqlite3
from flask import Blueprint, Response, current_app, jsonify, request
from services.token_observability import TokenStore, report

blueprint = Blueprint('token_dashboard', __name__)


def store():
    return TokenStore(current_app.config['TOKEN_DATA_DIRECTORY']())


@blueprint.errorhandler(ValueError)
def invalid(error):
    return jsonify(ok=False, message=str(error)), 400


@blueprint.errorhandler(OSError)
@blueprint.errorhandler(sqlite3.Error)
def failed(error):
    return jsonify(ok=False, message='Token数据库读写失败，请检查磁盘或权限'), 500


@blueprint.get('/api/tokens/report')
def dashboard():
    result = report(store(), request.args)
    result.pop('_export')
    response = jsonify(ok=True, **result)
    response.headers['Cache-Control'] = 'no-store'
    return response


@blueprint.route('/api/tokens/settings', methods=['GET', 'POST'])
def settings():
    target = store()
    if request.method == 'GET':
        return jsonify(ok=True, settings=target.settings())
    return jsonify(ok=True, settings=target.save_settings(request.get_json(silent=True)))


@blueprint.post('/api/tokens/prune')
def prune():
    value = request.get_json(silent=True)
    if not isinstance(value, dict) or value.get('confirmed') is not True:
        raise ValueError('清理历史记录不可恢复，请确认')
    return jsonify(ok=True, removed=store().prune())


@blueprint.get('/api/tokens/export')
def export():
    result = report(store(), request.args)
    columns = ['id', 'timestamp', 'source', 'model', 'provider', 'endpoint', 'status', 'outcome', 'latency_ms', 'input_tokens', 'output_tokens', 'total_tokens', 'cached_tokens', 'reasoning_tokens', 'estimated_cny']
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in result['_export']:
        cells = []
        for key in columns:
            value = row.get(key)
            if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
                value = "'" + value
            cells.append('' if value is None else value)
        writer.writerow(cells)
    filename = 'tokens_' + result['start'] + '_' + result['end'] + '.csv'
    return Response('\ufeff' + output.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename="' + filename + '"', 'Cache-Control': 'no-store'})
