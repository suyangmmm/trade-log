import os
import sys
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, send_file

# ========== Configuration ==========
BASE_DIR = Path(__file__).parent.resolve()
DB_PATH = Path(os.environ.get('TRADE_DB_PATH', str(BASE_DIR / 'trade.db')))
UPLOAD_DIR = BASE_DIR / 'uploads'
HOST = os.environ.get('TRADE_HOST', '0.0.0.0')
PORT = int(os.environ.get("TRADE_PORT", "5800"))
USE_HTTPS = os.environ.get("TRADE_HTTPS", "0") == "1"
CERT_FILE = os.environ.get("TRADE_CERT", str(BASE_DIR / "cert.pem"))
KEY_FILE = os.environ.get("TRADE_KEY", str(BASE_DIR / "key.pem"))
SCHEME = "https" if USE_HTTPS else "http"
SECRET_KEY = os.environ.get('TRADE_SECRET', 'change-me-to-something-random')
DEBUG = os.environ.get('TRADE_DEBUG', '0') == '1'
MAX_CONTENT_LENGTH = int(os.environ.get('TRADE_MAX_UPLOAD_MB', '20')) * 1024 * 1024

app = Flask(__name__, static_folder='.')
app.secret_key = SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# ========== Database ==========
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS fields (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'text',
            options TEXT DEFAULT '[]',
            ord INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS records (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            model_values TEXT NOT NULL DEFAULT '{}',
            result TEXT,
            close_price REAL,
            close_time TEXT,
            close_type TEXT,
            close_pnl REAL
        );
        CREATE TABLE IF NOT EXISTS screenshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            ord INTEGER DEFAULT 0,
            FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE
        );
    """)
    conn.commit()
    conn.close()

# ========== Default Data ==========
DEFAULT_FIELDS = [
    {'id': 'trend', 'name': '趋势方向', 'type': 'dropdown', 'options': ['多头', '空头', '震荡'], 'order': 0},
    {'id': 'pattern', 'name': '形态类型', 'type': 'dropdown', 'options': ['头肩顶','头肩底','双底','双顶','旗形','三角旗形','楔形','矩形','其他'], 'order': 1},
    {'id': 'action', 'name': '操作方向', 'type': 'dropdown', 'options': ['开多','开空'], 'order': 2},
    {'id': 'entry_price', 'name': '开仓价格', 'type': 'number', 'order': 3},
    {'id': 'stop_loss', 'name': '止损价位', 'type': 'number', 'order': 4},
    {'id': 'take_profit', 'name': '止盈价位', 'type': 'number', 'order': 5},
    {'id': 'timeframe', 'name': '交易周期', 'type': 'dropdown', 'options': ['1分钟','5分钟','15分钟','30分钟','60分钟','日线','周线'], 'order': 6},
    {'id': 'position_size', 'name': '仓位比例', 'type': 'number', 'order': 7},
    {'id': 'reason', 'name': '开仓理由', 'type': 'textarea', 'order': 8},
]

def seed_defaults():
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM fields").fetchone()[0]
    if count == 0:
        for f in DEFAULT_FIELDS:
            conn.execute(
                "INSERT INTO fields (id, name, type, options, ord, enabled) VALUES (?, ?, ?, ?, ?, 1)",
                (f['id'], f['name'], f['type'],
                 json.dumps(f.get('options', []), ensure_ascii=False),
                 f['order'])
            )
        conn.commit()
    conn.close()

# ========== Error Handler ==========
@app.errorhandler(413)
def too_large(e):
    return jsonify({'error': f'文件超过 {MAX_CONTENT_LENGTH//1024//1024}MB 限制'}), 413

# ========== API ==========
@app.route('/api/load')
def api_load():
    conn = get_db()
    fields_rows = conn.execute("SELECT * FROM fields ORDER BY ord").fetchall()
    records_rows = conn.execute("SELECT * FROM records ORDER BY timestamp DESC").fetchall()

    fields = []
    for f in fields_rows:
        fields.append({
            'id': f['id'], 'name': f['name'], 'type': f['type'],
            'options': json.loads(f['options']) if f['options'] else [],
            'order': f['ord'], 'enabled': bool(f['enabled']),
        })

    records = []
    for r in records_rows:
        ss_rows = conn.execute("SELECT filename FROM screenshots WHERE record_id=? ORDER BY ord", (r['id'],)).fetchall()
        records.append({
            'id': r['id'], 'timestamp': r['timestamp'],
            'values': json.loads(r['model_values']) if r['model_values'] else {},
            'screenshots': [s['filename'] for s in ss_rows],
            'result': r['result'], 'closePrice': r['close_price'],
            'closeTime': r['close_time'], 'closeType': r['close_type'],
            'closePnL': r['close_pnl'],
        })
    conn.close()
    return jsonify({'fields': fields, 'records': records})

@app.route('/api/fields', methods=['POST'])
def api_save_fields():
    data = request.get_json(force=True)
    if not isinstance(data, list):
        return jsonify({'error': 'expected array'}), 400
    conn = get_db()
    conn.execute("DELETE FROM fields")
    for i, f in enumerate(data):
        conn.execute(
            "INSERT INTO fields (id, name, type, options, ord, enabled) VALUES (?, ?, ?, ?, ?, ?)",
            (
                f.get('id', 'f_' + str(uuid.uuid4())),
                f['name'],
                f.get('type', 'text'),
                json.dumps(f.get('options', []), ensure_ascii=False),
                i,
                1 if f.get('enabled', True) else 0,
            )
        )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/records', methods=['POST'])
def api_create_record():
    data = request.get_json(force=True)
    rid = data.get('id', 'r_' + str(uuid.uuid4()).replace('-', '')[:16])
    now = datetime.now().isoformat()
    model_values = data.get('values', {})
    screenshots = data.get('screenshots', [])

    conn = get_db()
    conn.execute(
        "INSERT INTO records (id, timestamp, model_values) VALUES (?, ?, ?)",
        (rid, data.get('timestamp', now), json.dumps(model_values, ensure_ascii=False))
    )
    for i, filename in enumerate(screenshots):
        conn.execute(
            "INSERT INTO screenshots (record_id, filename, ord) VALUES (?, ?, ?)",
            (rid, filename, i)
        )
    conn.commit()
    conn.close()
    return jsonify({'id': rid, 'ok': True})

@app.route('/api/records/<record_id>', methods=['PUT'])
def api_close_record(record_id):
    data = request.get_json(force=True)
    conn = get_db()
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE records SET result=?, close_price=?, close_time=?, close_type=?, close_pnl=? WHERE id=?",
        (data.get('result'), data.get('closePrice'), data.get('closeTime', now),
         data.get('closeType'), data.get('closePnL'), record_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/records/<record_id>', methods=['DELETE'])
def api_delete_record(record_id):
    conn = get_db()
    ss = conn.execute("SELECT filename FROM screenshots WHERE record_id=?", (record_id,)).fetchall()
    conn.execute("DELETE FROM records WHERE id=?", (record_id,))
    conn.commit()
    conn.close()
    for s in ss:
        fpath = UPLOAD_DIR / s['filename']
        if fpath.exists():
            fpath.unlink()
    return jsonify({'ok': True})

@app.route('/api/upload', methods=['POST'])
def api_upload():
    if 'file' not in request.files:
        return jsonify({'error': 'no file'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'empty filename'}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'):
        return jsonify({'error': 'unsupported format'}), 400

    filename = f"{uuid.uuid4().hex[:12]}{ext}"
    filepath = UPLOAD_DIR / filename
    file.save(str(filepath))

    # Compress if PIL is available
    try:
        from PIL import Image
        img = Image.open(str(filepath))
        if img.width > 1600 or img.height > 1600:
            img.thumbnail((1600, 1600), Image.LANCZOS)
            img.save(str(filepath), optimize=True, quality=85)
    except ImportError:
        pass

    return jsonify({'filename': filename})

@app.route('/api/export')
def api_export():
    conn = get_db()
    fields_rows = conn.execute("SELECT * FROM fields ORDER BY ord").fetchall()
    records_rows = conn.execute("SELECT * FROM records ORDER BY timestamp DESC").fetchall()

    fields = []
    for f in fields_rows:
        fields.append({
            'id': f['id'], 'name': f['name'], 'type': f['type'],
            'options': json.loads(f['options']) if f['options'] else [],
            'order': f['ord'], 'enabled': bool(f['enabled']),
        })

    records = []
    for r in records_rows:
        ss = conn.execute("SELECT filename FROM screenshots WHERE record_id=? ORDER BY ord", (r['id'],)).fetchall()
        records.append({
            'id': r['id'], 'timestamp': r['timestamp'],
            'values': json.loads(r['model_values']) if r['model_values'] else {},
            'screenshots': [s['filename'] for s in ss],
            'result': r['result'], 'closePrice': r['close_price'],
            'closeTime': r['close_time'], 'closeType': r['close_type'],
            'closePnL': r['close_pnl'],
        })
    conn.close()
    return jsonify({'fields': fields, 'records': records})

@app.route('/api/import', methods=['POST'])
def api_import():
    data = request.get_json(force=True)
    if not data or 'fields' not in data or 'records' not in data:
        return jsonify({'error': 'invalid format'}), 400

    conn = get_db()
    conn.execute("DELETE FROM fields")
    conn.execute("DELETE FROM records")
    conn.execute("DELETE FROM screenshots")

    for i, f in enumerate(data['fields']):
        conn.execute(
            "INSERT INTO fields (id, name, type, options, ord, enabled) VALUES (?, ?, ?, ?, ?, ?)",
            (f.get('id', 'f_'+str(uuid.uuid4())), f['name'], f.get('type','text'),
             json.dumps(f.get('options',[]), ensure_ascii=False), i,
             1 if f.get('enabled', True) else 0)
        )

    for r in data['records']:
        rid = r.get('id', 'r_'+str(uuid.uuid4()).replace('-','')[:16])
        conn.execute(
            "INSERT INTO records (id, timestamp, model_values, result, close_price, close_time, close_type, close_pnl) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, r.get('timestamp',datetime.now().isoformat()),
             json.dumps(r.get('values',{}), ensure_ascii=False),
             r.get('result'), r.get('closePrice'), r.get('closeTime'),
             r.get('closeType'), r.get('closePnL'))
        )
        ss = r.get('screenshots', [])
        if isinstance(ss, list) and len(ss) > 0 and isinstance(ss[0], str) and ss[0].startswith('data:'):
            ss = []
        for i, fname in enumerate(ss):
            conn.execute(
                "INSERT INTO screenshots (record_id, filename, ord) VALUES (?, ?, ?)",
                (rid, fname, i)
            )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ========== Static ==========
@app.route('/uploads/<filename>')
def serve_upload(filename):
    return send_from_directory(str(UPLOAD_DIR), filename)

@app.route('/')
def index():
    html_path = BASE_DIR / 'trade-log.html'
    if not html_path.exists():
        return "trade-log.html not found", 404
    return send_file(str(html_path))

@app.route('/trade-log.html')
def serve_html():
    html_path = BASE_DIR / 'trade-log.html'
    if not html_path.exists():
        return "trade-log.html not found", 404
    return send_file(str(html_path))

# ========== Main ==========
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
init_db()
seed_defaults()

print(f"┌──────────────────────────────────────────")
print(f"│  交易开仓流程记录")
print(f"│")
print(f"│  URL:    {SCHEME}://0.0.0.0:{PORT}")
print(f"│  DB:     {DB_PATH}")
print(f"│  Upload: {UPLOAD_DIR}/")
print(f"│  Mode:   {'Debug' if DEBUG else 'Production'}")
print(f"└──────────────────────────────────────────")

if __name__ == '__main__':
    ssl_ctx = (CERT_FILE, KEY_FILE) if USE_HTTPS else None
    if DEBUG:
        app.run(host=HOST, port=PORT, debug=True, ssl_context=ssl_ctx)
    else:
        # For production, use gunicorn instead:
        # gunicorn -w 1 -b 0.0.0.0:5800 server:app
        print("\n* For production: gunicorn -w 1 -b 0.0.0.0:5800 server:app")
        print("* Or: pip install gunicorn && ./start.sh\n")
        app.run(host=HOST, port=PORT, debug=False, ssl_context=ssl_ctx)
