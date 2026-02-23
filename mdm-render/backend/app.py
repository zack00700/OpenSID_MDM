"""
O.S MDM — Master Data Management — Backend V2
Nouvelles fonctionnalités :
  - Connexion DB externe (PostgreSQL, MySQL, MSSQL, Oracle)
  - Reporting / BI (KPIs, graphiques, tableaux croisés)
  - Règles de fusion Golden Record configurables
  - Audit trail
"""

import os, json, uuid, hashlib, hmac, csv, sqlite3
import jwt, pandas as pd
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import Flask, request, jsonify, g, Response
from io import StringIO, BytesIO

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DB_PATH    = os.path.join(BASE_DIR, '..', 'data', 'mdm.db')
UPLOAD_DIR = os.path.join(BASE_DIR, '..', 'uploads')
SECRET_KEY = os.environ.get('MDM_SECRET', 'os-mdm-v2-secret-change-in-prod')

FRONTEND_DIR_INIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend')
app = Flask(__name__, 
    static_folder=os.path.join(FRONTEND_DIR_INIT, 'static'),
    template_folder=os.path.join(FRONTEND_DIR_INIT, 'templates'))
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
app.config['DB_PATH'] = DB_PATH
import sys, os as _os
sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from maritime import maritime_bp, MARITIME_SCHEMA
app.register_blueprint(maritime_bp, url_prefix='/api/maritime')

import os
from flask import send_from_directory

# ── FRONTEND ROUTES (Render: single service) ──────────────────────────────
FRONTEND_DIR = os.path.join(BASE_DIR, '..', 'frontend')
STATIC_DIR   = os.path.join(FRONTEND_DIR, 'static')
TEMPLATE_DIR = os.path.join(FRONTEND_DIR, 'templates')

@app.route('/')
def serve_index():
    return send_from_directory(TEMPLATE_DIR, 'index.html')

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory(STATIC_DIR, filename)

@app.route('/static/js/<path:filename>')
def serve_js(filename):
    return send_from_directory(os.path.join(STATIC_DIR, 'js'), filename)

@app.route('/static/css/<path:filename>')
def serve_css(filename):
    return send_from_directory(os.path.join(STATIC_DIR, 'css'), filename)

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'version': 'v2.0'})



@app.after_request
def cors(r):
    r.headers['Access-Control-Allow-Origin']  = '*'
    r.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    r.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,OPTIONS'
    return r

@app.before_request
def options_handler():
    if request.method == 'OPTIONS':
        r = Response(); r.status_code = 204
        r.headers['Access-Control-Allow-Origin']  = '*'
        r.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
        r.headers['Access-Control-Allow-Methods'] = 'GET,POST,PUT,DELETE,OPTIONS'
        return r

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# ── PASSWORD ──────────────────────────────────
def hash_pw(pwd):
    salt = os.urandom(16).hex()
    h = hashlib.sha256((salt+pwd).encode()).hexdigest()
    return f"{salt}:{h}"

def check_pw(pwd, stored):
    try:
        salt, h = stored.split(':', 1)
        return hmac.compare_digest(h, hashlib.sha256((salt+pwd).encode()).hexdigest())
    except: return False

# ── DATABASE ──────────────────────────────────
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL, name TEXT, role TEXT DEFAULT 'admin',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS entities (
            id TEXT PRIMARY KEY, mdm_id TEXT UNIQUE, status TEXT DEFAULT 'active',
            source TEXT DEFAULT 'manual', data TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS duplicates (
            id TEXT PRIMARY KEY, entity1_id TEXT, entity2_id TEXT,
            score REAL DEFAULT 0, status TEXT DEFAULT 'pending',
            method TEXT DEFAULT 'exact',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS import_logs (
            id TEXT PRIMARY KEY, filename TEXT, source_label TEXT,
            total_rows INTEGER DEFAULT 0, imported INTEGER DEFAULT 0,
            errors INTEGER DEFAULT 0, status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS golden_records (
            id TEXT PRIMARY KEY, mdm_id TEXT UNIQUE, data TEXT,
            source_ids TEXT, rules_applied TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS db_connections (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, db_type TEXT NOT NULL,
            host TEXT, port INTEGER, database_name TEXT,
            username TEXT, password TEXT, status TEXT DEFAULT 'untested',
            last_tested TEXT, created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS fusion_rules (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, field TEXT NOT NULL,
            strategy TEXT NOT NULL, source_priority TEXT,
            condition_expr TEXT, active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id TEXT PRIMARY KEY, action TEXT, entity_type TEXT,
            entity_id TEXT, user_id TEXT, details TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    cur = db.execute("SELECT id FROM users WHERE email='admin@osmdm.local'")
    if not cur.fetchone():
        db.execute("INSERT INTO users(id,email,password,name,role) VALUES(?,?,?,?,?)",
                   (str(uuid.uuid4()), 'admin@osmdm.local', hash_pw('admin123'), 'Administrateur', 'admin'))
    # Tables maritimes
    db.executescript("""
        CREATE TABLE IF NOT EXISTS maritime_vessels (
            id TEXT PRIMARY KEY, mdm_id TEXT UNIQUE, status TEXT DEFAULT 'active',
            source TEXT DEFAULT 'manual', imo_number TEXT UNIQUE, mmsi TEXT,
            vessel_name TEXT NOT NULL, vessel_name_normalized TEXT, vessel_type TEXT,
            flag_code TEXT, flag_name TEXT, gross_tonnage REAL, deadweight REAL,
            year_built INTEGER, owner_id TEXT, operator TEXT, class_society TEXT,
            data TEXT, validation_errors TEXT, confidence_score REAL DEFAULT 1.0,
            created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS maritime_owners (
            id TEXT PRIMARY KEY, mdm_id TEXT UNIQUE, status TEXT DEFAULT 'active',
            source TEXT DEFAULT 'manual', owner_name TEXT NOT NULL,
            owner_name_normalized TEXT, owner_type TEXT, country_code TEXT,
            country_name TEXT, city TEXT, address TEXT, contact_email TEXT,
            contact_phone TEXT, fleet_size INTEGER DEFAULT 0, data TEXT,
            created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS maritime_ports (
            id TEXT PRIMARY KEY, mdm_id TEXT UNIQUE, status TEXT DEFAULT 'active',
            source TEXT DEFAULT 'manual', port_name TEXT NOT NULL, un_locode TEXT UNIQUE,
            country_code TEXT, country_name TEXT, latitude REAL, longitude REAL,
            port_function TEXT, max_vessel_size TEXT, max_draft REAL,
            tide_dependent INTEGER DEFAULT 0, pilotage_required INTEGER DEFAULT 1, data TEXT,
            created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS maritime_port_calls (
            id TEXT PRIMARY KEY, mdm_id TEXT UNIQUE, status TEXT DEFAULT 'active',
            source TEXT DEFAULT 'manual', vessel_id TEXT, vessel_name TEXT,
            imo_number TEXT, port_id TEXT, port_name TEXT, un_locode TEXT,
            terminal TEXT, berth TEXT, eta TEXT, etd TEXT, ata TEXT, atd TEXT,
            call_status TEXT DEFAULT 'Planned', cargo_type TEXT, cargo_quantity REAL,
            cargo_unit TEXT, agent_name TEXT, voyage_number TEXT, data TEXT,
            created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now'))
        );
    """)
    db.commit(); db.close()

def audit(action, entity_type, entity_id, details=None):
    try:
        db = get_db()
        uid = g.current_user.get('user_id','?') if hasattr(g,'current_user') else '?'
        db.execute("INSERT INTO audit_log(id,action,entity_type,entity_id,user_id,details) VALUES(?,?,?,?,?,?)",
                   (str(uuid.uuid4()), action, entity_type, entity_id, uid, json.dumps(details or {})))
        db.commit()
    except: pass

# ── AUTH ─────────────────────────────────────
def token_required(f):
    @wraps(f)
    def dec(*a, **kw):
        token = request.headers.get('Authorization','').replace('Bearer ','')
        if not token: return jsonify({'error':'Token manquant'}), 401
        try:
            g.current_user = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
        except jwt.ExpiredSignatureError:
            return jsonify({'error':'Token expiré'}), 401
        except: return jsonify({'error':'Token invalide'}), 401
        return f(*a, **kw)
    return dec

@app.route('/api/auth/login', methods=['POST'])
def login():
    b = request.json or {}
    email = b.get('email','').strip().lower()
    pwd   = b.get('password','')
    db = get_db()
    u = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not u or not check_pw(pwd, u['password']):
        return jsonify({'error':'Identifiants invalides'}), 401
    token = jwt.encode({
        'user_id': u['id'], 'email': u['email'], 'role': u['role'],
        'exp': datetime.now(timezone.utc) + timedelta(hours=12)
    }, SECRET_KEY, algorithm='HS256')
    return jsonify({'token': token, 'user': {'id':u['id'],'email':u['email'],'name':u['name'],'role':u['role']}})

@app.route('/api/auth/me', methods=['GET'])
@token_required
def me():
    u = get_db().execute("SELECT id,email,name,role,created_at FROM users WHERE id=?",
                          (g.current_user['user_id'],)).fetchone()
    return jsonify(dict(u)) if u else (jsonify({'error':'Introuvable'}), 404)

# ── DASHBOARD ────────────────────────────────
@app.route('/api/dashboard/stats', methods=['GET'])
@token_required
def dashboard_stats():
    db = get_db()
    total_e  = db.execute("SELECT COUNT(*) FROM entities WHERE status='active'").fetchone()[0]
    total_d  = db.execute("SELECT COUNT(*) FROM duplicates WHERE status='pending'").fetchone()[0]
    total_g  = db.execute("SELECT COUNT(*) FROM golden_records").fetchone()[0]
    total_i  = db.execute("SELECT COUNT(*) FROM import_logs").fetchone()[0]
    total_cn = db.execute("SELECT COUNT(*) FROM db_connections WHERE status='ok'").fetchone()[0]
    total_r  = db.execute("SELECT COUNT(*) FROM fusion_rules WHERE active=1").fetchone()[0]
    recent   = db.execute("SELECT id,source,created_at,data FROM entities WHERE status='active' ORDER BY created_at DESC LIMIT 5").fetchall()
    sources  = db.execute("SELECT source, COUNT(*) as cnt FROM entities WHERE status='active' GROUP BY source ORDER BY cnt DESC LIMIT 10").fetchall()
    trend    = db.execute("""SELECT DATE(created_at) as day, SUM(imported) as total FROM import_logs
                             WHERE created_at >= date('now','-7 days') GROUP BY day ORDER BY day""").fetchall()
    return jsonify({
        'total_entities': total_e, 'total_duplicates': total_d,
        'total_golden': total_g, 'total_imports': total_i,
        'total_connections': total_cn, 'total_rules': total_r,
        'recent_entities': [dict(r) for r in recent],
        'sources_breakdown': [dict(s) for s in sources],
        'import_trend': [dict(t) for t in trend],
    })

# ── IMPORT ───────────────────────────────────
@app.route('/api/import/csv', methods=['POST'])
@token_required
def import_csv():
    if 'file' not in request.files:
        return jsonify({'error':'Aucun fichier'}), 400
    file = request.files['file']
    source_label = request.form.get('source_label', file.filename)
    ext = file.filename.rsplit('.',1)[-1].lower() if '.' in file.filename else ''
    log_id = str(uuid.uuid4())
    db = get_db()
    db.execute("INSERT INTO import_logs(id,filename,source_label,status) VALUES(?,?,?,'processing')",
               (log_id, file.filename, source_label))
    db.commit()
    try:
        if ext == 'csv':
            content = file.read().decode('utf-8-sig', errors='replace')
            df = pd.read_csv(StringIO(content))
        elif ext in ('xlsx','xls'):
            df = pd.read_excel(BytesIO(file.read()))
        else:
            return jsonify({'error':'Format non supporté'}), 400
        df = df.where(pd.notnull(df), None)
        total = len(df); imported = 0; errors = 0
        for _, row in df.iterrows():
            try:
                eid = str(uuid.uuid4())
                db.execute("INSERT INTO entities(id,mdm_id,status,source,data) VALUES(?,?,'active',?,?)",
                           (eid, 'MDM-'+eid[:8].upper(), source_label,
                            json.dumps(row.to_dict(), ensure_ascii=False, default=str)))
                imported += 1
            except: errors += 1
        db.execute("UPDATE import_logs SET total_rows=?,imported=?,errors=?,status='done' WHERE id=?",
                   (total, imported, errors, log_id))
        db.commit()
        audit('import', 'import_log', log_id, {'file': file.filename, 'imported': imported})
        return jsonify({'log_id':log_id,'total':total,'imported':imported,'errors':errors})
    except Exception as e:
        db.execute("UPDATE import_logs SET status='error' WHERE id=?", (log_id,))
        db.commit()
        return jsonify({'error': str(e)}), 500

@app.route('/api/import/logs', methods=['GET'])
@token_required
def import_logs():
    logs = get_db().execute("SELECT * FROM import_logs ORDER BY created_at DESC LIMIT 50").fetchall()
    return jsonify([dict(l) for l in logs])

# ── ENTITIES ─────────────────────────────────
@app.route('/api/entities', methods=['GET'])
@token_required
def list_entities():
    db = get_db()
    page = int(request.args.get('page',1))
    per  = int(request.args.get('per_page',20))
    srch = request.args.get('search','').strip()
    src  = request.args.get('source','').strip()
    off  = (page-1)*per
    wh   = ["status='active'"]; params = []
    if srch: wh.append("data LIKE ?"); params.append(f'%{srch}%')
    if src:  wh.append("source LIKE ?"); params.append(f'%{src}%')
    w = ' AND '.join(wh)
    total = db.execute(f"SELECT COUNT(*) FROM entities WHERE {w}", params).fetchone()[0]
    rows  = db.execute(f"SELECT * FROM entities WHERE {w} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                       params+[per,off]).fetchall()
    ents = []
    for r in rows:
        e = dict(r)
        try: e['data'] = json.loads(e['data'])
        except: pass
        ents.append(e)
    return jsonify({'total':total,'page':page,'per_page':per,'entities':ents})

@app.route('/api/entities/<eid>', methods=['GET'])
@token_required
def get_entity(eid):
    r = get_db().execute("SELECT * FROM entities WHERE id=?", (eid,)).fetchone()
    if not r: return jsonify({'error':'Introuvable'}), 404
    e = dict(r)
    try: e['data'] = json.loads(e['data'])
    except: pass
    return jsonify(e)

@app.route('/api/entities', methods=['POST'])
@token_required
def create_entity():
    b = request.json or {}
    eid = str(uuid.uuid4())
    mid = 'MDM-'+eid[:8].upper()
    db  = get_db()
    db.execute("INSERT INTO entities(id,mdm_id,status,source,data) VALUES(?,?,'active','manual',?)",
               (eid, mid, json.dumps(b.get('data',{}), ensure_ascii=False)))
    db.commit()
    audit('create','entity',eid)
    return jsonify({'id':eid,'mdm_id':mid}), 201

@app.route('/api/entities/<eid>', methods=['PUT'])
@token_required
def update_entity(eid):
    b = request.json or {}
    db = get_db()
    if not db.execute("SELECT id FROM entities WHERE id=?", (eid,)).fetchone():
        return jsonify({'error':'Introuvable'}), 404
    db.execute("UPDATE entities SET data=?,updated_at=datetime('now') WHERE id=?",
               (json.dumps(b.get('data',{}), ensure_ascii=False), eid))
    db.commit()
    audit('update','entity',eid)
    return jsonify({'message':'Mis à jour'})

@app.route('/api/entities/<eid>', methods=['DELETE'])
@token_required
def delete_entity(eid):
    db = get_db()
    db.execute("UPDATE entities SET status='deleted' WHERE id=?", (eid,))
    db.commit()
    audit('delete','entity',eid)
    return jsonify({'message':'Supprimé'})

# ── DB CONNECTIONS ────────────────────────────
def _make_conn(info):
    db_type = info['db_type'].lower()
    h = info.get('host','localhost')
    p = info.get('port')
    db_name = info.get('database_name','')
    user = info.get('username','')
    pwd  = info.get('password','')
    if db_type == 'postgresql':
        import psycopg2
        return psycopg2.connect(host=h, port=p or 5432, dbname=db_name, user=user, password=pwd, connect_timeout=10)
    elif db_type in ('mysql','mariadb'):
        import pymysql
        return pymysql.connect(host=h, port=int(p or 3306), database=db_name, user=user, password=pwd, connect_timeout=10)
    elif db_type == 'mssql':
        import pyodbc
        return pyodbc.connect(f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={h},{p or 1433};DATABASE={db_name};UID={user};PWD={pwd};timeout=10")
    elif db_type == 'oracle':
        import cx_Oracle
        dsn = cx_Oracle.makedsn(h, p or 1521, service_name=db_name)
        return cx_Oracle.connect(user=user, password=pwd, dsn=dsn)
    else:
        import sqlite3 as _sq
        return _sq.connect(db_name)

@app.route('/api/connections', methods=['GET'])
@token_required
def list_connections():
    rows = get_db().execute("SELECT id,name,db_type,host,port,database_name,username,status,last_tested,created_at FROM db_connections ORDER BY created_at DESC").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/connections', methods=['POST'])
@token_required
def create_connection():
    b = request.json or {}
    cid = str(uuid.uuid4())
    get_db().execute("INSERT INTO db_connections(id,name,db_type,host,port,database_name,username,password,status) VALUES(?,?,?,?,?,?,?,?,'untested')",
               (cid, b.get('name'), b.get('db_type'), b.get('host'), b.get('port'),
                b.get('database_name'), b.get('username'), b.get('password','')))
    get_db().commit()
    return jsonify({'id': cid}), 201

@app.route('/api/connections/<cid>', methods=['PUT'])
@token_required
def update_connection(cid):
    b = request.json or {}
    db = get_db()
    db.execute("UPDATE db_connections SET name=?,db_type=?,host=?,port=?,database_name=?,username=?,password=? WHERE id=?",
               (b.get('name'), b.get('db_type'), b.get('host'), b.get('port'),
                b.get('database_name'), b.get('username'), b.get('password',''), cid))
    db.commit()
    return jsonify({'message':'Mis à jour'})

@app.route('/api/connections/<cid>', methods=['DELETE'])
@token_required
def delete_connection(cid):
    get_db().execute("DELETE FROM db_connections WHERE id=?", (cid,))
    get_db().commit()
    return jsonify({'message':'Supprimé'})

@app.route('/api/connections/<cid>/test', methods=['POST'])
@token_required
def test_connection(cid):
    db  = get_db()
    row = db.execute("SELECT * FROM db_connections WHERE id=?", (cid,)).fetchone()
    if not row: return jsonify({'error':'Introuvable'}), 404
    try:
        conn = _make_conn(dict(row))
        conn.cursor().execute("SELECT 1")
        conn.close()
        db.execute("UPDATE db_connections SET status='ok', last_tested=datetime('now') WHERE id=?", (cid,))
        db.commit()
        return jsonify({'status':'ok', 'message':'Connexion réussie ✅'})
    except Exception as e:
        db.execute("UPDATE db_connections SET status='error', last_tested=datetime('now') WHERE id=?", (cid,))
        db.commit()
        return jsonify({'status':'error', 'message': str(e)}), 400

@app.route('/api/connections/<cid>/tables', methods=['GET'])
@token_required
def list_tables(cid):
    row = get_db().execute("SELECT * FROM db_connections WHERE id=?", (cid,)).fetchone()
    if not row: return jsonify({'error':'Introuvable'}), 404
    try:
        conn = _make_conn(dict(row))
        cur  = conn.cursor()
        db_type = row['db_type'].lower()
        if db_type == 'postgresql':
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
        elif db_type in ('mysql','mariadb'):
            cur.execute("SHOW TABLES")
        elif db_type == 'mssql':
            cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'")
        elif db_type == 'oracle':
            cur.execute("SELECT table_name FROM user_tables ORDER BY table_name")
        else:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        conn.close()
        return jsonify({'tables': tables})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/connections/<cid>/preview', methods=['POST'])
@token_required
def preview_table(cid):
    row = get_db().execute("SELECT * FROM db_connections WHERE id=?", (cid,)).fetchone()
    if not row: return jsonify({'error':'Introuvable'}), 404
    table = (request.json or {}).get('table','')
    if not table: return jsonify({'error':'Table requise'}), 400
    if not all(c.isalnum() or c in '_.' for c in table):
        return jsonify({'error':'Nom de table invalide'}), 400
    try:
        conn = _make_conn(dict(row))
        df   = pd.read_sql(f'SELECT * FROM "{table}" LIMIT 20', conn)
        conn.close()
        return jsonify({'columns': list(df.columns), 'rows': df.fillna('').to_dict(orient='records')})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/connections/<cid>/import', methods=['POST'])
@token_required
def import_from_db(cid):
    row = get_db().execute("SELECT * FROM db_connections WHERE id=?", (cid,)).fetchone()
    if not row: return jsonify({'error':'Introuvable'}), 404
    b     = request.json or {}
    table = b.get('table','')
    query = b.get('query','')
    limit = int(b.get('limit', 10000))
    if not table and not query: return jsonify({'error':'Table ou SQL requis'}), 400
    if not query:
        if not all(c.isalnum() or c in '_.' for c in table):
            return jsonify({'error':'Nom de table invalide'}), 400
        query = f'SELECT * FROM "{table}" LIMIT {limit}'
    source_label = b.get('source_label') or f"{row['name']}.{table or 'query'}"
    log_id = str(uuid.uuid4())
    db = get_db()
    db.execute("INSERT INTO import_logs(id,filename,source_label,status) VALUES(?,?,?,'processing')",
               (log_id, f"[DB] {source_label}", source_label))
    db.commit()
    try:
        conn = _make_conn(dict(row))
        df   = pd.read_sql(query, conn)
        conn.close()
        df = df.where(pd.notnull(df), None)
        total = len(df); imported = 0; errors = 0
        for _, row_data in df.iterrows():
            try:
                eid = str(uuid.uuid4())
                db.execute("INSERT INTO entities(id,mdm_id,status,source,data) VALUES(?,?,'active',?,?)",
                           (eid, 'MDM-'+eid[:8].upper(), source_label,
                            json.dumps(row_data.to_dict(), ensure_ascii=False, default=str)))
                imported += 1
            except: errors += 1
        db.execute("UPDATE import_logs SET total_rows=?,imported=?,errors=?,status='done' WHERE id=?",
                   (total, imported, errors, log_id))
        db.commit()
        audit('db_import','import_log',log_id,{'source':source_label,'imported':imported})
        return jsonify({'log_id':log_id,'total':total,'imported':imported,'errors':errors})
    except Exception as e:
        db.execute("UPDATE import_logs SET status='error' WHERE id=?", (log_id,))
        db.commit()
        return jsonify({'error': str(e)}), 500

# ── DUPLICATES ───────────────────────────────
def normalize(v): return str(v or '').strip().lower()

@app.route('/api/duplicates/detect', methods=['POST'])
@token_required
def detect_duplicates():
    b = request.json or {}
    fields = b.get('fields', [])
    method = b.get('method', 'exact')
    db = get_db()
    db.execute("DELETE FROM duplicates WHERE status='pending'"); db.commit()
    rows = db.execute("SELECT id,data FROM entities WHERE status='active'").fetchall()
    entities = []
    for r in rows:
        try: d = json.loads(r['data'])
        except: d = {}
        entities.append({'id': r['id'], 'data': d})
    pairs = []; found = 0
    if method == 'exact':
        from collections import defaultdict
        groups = defaultdict(list)
        for e in entities:
            parts = [normalize(e['data'].get(f,'')) for f in fields] if fields else \
                    [normalize(v) for v in e['data'].values() if isinstance(v,(str,int,float))]
            key = '|'.join(parts)
            if any(p.strip() for p in parts): groups[key].append(e['id'])
        for key, ids in groups.items():
            if len(ids) > 1:
                for i in range(len(ids)):
                    for j in range(i+1,len(ids)):
                        pairs.append((ids[i],ids[j],1.0,'exact'))
    elif method == 'fuzzy':
        try: from thefuzz import fuzz
        except: return jsonify({'error':'thefuzz non installé'}), 500
        threshold = int(b.get('threshold',80))
        for i in range(len(entities)):
            for j in range(i+1,len(entities)):
                e1,e2 = entities[i],entities[j]
                if fields:
                    scores = [fuzz.ratio(normalize(e1['data'].get(f,'')), normalize(e2['data'].get(f,'')))
                              for f in fields if e1['data'].get(f) and e2['data'].get(f)]
                    score = sum(scores)/len(scores) if scores else 0
                else:
                    s1=' '.join(normalize(v) for v in e1['data'].values() if isinstance(v,(str,int,float)))
                    s2=' '.join(normalize(v) for v in e2['data'].values() if isinstance(v,(str,int,float)))
                    score = fuzz.token_sort_ratio(s1,s2)
                if score >= threshold: pairs.append((e1['id'],e2['id'],score/100.0,'fuzzy'))
    for e1id,e2id,score,meth in pairs:
        try:
            db.execute("INSERT INTO duplicates(id,entity1_id,entity2_id,score,status,method) VALUES(?,?,?,?,'pending',?)",
                       (str(uuid.uuid4()),e1id,e2id,score,meth)); found+=1
        except: pass
    db.commit()
    return jsonify({'found':found,'method':method})

@app.route('/api/duplicates', methods=['GET'])
@token_required
def list_duplicates():
    db = get_db()
    status = request.args.get('status','pending')
    rows = db.execute("SELECT * FROM duplicates WHERE status=? ORDER BY score DESC",(status,)).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        for key in ('entity1_id','entity2_id'):
            alias = key.replace('_id','')
            e = db.execute("SELECT id,mdm_id,data,source FROM entities WHERE id=?",(d[key],)).fetchone()
            if e:
                try: data=json.loads(e['data'])
                except: data={}
                d[alias]={'id':e['id'],'mdm_id':e['mdm_id'],'data':data,'source':e['source']}
        result.append(d)
    return jsonify(result)

@app.route('/api/duplicates/ignore', methods=['POST'])
@token_required
def ignore_duplicate():
    dup_id=(request.json or {}).get('duplicate_id')
    if not dup_id: return jsonify({'error':'duplicate_id requis'}),400
    get_db().execute("UPDATE duplicates SET status='ignored' WHERE id=?",(dup_id,))
    get_db().commit()
    return jsonify({'message':'Ignoré'})

# ── FUSION RULES ─────────────────────────────
@app.route('/api/fusion-rules', methods=['GET'])
@token_required
def list_rules():
    rows=get_db().execute("SELECT * FROM fusion_rules ORDER BY created_at DESC").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/fusion-rules', methods=['POST'])
@token_required
def create_rule():
    b=request.json or {}
    rid=str(uuid.uuid4())
    get_db().execute("INSERT INTO fusion_rules(id,name,field,strategy,source_priority,condition_expr,active) VALUES(?,?,?,?,?,?,1)",
               (rid,b.get('name'),b.get('field'),b.get('strategy','most_complete'),
                json.dumps(b.get('source_priority',[])),b.get('condition_expr','')))
    get_db().commit()
    return jsonify({'id':rid}),201

@app.route('/api/fusion-rules/<rid>', methods=['PUT'])
@token_required
def update_rule(rid):
    b=request.json or {}
    get_db().execute("UPDATE fusion_rules SET name=?,field=?,strategy=?,source_priority=?,condition_expr=?,active=? WHERE id=?",
               (b.get('name'),b.get('field'),b.get('strategy'),
                json.dumps(b.get('source_priority',[])),b.get('condition_expr',''),int(b.get('active',1)),rid))
    get_db().commit()
    return jsonify({'message':'Mis à jour'})

@app.route('/api/fusion-rules/<rid>', methods=['DELETE'])
@token_required
def delete_rule(rid):
    get_db().execute("DELETE FROM fusion_rules WHERE id=?",(rid,))
    get_db().commit()
    return jsonify({'message':'Supprimé'})

@app.route('/api/fusion-rules/preview', methods=['POST'])
@token_required
def preview_rules():
    b=request.json or {}
    e1=b.get('entity1',{})
    e2=b.get('entity2',{})
    db=get_db()
    rules=db.execute("SELECT * FROM fusion_rules WHERE active=1 ORDER BY created_at").fetchall()
    all_keys=list(set(list(e1.keys())+list(e2.keys())))
    result={}; applied=[]
    for key in all_keys:
        v1=e1.get(key,''); v2=e2.get(key,'')
        chosen=v1; rule_used=None
        for rule in rules:
            r=dict(rule)
            if r['field']!=key and r['field']!='*': continue
            strat=r['strategy']
            if strat=='most_complete':
                chosen=v1 if len(str(v1 or ''))>=len(str(v2 or '')) else v2
            elif strat=='source_priority':
                try:
                    prio=json.loads(r['source_priority'] or '[]')
                    src1=e1.get('_source',''); src2=e2.get('_source','')
                    i1=prio.index(src1) if src1 in prio else 99
                    i2=prio.index(src2) if src2 in prio else 99
                    chosen=v1 if i1<=i2 else v2
                except: chosen=v1
            elif strat=='always_entity1': chosen=v1
            elif strat=='always_entity2': chosen=v2
            elif strat=='non_empty': chosen=v1 if v1 and str(v1).strip() else v2
            elif strat=='longest': chosen=v1 if len(str(v1 or ''))>=len(str(v2 or '')) else v2
            rule_used=r['name']; break
        result[key]=chosen
        applied.append({'field':key,'v1':v1,'v2':v2,'chosen':chosen,'rule':rule_used or 'défaut (entité 1)'})
    return jsonify({'merged':result,'applied':applied})

# ── GOLDEN RECORDS ────────────────────────────
@app.route('/api/golden-records/merge', methods=['POST'])
@token_required
def merge_entities():
    b=request.json or {}
    entity_ids=b.get('entity_ids',[])
    merged_data=b.get('merged_data',{})
    dup_id=b.get('duplicate_id')
    rules_used=b.get('rules_applied',[])
    if len(entity_ids)<2: return jsonify({'error':'Au moins 2 entités requises'}),400
    db=get_db()
    gid=str(uuid.uuid4()); mid='GR-'+gid[:8].upper()
    db.execute("INSERT INTO golden_records(id,mdm_id,data,source_ids,rules_applied) VALUES(?,?,?,?,?)",
               (gid,mid,json.dumps(merged_data,ensure_ascii=False),
                json.dumps(entity_ids),json.dumps(rules_used)))
    for eid in entity_ids:
        db.execute("UPDATE entities SET status='merged' WHERE id=?",(eid,))
    if dup_id:
        db.execute("UPDATE duplicates SET status='resolved' WHERE id=?",(dup_id,))
    db.commit()
    audit('merge','golden_record',gid,{'sources':entity_ids})
    return jsonify({'golden_record_id':gid,'mdm_id':mid}),201

@app.route('/api/golden-records', methods=['GET'])
@token_required
def list_golden_records():
    rows=get_db().execute("SELECT * FROM golden_records ORDER BY created_at DESC").fetchall()
    result=[]
    for r in rows:
        gr=dict(r)
        for k in ('data','source_ids','rules_applied'):
            try: gr[k]=json.loads(gr[k])
            except: pass
        result.append(gr)
    return jsonify(result)

# ── REPORTING ────────────────────────────────
@app.route('/api/reporting/overview', methods=['GET'])
@token_required
def reporting_overview():
    db=get_db()
    total_e   =db.execute("SELECT COUNT(*) FROM entities WHERE status='active'").fetchone()[0]
    total_mer =db.execute("SELECT COUNT(*) FROM entities WHERE status='merged'").fetchone()[0]
    total_del =db.execute("SELECT COUNT(*) FROM entities WHERE status='deleted'").fetchone()[0]
    total_dup =db.execute("SELECT COUNT(*) FROM duplicates WHERE status='pending'").fetchone()[0]
    total_res =db.execute("SELECT COUNT(*) FROM duplicates WHERE status='resolved'").fetchone()[0]
    total_ign =db.execute("SELECT COUNT(*) FROM duplicates WHERE status='ignored'").fetchone()[0]
    total_gr  =db.execute("SELECT COUNT(*) FROM golden_records").fetchone()[0]
    total_i   =db.execute("SELECT COUNT(*) FROM import_logs WHERE status='done'").fetchone()[0]
    total_rows=db.execute("SELECT COALESCE(SUM(imported),0) FROM import_logs WHERE status='done'").fetchone()[0]
    dup_rate  =round(total_dup/max(total_e,1)*100,1)
    coverage  =round(total_gr/max(total_e+total_mer,1)*100,1)
    by_source =db.execute("SELECT source,COUNT(*) as count FROM entities WHERE status IN ('active','merged') GROUP BY source ORDER BY count DESC").fetchall()
    import_trend=db.execute("SELECT DATE(created_at) as day,COUNT(*) as imports,COALESCE(SUM(imported),0) as rows FROM import_logs WHERE status='done' AND created_at>=date('now','-30 days') GROUP BY day ORDER BY day").fetchall()
    dup_trend   =db.execute("SELECT DATE(created_at) as day,COUNT(*) as found FROM duplicates WHERE created_at>=date('now','-30 days') GROUP BY day ORDER BY day").fetchall()
    gr_trend    =db.execute("SELECT DATE(created_at) as day,COUNT(*) as created FROM golden_records WHERE created_at>=date('now','-30 days') GROUP BY day ORDER BY day").fetchall()
    top_sources =db.execute("SELECT source_label,SUM(imported) as total_rows FROM import_logs WHERE status='done' GROUP BY source_label ORDER BY total_rows DESC LIMIT 10").fetchall()
    status_dist =db.execute("SELECT status,COUNT(*) as count FROM entities GROUP BY status").fetchall()
    return jsonify({
        'kpis':{'total_entities':total_e,'total_merged':total_mer,'total_deleted':total_del,
                'total_duplicates_pending':total_dup,'total_duplicates_resolved':total_res,
                'total_duplicates_ignored':total_ign,'total_golden_records':total_gr,
                'total_imports':total_i,'total_rows_imported':total_rows,
                'duplicate_rate':dup_rate,'golden_coverage':coverage},
        'by_source':[dict(r) for r in by_source],
        'import_trend':[dict(r) for r in import_trend],
        'dup_trend':[dict(r) for r in dup_trend],
        'gr_trend':[dict(r) for r in gr_trend],
        'top_sources':[dict(r) for r in top_sources],
        'status_dist':[dict(r) for r in status_dist],
    })

@app.route('/api/reporting/pivot', methods=['POST'])
@token_required
def pivot_table():
    b=request.json or {}
    row_f=b.get('row_field'); col_f=b.get('col_field')
    agg=b.get('aggregation','count'); val_f=b.get('value_field')
    src=b.get('source','')
    if not row_f: return jsonify({'error':'row_field requis'}),400
    db=get_db()
    wh="status IN ('active','merged')"; params=[]
    if src: wh+=" AND source LIKE ?"; params.append(f'%{src}%')
    rows=db.execute(f"SELECT data,source FROM entities WHERE {wh}",params).fetchall()
    data=[]
    for r in rows:
        try: d=json.loads(r['data']); d['_source']=r['source']
        except: d={}
        data.append(d)
    if not data: return jsonify({'pivot':[],'columns':[],'rows':[]})
    df=pd.DataFrame(data)
    if row_f not in df.columns: return jsonify({'error':f"Champ '{row_f}' introuvable"}),400
    try:
        if col_f and col_f in df.columns:
            if agg=='count':
                piv=pd.crosstab(df[row_f],df[col_f])
            else:
                if not val_f or val_f not in df.columns: return jsonify({'error':f"value_field requis"}),400
                df[val_f]=pd.to_numeric(df[val_f],errors='coerce')
                piv=df.pivot_table(index=row_f,columns=col_f,values=val_f,aggfunc=agg,fill_value=0)
            piv=piv.reset_index()
            return jsonify({'pivot':piv.fillna(0).to_dict(orient='records'),'columns':list(piv.columns),'row_field':row_f,'col_field':col_f})
        else:
            if agg=='count':
                series=df[row_f].value_counts().reset_index(); series.columns=[row_f,'count']
            else:
                if not val_f or val_f not in df.columns: return jsonify({'error':'value_field requis'}),400
                df[val_f]=pd.to_numeric(df[val_f],errors='coerce')
                series=df.groupby(row_f)[val_f].agg(agg).reset_index(); series.columns=[row_f,agg]
            return jsonify({'pivot':series.fillna(0).to_dict(orient='records'),'columns':list(series.columns),'row_field':row_f})
    except Exception as e: return jsonify({'error':str(e)}),500

@app.route('/api/reporting/fields', methods=['GET'])
@token_required
def get_all_fields():
    rows=get_db().execute("SELECT data FROM entities WHERE status IN ('active','merged') LIMIT 300").fetchall()
    fields=set()
    for r in rows:
        try: fields.update(json.loads(r['data']).keys())
        except: pass
    return jsonify({'fields':sorted(fields)})

# ── EXPORT ───────────────────────────────────
@app.route('/api/export/csv', methods=['GET'])
@token_required
def export_csv():
    db=get_db(); params=[]
    include_merged=request.args.get('include_merged','false')=='true'
    source_filter=request.args.get('source','')
    q="SELECT * FROM entities WHERE status='active'"
    if include_merged: q="SELECT * FROM entities WHERE status IN ('active','merged')"
    if source_filter: q+=" AND source LIKE ?"; params.append(f'%{source_filter}%')
    rows=db.execute(q+' ORDER BY created_at DESC',params).fetchall()
    if not rows: return jsonify({'error':'Aucune entité'}),404
    all_data=[]; all_keys=set()
    for r in rows:
        e=dict(r)
        try: data=json.loads(e['data'])
        except: data={}
        flat={'_id':e['id'],'_mdm_id':e['mdm_id'],'_status':e['status'],'_source':e['source'],'_created_at':e['created_at']}
        flat.update(data); all_keys.update(data.keys()); all_data.append(flat)
    output=StringIO()
    fn=['_id','_mdm_id','_status','_source','_created_at']+sorted(all_keys)
    w=csv.DictWriter(output,fieldnames=fn,extrasaction='ignore')
    w.writeheader(); w.writerows(all_data)
    return Response(output.getvalue(),mimetype='text/csv',
                    headers={'Content-Disposition':f'attachment;filename=osmdm_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'})

@app.route('/api/export/golden-records/csv', methods=['GET'])
@token_required
def export_golden_csv():
    rows=get_db().execute("SELECT * FROM golden_records ORDER BY created_at DESC").fetchall()
    all_data=[]; all_keys=set()
    for r in rows:
        gr=dict(r)
        try: data=json.loads(gr['data'])
        except: data={}
        flat={'_id':gr['id'],'_mdm_id':gr['mdm_id'],'_created_at':gr['created_at']}
        flat.update(data); all_keys.update(data.keys()); all_data.append(flat)
    output=StringIO()
    fn=['_id','_mdm_id','_created_at']+sorted(all_keys)
    w=csv.DictWriter(output,fieldnames=fn,extrasaction='ignore')
    w.writeheader(); w.writerows(all_data)
    return Response(output.getvalue(),mimetype='text/csv',
                    headers={'Content-Disposition':f'attachment;filename=golden_records_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'})

# ── AUDIT ────────────────────────────────────
@app.route('/api/audit', methods=['GET'])
@token_required
def get_audit():
    logs=get_db().execute("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 100").fetchall()
    return jsonify([dict(l) for l in logs])

# ── USERS ────────────────────────────────────
@app.route('/api/users', methods=['GET'])
@token_required
def list_users():
    rows=get_db().execute("SELECT id,email,name,role,created_at FROM users").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/users', methods=['POST'])
@token_required
def create_user():
    b=request.json or {}; uid=str(uuid.uuid4())
    get_db().execute("INSERT INTO users(id,email,password,name,role) VALUES(?,?,?,?,?)",
               (uid,b['email'],hash_pw(b.get('password','changeme')),b.get('name',''),b.get('role','admin')))
    get_db().commit()
    return jsonify({'id':uid}),201

if __name__=='__main__':
    init_db()
    print("\n✅  O.S MDM V2 — Backend démarré !")
    print("📋  Admin : admin@osmdm.local / admin123")
    print("🌐  API   : http://localhost:5001/api\n")
    app.run(host='127.0.0.1', debug=True, port=5001, use_reloader=False)
