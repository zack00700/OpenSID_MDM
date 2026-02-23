"""
O.S MDM V2 — Module Maritime
Gestion des entités : Navires, Escales, Armateurs, Ports & Terminaux
Standards : IMO, MMSI, UN/LOCODE, BIMCO
"""

import json, uuid, re
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from functools import wraps

maritime_bp = Blueprint('maritime', __name__)

# ── STANDARDS & RÉFÉRENTIELS ───────────────────────────────────────────────

VESSEL_TYPES = [
    'Bulk Carrier', 'Container Ship', 'Tanker', 'General Cargo',
    'Ro-Ro', 'Passenger', 'Ferry', 'Tug', 'Offshore Supply',
    'Chemical Tanker', 'LNG Carrier', 'LPG Carrier', 'Dredger',
    'Fishing Vessel', 'Research Vessel', 'Yacht', 'Barge', 'Other'
]

FLAGS = {
    'PA': 'Panama', 'LR': 'Liberia', 'MH': 'Marshall Islands', 'HK': 'Hong Kong',
    'SG': 'Singapore', 'BS': 'Bahamas', 'MT': 'Malta', 'CY': 'Cyprus',
    'CN': 'China', 'GB': 'United Kingdom', 'NO': 'Norway', 'GR': 'Greece',
    'JP': 'Japan', 'KR': 'South Korea', 'IT': 'Italy', 'DE': 'Germany',
    'FR': 'France', 'US': 'United States', 'NL': 'Netherlands', 'DK': 'Denmark',
    'MA': 'Morocco', 'DZ': 'Algeria', 'TN': 'Tunisia', 'EG': 'Egypt',
    'NG': 'Nigeria', 'ZA': 'South Africa', 'AE': 'UAE', 'IN': 'India',
    'BR': 'Brazil', 'ES': 'Spain', 'PT': 'Portugal', 'TR': 'Turkey',
    'RU': 'Russia', 'BE': 'Belgium', 'SE': 'Sweden', 'FI': 'Finland',
}

PORT_FUNCTIONS = [
    'Port of Loading', 'Port of Discharge', 'Transhipment Hub',
    'Bunkering Port', 'Port of Refuge', 'Anchorage', 'Dry Dock',
    'River Port', 'Lake Port', 'Canal Port'
]

CALL_STATUSES = ['Planned', 'In Transit', 'At Anchor', 'Berthed', 'Departed', 'Cancelled']
CARGO_TYPES = ['Dry Bulk', 'Liquid Bulk', 'Container', 'Ro-Ro', 'General Cargo',
               'Project Cargo', 'Refrigerated', 'Hazardous', 'Passengers', 'Ballast', 'Other']

# ── VALIDATION RULES (règles MDM maritimes) ───────────────────────────────

def validate_imo(imo_raw):
    """
    Validation IMO number — standard international (IMO Res. A.600(15))
    Format : IMO + 7 chiffres, dernier = checkdigit
    Ex: IMO9321483
    """
    if not imo_raw:
        return None, 'IMO manquant'
    imo = str(imo_raw).strip().upper().replace(' ', '')
    if not imo.startswith('IMO'):
        imo = 'IMO' + imo
    digits = imo[3:]
    if not digits.isdigit() or len(digits) != 7:
        return None, f"IMO invalide '{imo_raw}' — doit être 7 chiffres après IMO"
    # Checksum IMO
    total = sum(int(d) * (7 - i) for i, d in enumerate(digits[:6]))
    if total % 10 != int(digits[6]):
        return None, f"Checksum IMO invalide pour '{imo}'"
    return imo, None

def validate_mmsi(mmsi_raw):
    """
    MMSI — Maritime Mobile Service Identity
    Format : 9 chiffres, commence par 2-7
    """
    if not mmsi_raw:
        return None, None  # optionnel
    mmsi = str(mmsi_raw).strip().replace(' ', '')
    if not mmsi.isdigit() or len(mmsi) != 9:
        return None, f"MMSI invalide '{mmsi_raw}' — doit être exactement 9 chiffres"
    if mmsi[0] not in '234567':
        return None, f"MMSI invalide — premier chiffre doit être entre 2 et 7"
    return mmsi, None

def validate_locode(locode_raw):
    """
    UN/LOCODE — identifiant port international
    Format : 2 lettres pays + espace + 3 lettres/chiffres
    Ex: MACAO, FRPAR, NLRTM (Rotterdam)
    """
    if not locode_raw:
        return None, 'UN/LOCODE manquant'
    raw = str(locode_raw).strip().upper().replace(' ', '')
    if len(raw) == 5:
        locode = raw[:2] + ' ' + raw[2:]
    else:
        locode = str(locode_raw).strip().upper()
    parts = locode.split()
    if len(parts) != 2 or len(parts[0]) != 2 or len(parts[1]) != 3:
        return None, f"UN/LOCODE invalide '{locode_raw}' — format attendu: XX YYY (ex: MA AGD)"
    if not parts[0].isalpha():
        return None, f"Code pays invalide dans UN/LOCODE '{locode_raw}'"
    return locode, None

def normalize_vessel_name(name):
    """
    Normalisation nom navire pour MDM matching
    Supprime les préfixes standard (MV, MS, SS, MT, etc.)
    """
    if not name:
        return ''
    prefixes = ['MV ', 'MS ', 'SS ', 'MT ', 'M/V ', 'M/T ', 'M.V. ', 'M.T. ',
                'SV ', 'RV ', 'FSO ', 'FPSO ', 'FPU ']
    normalized = str(name).strip().upper()
    for p in prefixes:
        if normalized.startswith(p):
            normalized = normalized[len(p):]
            break
    return normalized.strip()

def detect_vessel_duplicates(db, vessel_data, exclude_id=None):
    """
    Règles de déduplication navire :
    1. IMO identique → doublon certain (score 1.0)
    2. MMSI identique → doublon probable (score 0.95)
    3. Nom normalisé + pavillon identiques → doublon possible (score 0.8)
    """
    duplicates = []
    vessels = db.execute(
        "SELECT * FROM maritime_vessels WHERE status='active'" +
        (f" AND id != '{exclude_id}'" if exclude_id else "")
    ).fetchall()

    new_imo  = vessel_data.get('imo_number', '')
    new_mmsi = vessel_data.get('mmsi', '')
    new_name = normalize_vessel_name(vessel_data.get('vessel_name', ''))
    new_flag = vessel_data.get('flag_code', '')

    for v in vessels:
        try: vd = json.loads(v['data'])
        except: continue

        # Règle 1 : IMO identique
        if new_imo and new_imo == vd.get('imo_number'):
            duplicates.append({'vessel_id': v['id'], 'score': 1.0, 'reason': 'IMO identique'})
            continue

        # Règle 2 : MMSI identique
        if new_mmsi and new_mmsi == vd.get('mmsi'):
            duplicates.append({'vessel_id': v['id'], 'score': 0.95, 'reason': 'MMSI identique'})
            continue

        # Règle 3 : Nom normalisé + pavillon
        existing_name = normalize_vessel_name(vd.get('vessel_name', ''))
        if new_name and existing_name and new_name == existing_name and new_flag == vd.get('flag_code'):
            duplicates.append({'vessel_id': v['id'], 'score': 0.8, 'reason': 'Nom + pavillon identiques'})

    return duplicates

def get_db_from_app():
    """Récupère la connexion DB depuis le contexte Flask"""
    import sqlite3
    from flask import current_app
    db_path = current_app.config.get('DB_PATH')
    if 'maritime_db' not in g:
        g.maritime_db = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        g.maritime_db.row_factory = sqlite3.Row
    return g.maritime_db

# ── INIT TABLES ──────────────────────────────────────────────────────────

MARITIME_SCHEMA = """
CREATE TABLE IF NOT EXISTS maritime_vessels (
    id TEXT PRIMARY KEY,
    mdm_id TEXT UNIQUE,
    status TEXT DEFAULT 'active',
    source TEXT DEFAULT 'manual',
    imo_number TEXT UNIQUE,
    mmsi TEXT,
    vessel_name TEXT NOT NULL,
    vessel_name_normalized TEXT,
    vessel_type TEXT,
    flag_code TEXT,
    flag_name TEXT,
    gross_tonnage REAL,
    deadweight REAL,
    year_built INTEGER,
    owner_id TEXT,
    operator TEXT,
    class_society TEXT,
    data TEXT,
    validation_errors TEXT,
    confidence_score REAL DEFAULT 1.0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS maritime_owners (
    id TEXT PRIMARY KEY,
    mdm_id TEXT UNIQUE,
    status TEXT DEFAULT 'active',
    source TEXT DEFAULT 'manual',
    owner_name TEXT NOT NULL,
    owner_name_normalized TEXT,
    owner_type TEXT,
    country_code TEXT,
    country_name TEXT,
    city TEXT,
    address TEXT,
    contact_email TEXT,
    contact_phone TEXT,
    fleet_size INTEGER DEFAULT 0,
    data TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS maritime_ports (
    id TEXT PRIMARY KEY,
    mdm_id TEXT UNIQUE,
    status TEXT DEFAULT 'active',
    source TEXT DEFAULT 'manual',
    port_name TEXT NOT NULL,
    un_locode TEXT UNIQUE,
    country_code TEXT,
    country_name TEXT,
    latitude REAL,
    longitude REAL,
    port_function TEXT,
    max_vessel_size TEXT,
    max_draft REAL,
    tide_dependent INTEGER DEFAULT 0,
    pilotage_required INTEGER DEFAULT 1,
    data TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS maritime_port_calls (
    id TEXT PRIMARY KEY,
    mdm_id TEXT UNIQUE,
    status TEXT DEFAULT 'active',
    source TEXT DEFAULT 'manual',
    vessel_id TEXT,
    vessel_name TEXT,
    imo_number TEXT,
    port_id TEXT,
    port_name TEXT,
    un_locode TEXT,
    terminal TEXT,
    berth TEXT,
    eta TEXT,
    etd TEXT,
    ata TEXT,
    atd TEXT,
    call_status TEXT DEFAULT 'Planned',
    cargo_type TEXT,
    cargo_quantity REAL,
    cargo_unit TEXT,
    agent_name TEXT,
    voyage_number TEXT,
    data TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
"""

# ── HELPERS ──────────────────────────────────────────────────────────────

def maritime_response(rows):
    result = []
    for r in rows:
        item = dict(r)
        for k in ('data', 'validation_errors'):
            if k in item:
                try: item[k] = json.loads(item[k]) if item[k] else {}
                except: pass
        result.append(item)
    return result

def new_maritime_id(prefix):
    uid = str(uuid.uuid4())
    return uid, f"{prefix}-{uid[:8].upper()}"

# ── VESSELS ──────────────────────────────────────────────────────────────

@maritime_bp.route('/vessels', methods=['GET'])
def list_vessels():
    db   = get_db_from_app()
    page = int(request.args.get('page', 1))
    per  = int(request.args.get('per_page', 20))
    srch = request.args.get('search', '').strip()
    flag = request.args.get('flag', '').strip()
    vtype= request.args.get('vessel_type', '').strip()
    wh   = ["status='active'"]; params = []
    if srch:  wh.append("(vessel_name LIKE ? OR imo_number LIKE ? OR mmsi LIKE ?)"); params += [f'%{srch}%']*3
    if flag:  wh.append("flag_code=?"); params.append(flag)
    if vtype: wh.append("vessel_type=?"); params.append(vtype)
    w = ' AND '.join(wh)
    total = db.execute(f"SELECT COUNT(*) FROM maritime_vessels WHERE {w}", params).fetchone()[0]
    rows  = db.execute(f"SELECT * FROM maritime_vessels WHERE {w} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                       params+[per, (page-1)*per]).fetchall()
    return jsonify({'total': total, 'page': page, 'per_page': per,
                    'vessels': maritime_response(rows)})

@maritime_bp.route('/vessels/<vid>', methods=['GET'])
def get_vessel(vid):
    r = get_db_from_app().execute("SELECT * FROM maritime_vessels WHERE id=?", (vid,)).fetchone()
    if not r: return jsonify({'error': 'Navire introuvable'}), 404
    return jsonify(maritime_response([r])[0])

@maritime_bp.route('/vessels', methods=['POST'])
def create_vessel():
    b  = request.json or {}
    db = get_db_from_app()
    errors = []

    # Validation IMO
    imo, err = validate_imo(b.get('imo_number'))
    if err: errors.append(err)

    # Validation MMSI
    mmsi, err = validate_mmsi(b.get('mmsi'))
    if err: errors.append(err)

    # Nom obligatoire
    vessel_name = str(b.get('vessel_name', '')).strip()
    if not vessel_name: errors.append('Nom du navire obligatoire')

    # Vérifier unicité IMO
    if imo:
        existing = db.execute("SELECT id FROM maritime_vessels WHERE imo_number=?", (imo,)).fetchone()
        if existing:
            return jsonify({'error': f"Un navire avec l'IMO {imo} existe déjà", 'existing_id': existing['id']}), 409

    vid, mdm_id = new_maritime_id('VES')
    name_norm   = normalize_vessel_name(vessel_name)
    flag_code   = str(b.get('flag_code', '')).strip().upper()
    flag_name   = FLAGS.get(flag_code, flag_code)
    owner_id    = b.get('owner_id')

    # Détection doublons préventive
    dups = detect_vessel_duplicates(db, {
        'imo_number': imo, 'mmsi': mmsi,
        'vessel_name': vessel_name, 'flag_code': flag_code
    })

    # Score de confiance : baisse si erreurs de validation
    confidence = max(0.5, 1.0 - (len(errors) * 0.15))

    extra_data = {k: v for k, v in b.items() if k not in
                  ['imo_number','mmsi','vessel_name','vessel_type','flag_code','flag_name',
                   'gross_tonnage','deadweight','year_built','owner_id','operator','class_society']}

    db.execute("""INSERT INTO maritime_vessels
        (id,mdm_id,status,source,imo_number,mmsi,vessel_name,vessel_name_normalized,
         vessel_type,flag_code,flag_name,gross_tonnage,deadweight,year_built,
         owner_id,operator,class_society,data,validation_errors,confidence_score)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (vid, mdm_id, 'active', b.get('source','manual'),
         imo, mmsi, vessel_name, name_norm,
         b.get('vessel_type'), flag_code, flag_name,
         b.get('gross_tonnage'), b.get('deadweight'), b.get('year_built'),
         owner_id, b.get('operator'), b.get('class_society'),
         json.dumps(extra_data, ensure_ascii=False),
         json.dumps(errors) if errors else None,
         confidence))
    db.commit()

    return jsonify({
        'id': vid, 'mdm_id': mdm_id,
        'validation_errors': errors,
        'potential_duplicates': dups,
        'confidence_score': confidence,
        'warning': f"{len(dups)} doublon(s) potentiel(s) détecté(s)" if dups else None
    }), 201

@maritime_bp.route('/vessels/<vid>', methods=['PUT'])
def update_vessel(vid):
    b  = request.json or {}
    db = get_db_from_app()
    if not db.execute("SELECT id FROM maritime_vessels WHERE id=?", (vid,)).fetchone():
        return jsonify({'error': 'Introuvable'}), 404
    errors = []
    imo,  err = validate_imo(b.get('imo_number')); errors += [err] if err else []
    mmsi, err = validate_mmsi(b.get('mmsi'));      errors += [err] if err else []
    vessel_name = str(b.get('vessel_name', '')).strip()
    flag_code   = str(b.get('flag_code', '')).strip().upper()
    db.execute("""UPDATE maritime_vessels SET
        imo_number=?,mmsi=?,vessel_name=?,vessel_name_normalized=?,vessel_type=?,
        flag_code=?,flag_name=?,gross_tonnage=?,deadweight=?,year_built=?,
        owner_id=?,operator=?,class_society=?,validation_errors=?,updated_at=datetime('now')
        WHERE id=?""",
        (imo, mmsi, vessel_name, normalize_vessel_name(vessel_name),
         b.get('vessel_type'), flag_code, FLAGS.get(flag_code, flag_code),
         b.get('gross_tonnage'), b.get('deadweight'), b.get('year_built'),
         b.get('owner_id'), b.get('operator'), b.get('class_society'),
         json.dumps(errors) if errors else None, vid))
    db.commit()
    return jsonify({'message': 'Navire mis à jour', 'validation_errors': errors})

@maritime_bp.route('/vessels/<vid>', methods=['DELETE'])
def delete_vessel(vid):
    db = get_db_from_app()
    db.execute("UPDATE maritime_vessels SET status='deleted' WHERE id=?", (vid,))
    db.commit()
    return jsonify({'message': 'Navire supprimé'})

@maritime_bp.route('/vessels/<vid>/port-calls', methods=['GET'])
def vessel_port_calls(vid):
    r   = get_db_from_app().execute("SELECT * FROM maritime_vessels WHERE id=?", (vid,)).fetchone()
    if not r: return jsonify({'error': 'Navire introuvable'}), 404
    calls = get_db_from_app().execute(
        "SELECT * FROM maritime_port_calls WHERE vessel_id=? ORDER BY eta DESC", (vid,)).fetchall()
    return jsonify({'vessel': maritime_response([r])[0], 'port_calls': maritime_response(calls)})

@maritime_bp.route('/vessels/validate-imo', methods=['POST'])
def validate_imo_route():
    imo_raw = (request.json or {}).get('imo')
    imo, err = validate_imo(imo_raw)
    return jsonify({'valid': err is None, 'imo': imo, 'error': err})

@maritime_bp.route('/vessels/validate-mmsi', methods=['POST'])
def validate_mmsi_route():
    mmsi_raw = (request.json or {}).get('mmsi')
    mmsi, err = validate_mmsi(mmsi_raw)
    return jsonify({'valid': err is None, 'mmsi': mmsi, 'error': err})

# ── OWNERS ───────────────────────────────────────────────────────────────

@maritime_bp.route('/owners', methods=['GET'])
def list_owners():
    db   = get_db_from_app()
    page = int(request.args.get('page', 1))
    per  = int(request.args.get('per_page', 20))
    srch = request.args.get('search', '').strip()
    country = request.args.get('country', '').strip()
    wh = ["status='active'"]; params = []
    if srch:    wh.append("owner_name LIKE ?"); params.append(f'%{srch}%')
    if country: wh.append("country_code=?");   params.append(country)
    w = ' AND '.join(wh)
    total = db.execute(f"SELECT COUNT(*) FROM maritime_owners WHERE {w}", params).fetchone()[0]
    rows  = db.execute(f"SELECT * FROM maritime_owners WHERE {w} ORDER BY owner_name LIMIT ? OFFSET ?",
                       params+[per, (page-1)*per]).fetchall()
    return jsonify({'total': total, 'page': page, 'per_page': per,
                    'owners': maritime_response(rows)})

@maritime_bp.route('/owners/<oid>', methods=['GET'])
def get_owner(oid):
    r = get_db_from_app().execute("SELECT * FROM maritime_owners WHERE id=?", (oid,)).fetchone()
    if not r: return jsonify({'error': 'Armateur introuvable'}), 404
    # Enrichir avec la flotte
    fleet = get_db_from_app().execute(
        "SELECT id,mdm_id,vessel_name,imo_number,vessel_type,flag_code FROM maritime_vessels WHERE owner_id=? AND status='active'", (oid,)).fetchall()
    result = maritime_response([r])[0]
    result['fleet'] = [dict(v) for v in fleet]
    result['fleet_size'] = len(fleet)
    return jsonify(result)

@maritime_bp.route('/owners', methods=['POST'])
def create_owner():
    b  = request.json or {}
    db = get_db_from_app()
    oid, mdm_id = new_maritime_id('OWN')
    owner_name  = str(b.get('owner_name', '')).strip()
    if not owner_name: return jsonify({'error': 'Nom armateur obligatoire'}), 400
    country_code = str(b.get('country_code', '')).strip().upper()
    extra = {k: v for k, v in b.items() if k not in
             ['owner_name','owner_type','country_code','country_name','city','address','contact_email','contact_phone']}
    db.execute("""INSERT INTO maritime_owners
        (id,mdm_id,status,source,owner_name,owner_name_normalized,owner_type,
         country_code,country_name,city,address,contact_email,contact_phone,data)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (oid, mdm_id, 'active', b.get('source','manual'),
         owner_name, owner_name.upper().strip(),
         b.get('owner_type'), country_code, FLAGS.get(country_code, b.get('country_name','')),
         b.get('city'), b.get('address'), b.get('contact_email'), b.get('contact_phone'),
         json.dumps(extra, ensure_ascii=False)))
    db.commit()
    return jsonify({'id': oid, 'mdm_id': mdm_id}), 201

@maritime_bp.route('/owners/<oid>', methods=['PUT'])
def update_owner(oid):
    b  = request.json or {}
    db = get_db_from_app()
    if not db.execute("SELECT id FROM maritime_owners WHERE id=?", (oid,)).fetchone():
        return jsonify({'error': 'Introuvable'}), 404
    country_code = str(b.get('country_code', '')).strip().upper()
    db.execute("""UPDATE maritime_owners SET owner_name=?,owner_name_normalized=?,owner_type=?,
        country_code=?,country_name=?,city=?,address=?,contact_email=?,contact_phone=?,
        updated_at=datetime('now') WHERE id=?""",
        (b.get('owner_name'), str(b.get('owner_name','')).upper().strip(),
         b.get('owner_type'), country_code, FLAGS.get(country_code,''),
         b.get('city'), b.get('address'), b.get('contact_email'), b.get('contact_phone'), oid))
    db.commit()
    return jsonify({'message': 'Armateur mis à jour'})

@maritime_bp.route('/owners/<oid>', methods=['DELETE'])
def delete_owner(oid):
    db = get_db_from_app()
    db.execute("UPDATE maritime_owners SET status='deleted' WHERE id=?", (oid,))
    db.commit()
    return jsonify({'message': 'Armateur supprimé'})

# ── PORTS ────────────────────────────────────────────────────────────────

@maritime_bp.route('/ports', methods=['GET'])
def list_ports():
    db   = get_db_from_app()
    page = int(request.args.get('page', 1))
    per  = int(request.args.get('per_page', 20))
    srch = request.args.get('search', '').strip()
    country = request.args.get('country', '').strip()
    wh = ["status='active'"]; params = []
    if srch:    wh.append("(port_name LIKE ? OR un_locode LIKE ?)"); params += [f'%{srch}%']*2
    if country: wh.append("country_code=?"); params.append(country)
    w = ' AND '.join(wh)
    total = db.execute(f"SELECT COUNT(*) FROM maritime_ports WHERE {w}", params).fetchone()[0]
    rows  = db.execute(f"SELECT * FROM maritime_ports WHERE {w} ORDER BY port_name LIMIT ? OFFSET ?",
                       params+[per, (page-1)*per]).fetchall()
    return jsonify({'total': total, 'page': page, 'per_page': per,
                    'ports': maritime_response(rows)})

@maritime_bp.route('/ports/<pid>', methods=['GET'])
def get_port(pid):
    r = get_db_from_app().execute("SELECT * FROM maritime_ports WHERE id=?", (pid,)).fetchone()
    if not r: return jsonify({'error': 'Port introuvable'}), 404
    # Dernières escales dans ce port
    recent_calls = get_db_from_app().execute(
        "SELECT * FROM maritime_port_calls WHERE port_id=? ORDER BY eta DESC LIMIT 10", (pid,)).fetchall()
    result = maritime_response([r])[0]
    result['recent_calls'] = maritime_response(recent_calls)
    return jsonify(result)

@maritime_bp.route('/ports', methods=['POST'])
def create_port():
    b  = request.json or {}
    db = get_db_from_app()
    pid, mdm_id = new_maritime_id('PRT')
    port_name   = str(b.get('port_name', '')).strip()
    if not port_name: return jsonify({'error': 'Nom du port obligatoire'}), 400

    # Validation UN/LOCODE
    locode, err = validate_locode(b.get('un_locode'))
    if err: return jsonify({'error': err, 'field': 'un_locode'}), 400

    # Vérifier unicité LOCODE
    if locode:
        existing = db.execute("SELECT id FROM maritime_ports WHERE un_locode=?", (locode,)).fetchone()
        if existing:
            return jsonify({'error': f"Port avec LOCODE {locode} existe déjà", 'existing_id': existing['id']}), 409

    country_code = str(b.get('country_code', locode[:2] if locode else '')).strip().upper()
    extra = {k: v for k, v in b.items() if k not in
             ['port_name','un_locode','country_code','country_name','latitude','longitude',
              'port_function','max_vessel_size','max_draft','tide_dependent','pilotage_required']}

    db.execute("""INSERT INTO maritime_ports
        (id,mdm_id,status,source,port_name,un_locode,country_code,country_name,
         latitude,longitude,port_function,max_vessel_size,max_draft,tide_dependent,pilotage_required,data)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (pid, mdm_id, 'active', b.get('source','manual'),
         port_name, locode, country_code, FLAGS.get(country_code, b.get('country_name','')),
         b.get('latitude'), b.get('longitude'), b.get('port_function'),
         b.get('max_vessel_size'), b.get('max_draft'),
         1 if b.get('tide_dependent') else 0,
         1 if b.get('pilotage_required', True) else 0,
         json.dumps(extra, ensure_ascii=False)))
    db.commit()
    return jsonify({'id': pid, 'mdm_id': mdm_id, 'un_locode': locode}), 201

@maritime_bp.route('/ports/<pid>', methods=['PUT'])
def update_port(pid):
    b  = request.json or {}
    db = get_db_from_app()
    if not db.execute("SELECT id FROM maritime_ports WHERE id=?", (pid,)).fetchone():
        return jsonify({'error': 'Introuvable'}), 404
    locode, err = validate_locode(b.get('un_locode'))
    if err: return jsonify({'error': err}), 400
    country_code = str(b.get('country_code', '')).strip().upper()
    db.execute("""UPDATE maritime_ports SET port_name=?,un_locode=?,country_code=?,country_name=?,
        latitude=?,longitude=?,port_function=?,max_vessel_size=?,max_draft=?,
        tide_dependent=?,pilotage_required=?,updated_at=datetime('now') WHERE id=?""",
        (b.get('port_name'), locode, country_code, FLAGS.get(country_code,''),
         b.get('latitude'), b.get('longitude'), b.get('port_function'),
         b.get('max_vessel_size'), b.get('max_draft'),
         1 if b.get('tide_dependent') else 0,
         1 if b.get('pilotage_required', True) else 0, pid))
    db.commit()
    return jsonify({'message': 'Port mis à jour'})

@maritime_bp.route('/ports/<pid>', methods=['DELETE'])
def delete_port(pid):
    get_db_from_app().execute("UPDATE maritime_ports SET status='deleted' WHERE id=?", (pid,))
    get_db_from_app().commit()
    return jsonify({'message': 'Port supprimé'})

# ── PORT CALLS ────────────────────────────────────────────────────────────

@maritime_bp.route('/port-calls', methods=['GET'])
def list_port_calls():
    db   = get_db_from_app()
    page = int(request.args.get('page', 1))
    per  = int(request.args.get('per_page', 20))
    srch = request.args.get('search', '').strip()
    status_f   = request.args.get('status', '').strip()
    vessel_id  = request.args.get('vessel_id', '').strip()
    port_id    = request.args.get('port_id', '').strip()
    locode_f   = request.args.get('locode', '').strip()
    wh = ["pc.status != 'deleted'"]; params = []
    if srch:      wh.append("(pc.vessel_name LIKE ? OR pc.imo_number LIKE ? OR pc.port_name LIKE ?)"); params += [f'%{srch}%']*3
    if status_f:  wh.append("pc.call_status=?");   params.append(status_f)
    if vessel_id: wh.append("pc.vessel_id=?");     params.append(vessel_id)
    if port_id:   wh.append("pc.port_id=?");       params.append(port_id)
    if locode_f:  wh.append("pc.un_locode LIKE ?");params.append(f'%{locode_f}%')
    w = ' AND '.join(wh)
    total = db.execute(f"SELECT COUNT(*) FROM maritime_port_calls pc WHERE {w}", params).fetchone()[0]
    rows  = db.execute(f"SELECT pc.* FROM maritime_port_calls pc WHERE {w} ORDER BY pc.eta DESC LIMIT ? OFFSET ?",
                       params+[per, (page-1)*per]).fetchall()
    return jsonify({'total': total, 'page': page, 'per_page': per,
                    'port_calls': maritime_response(rows)})

@maritime_bp.route('/port-calls/<cid>', methods=['GET'])
def get_port_call(cid):
    r = get_db_from_app().execute("SELECT * FROM maritime_port_calls WHERE id=?", (cid,)).fetchone()
    if not r: return jsonify({'error': 'Escale introuvable'}), 404
    return jsonify(maritime_response([r])[0])

@maritime_bp.route('/port-calls', methods=['POST'])
def create_port_call():
    b  = request.json or {}
    db = get_db_from_app()
    cid, mdm_id = new_maritime_id('ETA')
    errors = []

    # Résolution navire
    vessel_id = b.get('vessel_id')
    vessel_name = b.get('vessel_name', '')
    imo_number  = b.get('imo_number', '')
    if not vessel_id and imo_number:
        v = db.execute("SELECT id,vessel_name FROM maritime_vessels WHERE imo_number=?", (imo_number,)).fetchone()
        if v: vessel_id = v['id']; vessel_name = v['vessel_name']
    if not vessel_name and vessel_id:
        v = db.execute("SELECT vessel_name,imo_number FROM maritime_vessels WHERE id=?", (vessel_id,)).fetchone()
        if v: vessel_name=v['vessel_name']; imo_number=v['imo_number']

    # Résolution port
    port_id   = b.get('port_id')
    port_name = b.get('port_name', '')
    un_locode = b.get('un_locode', '')
    if not port_id and un_locode:
        p = db.execute("SELECT id,port_name FROM maritime_ports WHERE un_locode=?", (un_locode,)).fetchone()
        if p: port_id=p['id']; port_name=p['port_name']
    if not port_name and port_id:
        p = db.execute("SELECT port_name,un_locode FROM maritime_ports WHERE id=?", (port_id,)).fetchone()
        if p: port_name=p['port_name']; un_locode=p['un_locode']

    # Validation dates ETA/ETD
    eta = b.get('eta'); etd = b.get('etd')
    if eta and etd:
        try:
            eta_dt = datetime.fromisoformat(eta.replace('Z',''))
            etd_dt = datetime.fromisoformat(etd.replace('Z',''))
            if etd_dt < eta_dt:
                errors.append('ETD ne peut pas être avant ETA')
        except: errors.append('Format de date invalide (ISO 8601 attendu)')

    # Validation statut
    call_status = b.get('call_status', 'Planned')
    if call_status not in CALL_STATUSES:
        errors.append(f"Statut invalide '{call_status}'. Valeurs: {', '.join(CALL_STATUSES)}")
        call_status = 'Planned'

    if not vessel_name: errors.append('Navire requis (vessel_id ou imo_number ou vessel_name)')
    if not port_name:   errors.append('Port requis (port_id ou un_locode ou port_name)')

    extra = {k: v for k, v in b.items() if k not in
             ['vessel_id','vessel_name','imo_number','port_id','port_name','un_locode',
              'terminal','berth','eta','etd','ata','atd','call_status',
              'cargo_type','cargo_quantity','cargo_unit','agent_name','voyage_number']}

    db.execute("""INSERT INTO maritime_port_calls
        (id,mdm_id,status,source,vessel_id,vessel_name,imo_number,port_id,port_name,un_locode,
         terminal,berth,eta,etd,ata,atd,call_status,cargo_type,cargo_quantity,cargo_unit,
         agent_name,voyage_number,data)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (cid, mdm_id, 'active', b.get('source','manual'),
         vessel_id, vessel_name, imo_number, port_id, port_name, un_locode,
         b.get('terminal'), b.get('berth'), eta, etd, b.get('ata'), b.get('atd'),
         call_status, b.get('cargo_type'), b.get('cargo_quantity'),
         b.get('cargo_unit','MT'), b.get('agent_name'), b.get('voyage_number'),
         json.dumps(extra, ensure_ascii=False)))
    db.commit()
    return jsonify({'id': cid, 'mdm_id': mdm_id, 'validation_errors': errors,
                    'warning': '; '.join(errors) if errors else None}), 201

@maritime_bp.route('/port-calls/<cid>', methods=['PUT'])
def update_port_call(cid):
    b  = request.json or {}
    db = get_db_from_app()
    if not db.execute("SELECT id FROM maritime_port_calls WHERE id=?", (cid,)).fetchone():
        return jsonify({'error': 'Introuvable'}), 404
    call_status = b.get('call_status', 'Planned')
    if call_status not in CALL_STATUSES: call_status = 'Planned'
    db.execute("""UPDATE maritime_port_calls SET
        vessel_name=?,imo_number=?,port_name=?,un_locode=?,terminal=?,berth=?,
        eta=?,etd=?,ata=?,atd=?,call_status=?,cargo_type=?,cargo_quantity=?,
        cargo_unit=?,agent_name=?,voyage_number=?,updated_at=datetime('now') WHERE id=?""",
        (b.get('vessel_name'), b.get('imo_number'), b.get('port_name'), b.get('un_locode'),
         b.get('terminal'), b.get('berth'), b.get('eta'), b.get('etd'),
         b.get('ata'), b.get('atd'), call_status, b.get('cargo_type'),
         b.get('cargo_quantity'), b.get('cargo_unit','MT'),
         b.get('agent_name'), b.get('voyage_number'), cid))
    db.commit()
    return jsonify({'message': 'Escale mise à jour'})

@maritime_bp.route('/port-calls/<cid>', methods=['DELETE'])
def delete_port_call(cid):
    get_db_from_app().execute("UPDATE maritime_port_calls SET status='deleted' WHERE id=?", (cid,))
    get_db_from_app().commit()
    return jsonify({'message': 'Escale supprimée'})

# ── MARITIME STATS ────────────────────────────────────────────────────────

@maritime_bp.route('/stats', methods=['GET'])
def maritime_stats():
    db = get_db_from_app()
    return jsonify({
        'total_vessels':    db.execute("SELECT COUNT(*) FROM maritime_vessels WHERE status='active'").fetchone()[0],
        'total_owners':     db.execute("SELECT COUNT(*) FROM maritime_owners WHERE status='active'").fetchone()[0],
        'total_ports':      db.execute("SELECT COUNT(*) FROM maritime_ports WHERE status='active'").fetchone()[0],
        'total_port_calls': db.execute("SELECT COUNT(*) FROM maritime_port_calls WHERE status='active'").fetchone()[0],
        'active_calls':     db.execute("SELECT COUNT(*) FROM maritime_port_calls WHERE call_status IN ('Berthed','At Anchor','In Transit')").fetchone()[0],
        'vessels_by_flag':  [dict(r) for r in db.execute("SELECT flag_code,flag_name,COUNT(*) as count FROM maritime_vessels WHERE status='active' GROUP BY flag_code ORDER BY count DESC LIMIT 10").fetchall()],
        'vessels_by_type':  [dict(r) for r in db.execute("SELECT vessel_type,COUNT(*) as count FROM maritime_vessels WHERE status='active' GROUP BY vessel_type ORDER BY count DESC").fetchall()],
        'calls_by_status':  [dict(r) for r in db.execute("SELECT call_status,COUNT(*) as count FROM maritime_port_calls GROUP BY call_status ORDER BY count DESC").fetchall()],
        'top_ports':        [dict(r) for r in db.execute("SELECT port_name,un_locode,COUNT(*) as call_count FROM maritime_port_calls GROUP BY port_id ORDER BY call_count DESC LIMIT 10").fetchall()],
        'calls_timeline':   [dict(r) for r in db.execute("SELECT DATE(eta) as day,COUNT(*) as count FROM maritime_port_calls WHERE eta>=date('now','-30 days') GROUP BY day ORDER BY day").fetchall()],
        'low_confidence':   db.execute("SELECT COUNT(*) FROM maritime_vessels WHERE confidence_score < 0.8").fetchone()[0],
        'validation_errors':db.execute("SELECT COUNT(*) FROM maritime_vessels WHERE validation_errors IS NOT NULL AND validation_errors != 'null'").fetchone()[0],
    })

@maritime_bp.route('/duplicates/detect', methods=['POST'])
def detect_maritime_duplicates():
    """Détection doublons navires basée sur règles IMO/MMSI/Nom"""
    db      = get_db_from_app()
    vessels = db.execute("SELECT * FROM maritime_vessels WHERE status='active'").fetchall()
    found   = 0
    groups  = {'by_imo':{}, 'by_mmsi':{}, 'by_name_flag':{}}
    for v in vessels:
        if v['imo_number']:  groups['by_imo'].setdefault(v['imo_number'], []).append(v['id'])
        if v['mmsi']:        groups['by_mmsi'].setdefault(v['mmsi'], []).append(v['id'])
        key = f"{v['vessel_name_normalized']}|{v['flag_code']}"
        if v['vessel_name_normalized']: groups['by_name_flag'].setdefault(key, []).append(v['id'])

    results = []
    for reason, group, score in [
        ('IMO identique', groups['by_imo'], 1.0),
        ('MMSI identique', groups['by_mmsi'], 0.95),
        ('Nom+Pavillon identiques', groups['by_name_flag'], 0.8)
    ]:
        for key, ids in group.items():
            if len(ids) > 1:
                for i in range(len(ids)):
                    for j in range(i+1, len(ids)):
                        results.append({'vessel1_id':ids[i],'vessel2_id':ids[j],'score':score,'reason':reason})
                        found += 1
    return jsonify({'found': found, 'duplicates': results})

# ── RÉFÉRENTIELS ─────────────────────────────────────────────────────────

@maritime_bp.route('/referentials/flags', methods=['GET'])
def get_flags():
    return jsonify([{'code': k, 'name': v} for k, v in sorted(FLAGS.items(), key=lambda x: x[1])])

@maritime_bp.route('/referentials/vessel-types', methods=['GET'])
def get_vessel_types():
    return jsonify(VESSEL_TYPES)

@maritime_bp.route('/referentials/call-statuses', methods=['GET'])
def get_call_statuses():
    return jsonify(CALL_STATUSES)

@maritime_bp.route('/referentials/cargo-types', methods=['GET'])
def get_cargo_types():
    return jsonify(CARGO_TYPES)
