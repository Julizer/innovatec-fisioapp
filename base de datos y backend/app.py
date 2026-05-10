from flask import Flask, jsonify, request, session, send_from_directory
import os
import sqlite3
import random
import string
import bcrypt
from flask_cors import CORS
from pywebpush import webpush, WebPushException
import datetime
import json
import threading
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from cryptography.hazmat.primitives.asymmetric import ec

app = Flask(__name__)

#direcciones de servidor IMPORTANTES
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) #consigue el directorio del app.py
FRONTEND_DIR = os.path.join(BASE_DIR, "..") #extrae la carpeta padre de base_dir
DB_PATH = os.path.join(BASE_DIR, "fisioterapp.db")

#para login
app.secret_key = "clave_secreta"

CORS(app, supports_credentials=True)

IS_PRODUCTION = os.getenv("FLASK_ENV") == "production"
app.config["SESSION_COOKIE_SAMESITE"] = "None" if IS_PRODUCTION else "Lax"
app.config["SESSION_COOKIE_SECURE"] = IS_PRODUCTION

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "eFaUctaZhCHWiKuZXZ5hgh8G482uvKQLY_PCyCFdubgSuj1pQGDwQgx4jJxEgve_8O8eklSKij5xoQytYZjHHg")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "3vfnp_SJW87mtAqeTK7YMT1S5VPGuArrDk7UONC9xbQ")
VAPID_CLAIMS = {"sub": "mailto:admin@innovatec.com"}
AUTO_NOTIFICATION_HOURS = [9, 14, 19]


def initialize_database():
    # Evitar inicialización múltiple
    if hasattr(initialize_database, '_initialized'):
        return
    initialize_database._initialized = True

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    cursor.executescript(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            correo TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            rol TEXT CHECK(rol IN ('admin', 'terapeuta', 'paciente')) NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pacientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            apellidos TEXT NOT NULL,
            fecha_nacimiento DATE,
            sexo TEXT,
            telefono TEXT,
            correo TEXT,
            terapeuta_id INTEGER,
            fecha_registro DATE DEFAULT CURRENT_DATE,
            FOREIGN KEY (terapeuta_id) REFERENCES usuarios(id)
        );

        CREATE TABLE IF NOT EXISTS encuestas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            fecha DATE DEFAULT CURRENT_DATE,
            completada BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (paciente_id) REFERENCES pacientes(id)
        );

        CREATE TABLE IF NOT EXISTS respuestas_encuesta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            encuesta_id INTEGER NOT NULL,
            pregunta_numero INTEGER NOT NULL,
            respuesta TEXT NOT NULL,
            FOREIGN KEY (encuesta_id) REFERENCES encuestas(id)
        );

        CREATE TABLE IF NOT EXISTS notificaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            terapeuta_id INTEGER NOT NULL,
            mensaje TEXT NOT NULL,
            fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
            enviada BOOLEAN DEFAULT FALSE,
            tipo TEXT DEFAULT 'manual',
            FOREIGN KEY (paciente_id) REFERENCES pacientes(id),
            FOREIGN KEY (terapeuta_id) REFERENCES usuarios(id)
        );

        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            endpoint TEXT UNIQUE NOT NULL,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (paciente_id) REFERENCES pacientes(id)
        );
        """
    )

    # Reparar esquema de respuestas_encuesta si aún referencia encuestas_old
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='respuestas_encuesta'")
    respuestas_row = cursor.fetchone()
    respuestas_sql = respuestas_row[0] if respuestas_row else None
    if respuestas_sql and 'encuestas_old' in respuestas_sql:
        cursor.execute("CREATE TABLE IF NOT EXISTS respuestas_encuesta_new (\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            encuesta_id INTEGER NOT NULL,\n            pregunta_numero INTEGER NOT NULL,\n            respuesta TEXT NOT NULL,\n            FOREIGN KEY (encuesta_id) REFERENCES encuestas(id)\n        );")
        cursor.execute("INSERT INTO respuestas_encuesta_new (id, encuesta_id, pregunta_numero, respuesta) SELECT id, encuesta_id, pregunta_numero, respuesta FROM respuestas_encuesta")
        cursor.execute("DROP TABLE respuestas_encuesta")
        cursor.execute("ALTER TABLE respuestas_encuesta_new RENAME TO respuestas_encuesta")

    # Asegura compatibilidad con bases antiguas sin terapeuta_id.
    cursor.execute("PRAGMA table_info(pacientes)")
    columnas = [col[1] for col in cursor.fetchall()]
    if "terapeuta_id" not in columnas:
        cursor.execute("ALTER TABLE pacientes ADD COLUMN terapeuta_id INTEGER")

    # Asegura compatibilidad con bases antiguas sin tipo en notificaciones.
    cursor.execute("PRAGMA table_info(notificaciones)")
    columnas_notif = [col[1] for col in cursor.fetchall()]
    if "tipo" not in columnas_notif:
        cursor.execute("ALTER TABLE notificaciones ADD COLUMN tipo TEXT DEFAULT 'manual'")

    # Migra la tabla usuarios si la restriccion de rol no incluye 'paciente'.
    cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='usuarios'"
    )
    usuarios_table = cursor.fetchone()
    usuarios_sql = (usuarios_table[0] or "") if usuarios_table else ""

    if "'paciente'" not in usuarios_sql:
        cursor.executescript(
            """
            ALTER TABLE usuarios RENAME TO usuarios_old;

            CREATE TABLE usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                correo TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                rol TEXT CHECK(rol IN ('admin', 'terapeuta', 'paciente')) NOT NULL
            );

            INSERT INTO usuarios (id, correo, password, rol)
            SELECT id, correo, password, rol
            FROM usuarios_old;

            DROP TABLE usuarios_old;
            """
        )

    # Ensure 'codigo' column exists and backfill for terapeutas
    cursor.execute("PRAGMA table_info(usuarios)")
    cols = [c[1] for c in cursor.fetchall()]
    # Add profile columns if missing
    profile_cols = ['nombre', 'apellidos', 'telefono', 'especialidad']
    for pc in profile_cols:
        if pc not in cols:
            cursor.execute(f"ALTER TABLE usuarios ADD COLUMN {pc} TEXT")
    if 'codigo' not in cols:
        cursor.execute("ALTER TABLE usuarios ADD COLUMN codigo TEXT")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_codigo ON usuarios(codigo)")

    # Backfill codes for terapeutas missing one
    cursor.execute("SELECT id FROM usuarios WHERE rol='terapeuta' AND (codigo IS NULL OR codigo='')")
    missing = [r[0] for r in cursor.fetchall()]
    def gen_code(n=8):
        alphabet = string.ascii_uppercase + string.digits
        return ''.join(random.choice(alphabet) for _ in range(n))

    for tid in missing:
        code = gen_code()
        cursor.execute("SELECT 1 FROM usuarios WHERE codigo=?", (code,))
        while cursor.fetchone():
            code = gen_code()
            cursor.execute("SELECT 1 FROM usuarios WHERE codigo=?", (code,))
        cursor.execute("UPDATE usuarios SET codigo=? WHERE id=?", (code, tid))

    conn.commit()
    conn.close()

@app.route("/me", methods=["GET"])
def me():
    print("SESSION EN /me:", dict(session))
    if "user_id" not in session:
        return {"error": "No autenticado"}, 401
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT id, correo, rol, codigo, nombre, apellidos FROM usuarios WHERE id=?", (session["user_id"],))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {"error": "Usuario no encontrado"}, 404

    return {
        "user_id": row[0],
        "correo": row[1],
        "rol": row[2],
        "codigo": row[3],
        "nombre": row[4],
        "apellidos": row[5]
    }

@app.route("/vapid_public_key", methods=["GET"])
def vapid_public_key():
    return jsonify({"publicKey": VAPID_PUBLIC_KEY})

@app.route("/push/subscribe", methods=["POST"])
def push_subscribe():
    if "user_id" not in session:
        return {"error": "No autenticado"}, 401

    if session.get("rol") != "paciente":
        return {"error": "Solo para pacientes"}, 403

    data = request.get_json() or {}
    subscription = data.get("subscription") or data
    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys", {})
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not endpoint or not p256dh or not auth:
        return {"error": "Datos de suscripción incompletos"}, 400

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM pacientes WHERE correo = (SELECT correo FROM usuarios WHERE id = ?)",
        (session["user_id"],)
    )
    paciente_row = cursor.fetchone()
    if not paciente_row:
        conn.close()
        return {"error": "Paciente no encontrado"}, 404

    paciente_id = paciente_row[0]
    cursor.execute(
        "INSERT OR REPLACE INTO push_subscriptions (endpoint, p256dh, auth, paciente_id) VALUES (?, ?, ?, ?)",
        (endpoint, p256dh, auth, paciente_id)
    )
    conn.commit()
    conn.close()

    return {"mensaje": "Suscripción push guardada"}

@app.route("/push/unsubscribe", methods=["POST"])
def push_unsubscribe():
    if "user_id" not in session:
        return {"error": "No autenticado"}, 401

    if session.get("rol") != "paciente":
        return {"error": "Solo para pacientes"}, 403

    data = request.get_json() or {}
    endpoint = data.get("endpoint")
    if not endpoint:
        return {"error": "Endpoint faltante"}, 400

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    conn.commit()
    conn.close()

    return {"mensaje": "Suscripción push eliminada"}


def enviar_push(paciente_id, titulo, mensaje):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE paciente_id = ?",
        (paciente_id,)
    )
    suscripciones = cursor.fetchall()
    conn.close()

    payload = json.dumps({
        "title": titulo,
        "body": mensaje,
        "icon": "/assets/img/favicon.png" if os.path.exists(os.path.join(FRONTEND_DIR, "assets/img/favicon.png")) else None,
        "url": "/dashboard-paciente-home.html"
    })

    for endpoint, p256dh, auth in suscripciones:
        try:
            webpush(
                subscription_info={
                    "endpoint": endpoint,
                    "keys": {
                        "p256dh": p256dh,
                        "auth": auth
                    }
                },
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS
            )
        except WebPushException as exc:
            print("WebPush error:", exc)
            if exc.response and exc.response.status_code in [404, 410]:
                conn = conectar()
                c = conn.cursor()
                c.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
                conn.commit()
                conn.close()


def obtener_pacientes_sin_encuesta_hoy():
    fecha_hoy = datetime.date.today().isoformat()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT p.id, p.nombre, p.apellidos, p.terapeuta_id
        FROM pacientes p
        LEFT JOIN encuestas e ON e.paciente_id = p.id AND e.fecha = ? AND e.completada = 1
        WHERE e.id IS NULL
          AND p.terapeuta_id IS NOT NULL
        """,
        (fecha_hoy,)
    )
    filas = cursor.fetchall()
    conn.close()
    return filas


def enviar_notificaciones_automaticas(periodo_label):
    pacientes = obtener_pacientes_sin_encuesta_hoy()
    if not pacientes:
        return

    now = datetime.datetime.now()
    periodo_texto = f"({periodo_label})"

    for paciente_id, nombre, apellidos, terapeuta_id in pacientes:
        mensaje = f"Hola {nombre}, recuerda completar tu encuesta diaria {periodo_texto}."
        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT 1 FROM notificaciones WHERE paciente_id = ? AND tipo = 'auto' AND DATE(fecha) = ? AND mensaje LIKE ?",
            (paciente_id, now.date().isoformat(), f"%{periodo_texto}%")
        )
        if cursor.fetchone():
            conn.close()
            continue

        cursor.execute(
            "INSERT INTO notificaciones (paciente_id, terapeuta_id, mensaje, enviada, tipo) VALUES (?, ?, ?, 1, 'auto')",
            (paciente_id, terapeuta_id, mensaje)
        )
        conn.commit()
        conn.close()

        enviar_push(paciente_id, "Recordatorio automático", mensaje)


def run_notification_scheduler():
    last_window = None
    while True:
        now = datetime.datetime.now()
        current_hour = now.hour
        window = next((hour for hour in AUTO_NOTIFICATION_HOURS if hour == current_hour), None)

        if window is not None:
            key = (now.date().isoformat(), window)
            if key != last_window:
                enviar_notificaciones_automaticas(f"{window}:00")
                last_window = key

        time.sleep(60)


def start_notification_scheduler():
    scheduler_thread = threading.Thread(target=run_notification_scheduler, daemon=True)
    scheduler_thread.start()


@app.route("/notificar/auto/run", methods=["POST"])
def trigger_auto_notifications():
    if "user_id" not in session:
        return {"error": "No autorizado"}, 401

    if session.get("rol") not in ["terapeuta", "admin"]:
        return {"error": "Acceso prohibido"}, 403

    enviar_notificaciones_automaticas("manual")
    return {"mensaje": "Notificaciones automáticas disparadas"}


def conectar():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@app.route("/")
def frontend():
    return send_from_directory(FRONTEND_DIR, "index.html")

@app.route('/<path:path>')
def serve_files(path):
    return send_from_directory(
        FRONTEND_DIR,
        path
    )


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()

    correo = data.get("correo")
    password = data.get("password")

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("SELECT id, correo, rol, password, codigo FROM usuarios WHERE correo=?", (correo,))
    row = cursor.fetchone()
    conn.close()
    print("LOGIN USER ROW:", row)

    if not row:
        return {"mensaje": "Credenciales incorrectas"}, 401

    user_id, correo_db, rol, stored_pw, codigo = row

    pw_ok = False
    try:
        if stored_pw and stored_pw.startswith(("$2b$", "$2a$", "$2y$")):
            pw_ok = bcrypt.checkpw(password.encode(), stored_pw.encode())
        else:
            # legacy plaintext: accept and re-hash
            pw_ok = (password == stored_pw)
            if pw_ok:
                new_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                conn = conectar()
                cur = conn.cursor()
                cur.execute("UPDATE usuarios SET password=? WHERE id=?", (new_hash, user_id))
                conn.commit()
                conn.close()
    except Exception as e:
        print('Error checking password:', e)

    if not pw_ok:
        return {"mensaje": "Credenciales incorrectas"}, 401

    session.clear()
    session["user_id"] = user_id
    session["rol"] = rol

    return {
        "mensaje": "Login exitoso",
        "usuario": {
            "id": user_id,
            "correo": correo_db,
            "rol": rol,
            "codigo": codigo
        }
    }


@app.route("/register", methods=["POST"])
def register():
    data = request.get_json() or {}

    correo = data.get("correo") or data.get("usuario")
    password = data.get("password")
    rol = data.get("rol", "terapeuta")
    codigo_terapeuta = data.get("codigo_terapeuta")
    nombre = data.get("nombre")
    apellidos = data.get("apellidos")
    telefono = data.get("telefono")
    especialidad = data.get("especialidad")
    fecha_nacimiento = data.get("fecha_nacimiento")
    sexo = data.get("sexo")

    if not correo or not password:
        return {"mensaje": "Correo y password son obligatorios"}, 400

    if rol not in ["admin", "terapeuta", "paciente"]:
        return {"mensaje": "Rol inválido"}, 400

    # Validaciones adicionales para pacientes
    if rol == "paciente":
        if not fecha_nacimiento:
            return {"mensaje": "Fecha de nacimiento es obligatoria para pacientes"}, 400
        if not sexo or sexo not in ["M", "F", "Otro"]:
            return {"mensaje": "Sexo es obligatorio para pacientes (M, F, Otro)"}, 400

    conn = conectar()
    cursor = conn.cursor()

    try:
        # hash password
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        cursor.execute(
            "INSERT INTO usuarios (correo, password, rol) VALUES (?, ?, ?)",
            (correo, hashed, rol)
        )
        conn.commit()
        user_id = cursor.lastrowid

        # If terapeuta, generate a codigo for sharing
        if rol == "terapeuta":
            code = None
            def gen_code(n=8):
                alphabet = string.ascii_uppercase + string.digits
                return ''.join(random.choice(alphabet) for _ in range(n))

            code = gen_code()
            cursor.execute("SELECT 1 FROM usuarios WHERE codigo=?", (code,))
            while cursor.fetchone():
                code = gen_code()
                cursor.execute("SELECT 1 FROM usuarios WHERE codigo=?", (code,))

            cursor.execute("UPDATE usuarios SET codigo=? WHERE id=?", (code, user_id))
            conn.commit()
            # Save profile fields for terapeuta if provided
            cursor.execute(
                "UPDATE usuarios SET nombre=?, apellidos=?, telefono=?, especialidad=? WHERE id=?",
                (nombre or '', apellidos or '', telefono or '', especialidad or '', user_id)
            )
            conn.commit()

        # If paciente, associate to therapist and create pacientes row
        if rol == "paciente":
            if not codigo_terapeuta:
                conn.close()
                return {"mensaje": "codigo_terapeuta es requerido para pacientes"}, 400

            cursor.execute("SELECT id FROM usuarios WHERE rol='terapeuta' AND codigo=?", (codigo_terapeuta,))
            row = cursor.fetchone()
            if not row:
                conn.close()
                return {"mensaje": "Terapeuta no encontrado con ese codigo"}, 404

            terapeuta_id = row[0]

            # create a pacientes record linked to this therapist
            cursor.execute(
                "INSERT INTO pacientes (nombre, apellidos, fecha_nacimiento, sexo, telefono, correo, terapeuta_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (nombre or "", apellidos or "", fecha_nacimiento, sexo, telefono or "", correo, terapeuta_id)
            )
            conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return {"mensaje": "Ese correo ya existe"}, 409

    conn.close()
    resp = {"success": True, "mensaje": "Usuario registrado correctamente"}
    if rol == "terapeuta":
        resp["codigo"] = code

    return resp, 201


@app.route("/terapeuta/lookup", methods=["GET"])
def lookup_terapeuta():
    codigo = request.args.get("codigo")
    if not codigo:
        return {"mensaje": "codigo query required"}, 400

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT id, correo, nombre, apellidos FROM usuarios WHERE rol='terapeuta' AND codigo=?", (codigo,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return {"mensaje": "No encontrado"}, 404

    return {"id": row[0], "correo": row[1], "nombre": row[2], "apellidos": row[3], "codigo": codigo}


@app.route("/mi_terapeuta", methods=["GET"])
def mi_terapeuta():
    if "user_id" not in session:
        return {"error": "No autenticado"}, 401

    # only for pacientes
    if session.get("rol") != "paciente":
        return {"error": "No autorizado"}, 403

    conn = conectar()
    cur = conn.cursor()
    # get patient's correo
    cur.execute("SELECT correo FROM usuarios WHERE id=?", (session["user_id"],))
    r = cur.fetchone()
    if not r:
        conn.close()
        return {"error": "Paciente no encontrado"}, 404

    correo = r[0]
    cur.execute("SELECT terapeuta_id FROM pacientes WHERE correo=? ORDER BY id DESC LIMIT 1", (correo,))
    prow = cur.fetchone()
    if not prow or not prow[0]:
        conn.close()
        return {"error": "Terapeuta no asignado"}, 404

    terapeuta_id = prow[0]
    cur.execute("SELECT id, correo, codigo, nombre, apellidos, telefono, especialidad FROM usuarios WHERE id=?", (terapeuta_id,))
    t = cur.fetchone()
    conn.close()
    if not t:
        return {"error": "Terapeuta no encontrado"}, 404

    return {
        "id": t[0],
        "correo": t[1],
        "codigo": t[2],
        "nombre": t[3],
        "apellidos": t[4],
        "telefono": t[5],
        "especialidad": t[6]
    }

@app.route("/usuarios", methods=["GET"])
def obtener_usuarios():
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("SELECT id, correo, rol FROM usuarios")
    datos = cursor.fetchall()

    # convertir a JSON bonito
    usuarios = []
    for u in datos:
        usuarios.append({
            "id": u[0],
            "correo": u[1],
            "rol": u[2]
        })

    conn.close()

    return jsonify(usuarios)


# 🔹 GET → obtener pacientes
@app.route("/pacientes", methods=["GET"])
def obtener_pacientes():

    print("SESSION:", dict(session))
    
    if "user_id" not in session:
        return {"error": "No autorizado"}, 401

    if session.get("rol") not in ["terapeuta", "admin"]:
        return {"error": "Acceso prohibido"}, 403

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM pacientes WHERE terapeuta_id = ?",
        (session["user_id"],)
    )

    columnas = [col[0] for col in cursor.description]
    filas = cursor.fetchall()

    datos = []
    for fila in filas:
        datos.append(dict(zip(columnas, fila)))

    conn.close()

    return jsonify(datos)


# 🔹 GET → obtener pacientes con encuesta pendiente hoy
@app.route("/pacientes/pendientes", methods=["GET"])
def pacientes_pendientes():
    if "user_id" not in session:
        return {"error": "No autorizado"}, 401

    if session.get("rol") not in ["terapeuta", "admin"]:
        return {"error": "Acceso prohibido"}, 403

    conn = conectar()
    cursor = conn.cursor()
    fecha_hoy = datetime.date.today().isoformat()

    cursor.execute(
        """
        SELECT p.*
        FROM pacientes p
        LEFT JOIN encuestas e ON e.paciente_id = p.id AND e.fecha = ?
        WHERE p.terapeuta_id = ?
        GROUP BY p.id
        HAVING MAX(CASE WHEN e.completada = 1 THEN 1 ELSE 0 END) = 0
        """,
        (fecha_hoy, session["user_id"])
    )

    columnas = [col[0] for col in cursor.description]
    filas = cursor.fetchall()
    datos = [dict(zip(columnas, fila)) for fila in filas]
    conn.close()
    return jsonify(datos)


# 🔹 POST → enviar recordatorio a un paciente pendiente
@app.route("/notificar/paciente/<int:paciente_id>", methods=["POST"])
def notificar_paciente(paciente_id):
    if "user_id" not in session:
        return {"error": "No autorizado"}, 401

    if session.get("rol") not in ["terapeuta", "admin"]:
        return {"error": "Acceso prohibido"}, 403

    mensaje = request.get_json().get("mensaje", "Recuerda completar tu encuesta diaria.")

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT terapeuta_id FROM pacientes WHERE id = ?", (paciente_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"error": "Paciente no encontrado"}, 404

    if row[0] != session["user_id"] and session.get("rol") != "admin":
        conn.close()
        return {"error": "No puedes notificar a este paciente"}, 403

    cursor.execute(
        "INSERT INTO notificaciones (paciente_id, terapeuta_id, mensaje, enviada) VALUES (?, ?, ?, 1)",
        (paciente_id, session["user_id"], mensaje)
    )
    conn.commit()
    conn.close()

    enviar_push(paciente_id, "Recordatorio de encuesta diaria", mensaje)

    return {"mensaje": "Recordatorio enviado."}


# 🔹 POST → crear paciente
@app.route("/pacientes", methods=["POST"])
def crear_paciente():
    data = request.get_json()

    if "user_id" not in session:
        return {"error": "No autorizado"}, 401

    if session.get("rol") not in ["terapeuta", "admin"]:
        return {"error": "Acceso prohibido"}, 403

    if not data.get("nombre") or not data.get("apellidos"):
        return {"error": "Nombre y apellidos son obligatorios"}, 400

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO pacientes 
    (nombre, apellidos, fecha_nacimiento, sexo, telefono, correo, terapeuta_id)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("nombre"),
        data.get("apellidos"),
        data.get("fecha_nacimiento"),
        data.get("sexo"),
        data.get("telefono"),
        data.get("correo"),
        session["user_id"]   # 🔥 clave
    ))

    conn.commit()
    conn.close()

    return {"mensaje": "Paciente creado correctamente"}


# 🔹 ENCUESTAS
@app.route("/encuesta/diaria", methods=["GET"])
def obtener_encuesta_diaria():
    if "user_id" not in session:
        return {"error": "No autenticado"}, 401

    if session.get("rol") != "paciente":
        return {"error": "Solo para pacientes"}, 403

    # Obtener el paciente_id desde usuarios
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM pacientes WHERE correo = (SELECT correo FROM usuarios WHERE id = ?)", (session["user_id"],))
    paciente_row = cursor.fetchone()

    if not paciente_row:
        conn.close()
        return {"error": "Paciente no encontrado"}, 404

    paciente_id = paciente_row[0]
    fecha_hoy = datetime.date.today().isoformat()

    # Verificar si ya existe una encuesta para hoy
    cursor.execute("SELECT id, completada FROM encuestas WHERE paciente_id = ? AND fecha = ?", (paciente_id, fecha_hoy))
    encuesta_row = cursor.fetchone()

    if encuesta_row:
        encuesta_id, completada = encuesta_row
        if completada:
            conn.close()
            return {"completada": True, "mensaje": "Encuesta ya completada hoy"}

        # Obtener respuestas existentes
        cursor.execute("SELECT pregunta_numero, respuesta FROM respuestas_encuesta WHERE encuesta_id = ?", (encuesta_id,))
        respuestas = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()
        return {"encuesta_id": encuesta_id, "respuestas": respuestas}

    # Crear nueva encuesta
    cursor.execute("INSERT INTO encuestas (paciente_id, fecha) VALUES (?, ?)", (paciente_id, fecha_hoy))
    nueva_encuesta_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {"encuesta_id": nueva_encuesta_id, "respuestas": {}}


@app.route("/encuesta/guardar", methods=["POST"])
def guardar_encuesta():
    if "user_id" not in session:
        return {"error": "No autenticado"}, 401

    if session.get("rol") != "paciente":
        return {"error": "Solo para pacientes"}, 403

    data = request.get_json()
    encuesta_id = data.get("encuesta_id")
    respuestas = data.get("respuestas", {})

    if not encuesta_id or not respuestas:
        return {"error": "Datos incompletos"}, 400

    conn = conectar()
    cursor = conn.cursor()

    # Verificar que la encuesta pertenece al paciente
    cursor.execute("""
        SELECT e.id FROM encuestas e
        JOIN pacientes p ON e.paciente_id = p.id
        JOIN usuarios u ON p.correo = u.correo
        WHERE e.id = ? AND u.id = ?
    """, (encuesta_id, session["user_id"]))

    if not cursor.fetchone():
        conn.close()
        return {"error": "Encuesta no encontrada o no autorizada"}, 404

    # Eliminar respuestas anteriores
    cursor.execute("DELETE FROM respuestas_encuesta WHERE encuesta_id = ?", (encuesta_id,))

    # Insertar nuevas respuestas
    for pregunta_num, respuesta in respuestas.items():
        cursor.execute("INSERT INTO respuestas_encuesta (encuesta_id, pregunta_numero, respuesta) VALUES (?, ?, ?)",
                      (encuesta_id, int(pregunta_num), str(respuesta)))

    # Marcar como completada
    cursor.execute("UPDATE encuestas SET completada = TRUE WHERE id = ?", (encuesta_id,))

    conn.commit()
    conn.close()

    return {"mensaje": "Encuesta guardada correctamente"}


@app.route("/encuesta/estado", methods=["GET"])
def estado_encuesta():
    if "user_id" not in session:
        return {"error": "No autenticado"}, 401

    if session.get("rol") != "paciente":
        return {"error": "Solo para pacientes"}, 403

    # Obtener el paciente_id
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM pacientes WHERE correo = (SELECT correo FROM usuarios WHERE id = ?)", (session["user_id"],))
    paciente_row = cursor.fetchone()

    if not paciente_row:
        conn.close()
        return {"completada": False}

    paciente_id = paciente_row[0]
    fecha_hoy = datetime.date.today().isoformat()

    cursor.execute("SELECT completada FROM encuestas WHERE paciente_id = ? AND fecha = ?", (paciente_id, fecha_hoy))
    row = cursor.fetchone()

    cursor.execute(
        "SELECT fecha FROM encuestas WHERE paciente_id = ? AND completada = 1 ORDER BY fecha DESC",
        (paciente_id,)
    )
    completed_rows = [r[0] for r in cursor.fetchall()]
    conn.close()

    streak = 0
    today = datetime.date.today()
    previous_date = None

    for fecha_str in completed_rows:
        try:
            fecha = datetime.date.fromisoformat(fecha_str)
        except ValueError:
            continue

        if streak == 0:
            if fecha == today or fecha == today - datetime.timedelta(days=1):
                streak = 1
                previous_date = fecha
            else:
                break
        else:
            if fecha == previous_date - datetime.timedelta(days=1):
                streak += 1
                previous_date = fecha
            else:
                break

    return {"completada": bool(row and row[0]), "racha": streak}


@app.route("/encuesta/progreso", methods=["GET"])
def encuesta_progreso():
    """
    GET /encuesta/progreso?periodo=dia|semana|mes
    Retorna array de datos de progreso del paciente con promedios diarios
    """
    if "id_usuario" not in session:
        return {"error": "No autenticado"}, 401

    periodo = request.args.get("periodo", "semana")
    id_usuario = session["id_usuario"]

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Obtener id_paciente del usuario
    cursor.execute("SELECT id FROM pacientes WHERE id_usuario = ?", (id_usuario,))
    paciente_row = cursor.fetchone()
    if not paciente_row:
        conn.close()
        return {"error": "Paciente no encontrado"}, 404
    
    id_paciente = paciente_row[0]

    # Calcular fecha inicio según periodo
    today = datetime.date.today()
    if periodo == "dia":
        fecha_inicio = today
    elif periodo == "semana":
        fecha_inicio = today - datetime.timedelta(days=6)
    elif periodo == "mes":
        fecha_inicio = today - datetime.timedelta(days=29)
    else:
        fecha_inicio = today - datetime.timedelta(days=6)

    # Preguntas numéricas (0-10): 1,2,4,5,6,7,9,11,16,17
    preguntas_numericas = [1, 2, 4, 5, 6, 7, 9, 11, 16, 17]

    # Query: obtener todas las encuestas completadas en el rango
    cursor.execute("""
        SELECT DISTINCT DATE(e.fecha) as dia, AVG(CAST(r.respuesta AS FLOAT)) as promedio
        FROM encuestas e
        JOIN respuestas_encuesta r ON e.id = r.encuesta_id
        WHERE e.id_paciente = ? 
        AND DATE(e.fecha) >= DATE(?)
        AND e.completada = 1
        AND r.numero_pregunta IN ({})
        GROUP BY DATE(e.fecha)
        ORDER BY dia ASC
    """.format(','.join('?' * len(preguntas_numericas))), 
    [id_paciente, fecha_inicio.isoformat()] + preguntas_numericas)

    resultados = cursor.fetchall()
    conn.close()

    # Convertir a array con dias y promedios
    datos = []
    for dia, promedio in resultados:
        datos.append({
            "dia": dia,
            "promedio": round(promedio, 2) if promedio else 0
        })

    return {"datos": datos, "periodo": periodo}


#logout
@app.route("/logout", methods=["POST", "GET"])
def logout():
    session.clear()
    return {"mensaje": "Sesión cerrada"}

if __name__ == "__main__":
    initialize_database()
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_notification_scheduler()
    app.run(debug=True)