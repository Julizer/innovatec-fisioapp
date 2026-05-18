from flask import Flask, jsonify, request, session, send_from_directory
import os
import sqlite3
import random
import string
import bcrypt
import mimetypes
import logging
from flask_cors import CORS
from pywebpush import webpush, WebPushException
import datetime
import json
import threading
import time
from uuid import uuid4
from base64 import urlsafe_b64decode, urlsafe_b64encode
from cryptography.hazmat.primitives.asymmetric import ec
from werkzeug.utils import secure_filename

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

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "BInpwmVC5Xfb9_hWESi_O15d9CorQaVrQN-_QncpE9NNowZczH9SYGryI-3-B3YJbdZJNGh9i0C1g2k-ss58Rkw")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "yJco_xQqUqIklkhq8krWC2DM9v8NGXtGDsMG8JVxdy4")
VAPID_CLAIMS = {"sub": "mailto:admin@innovatec.com"}
AUTO_NOTIFICATION_HOURS = [9, 14, 19]
CHAT_UPLOAD_DIR = os.path.join(FRONTEND_DIR, "assets", "uploads", "chat")
TYPING_TTL_SECONDS = 6
typing_state = {}


class SuppressChatPollFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        if 'GET /chat/messages' in msg or 'GET /chat/typing' in msg or 'GET /chat/unread_count' in msg:
            return False
        return True


logging.getLogger("werkzeug").addFilter(SuppressChatPollFilter())


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
            usuario_id INTEGER,
            nombre TEXT NOT NULL,
            apellidos TEXT NOT NULL,
            fecha_nacimiento DATE,
            sexo TEXT,
            telefono TEXT,
            correo TEXT,
            terapeuta_id INTEGER,
            fecha_registro DATE DEFAULT CURRENT_DATE,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id),
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

        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            sender_user_id INTEGER NOT NULL,
            mensaje TEXT NOT NULL,
            fecha DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (paciente_id) REFERENCES pacientes(id),
            FOREIGN KEY (sender_user_id) REFERENCES usuarios(id)
        );

        CREATE TABLE IF NOT EXISTS chat_reads (
            user_id INTEGER NOT NULL,
            paciente_id INTEGER NOT NULL,
            last_read_message_id INTEGER NOT NULL DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, paciente_id),
            FOREIGN KEY (user_id) REFERENCES usuarios(id),
            FOREIGN KEY (paciente_id) REFERENCES pacientes(id)
        );

        CREATE TABLE IF NOT EXISTS push_subscriptions_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            endpoint TEXT UNIQUE NOT NULL,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES usuarios(id)
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
    if "usuario_id" not in columnas:
        cursor.execute("ALTER TABLE pacientes ADD COLUMN usuario_id INTEGER")

    # Backfill usuario_id in pacientes from matching correo when available.
    cursor.execute(
        """
        UPDATE pacientes
        SET usuario_id = (
            SELECT u.id
            FROM usuarios u
            WHERE lower(trim(u.correo)) = lower(trim(pacientes.correo))
            ORDER BY u.id DESC
            LIMIT 1
        )
        WHERE usuario_id IS NULL OR usuario_id = 0
        """
    )

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
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_paciente_fecha ON chat_messages(paciente_id, fecha)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_reads_user ON chat_reads(user_id, paciente_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_push_users_user ON push_subscriptions_users(user_id)")

    # Chat attachment compatibility for existing databases.
    cursor.execute("PRAGMA table_info(chat_messages)")
    chat_cols = [col[1] for col in cursor.fetchall()]
    if "attachment_url" not in chat_cols:
        cursor.execute("ALTER TABLE chat_messages ADD COLUMN attachment_url TEXT")
    if "attachment_name" not in chat_cols:
        cursor.execute("ALTER TABLE chat_messages ADD COLUMN attachment_name TEXT")
    if "attachment_mime" not in chat_cols:
        cursor.execute("ALTER TABLE chat_messages ADD COLUMN attachment_mime TEXT")

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

    # Canonical subscriptions for any authenticated role.
    cursor.execute(
        "INSERT OR REPLACE INTO push_subscriptions_users (endpoint, p256dh, auth, user_id) VALUES (?, ?, ?, ?)",
        (endpoint, p256dh, auth, session["user_id"])
    )

    paciente_id = None
    if session.get("rol") == "paciente":
        paciente_id = get_paciente_id_from_user(cursor, session["user_id"])
        if paciente_id:
            # Legacy table kept for backward compatibility.
            cursor.execute(
                "INSERT OR REPLACE INTO push_subscriptions (endpoint, p256dh, auth, paciente_id) VALUES (?, ?, ?, ?)",
                (endpoint, p256dh, auth, paciente_id)
            )

    cursor.execute(
        "SELECT rol FROM usuarios WHERE id = ?",
        (session["user_id"],)
    )
    role_row = cursor.fetchone()
    user_role = role_row[0] if role_row else session.get("rol")

    conn.commit()
    conn.close()

    return {"mensaje": "Suscripción push guardada", "paciente_id": paciente_id, "rol": user_role}

@app.route("/push/unsubscribe", methods=["POST"])
def push_unsubscribe():
    if "user_id" not in session:
        return {"error": "No autenticado"}, 401

    data = request.get_json() or {}
    endpoint = data.get("endpoint")
    if not endpoint:
        return {"error": "Endpoint faltante"}, 400

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    cursor.execute("DELETE FROM push_subscriptions_users WHERE endpoint = ?", (endpoint,))
    conn.commit()
    conn.close()

    return {"mensaje": "Suscripción push eliminada"}


def send_push_rows(rows, payload):
    endpoints_to_remove = []
    for endpoint, p256dh, auth in rows:
        try:
            webpush(
                subscription_info={
                    "endpoint": endpoint,
                    "keys": {
                        "p256dh": p256dh,
                        "auth": auth
                    }
                },
                data=json.dumps(payload),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS,
                timeout=4
            )
        except WebPushException as exc:
            status_code = exc.response.status_code if exc.response else None
            exc_text = str(exc)
            should_remove = (
                status_code in [401, 403, 404, 410]
                or '401' in exc_text
                or '403' in exc_text
                or '404' in exc_text
                or '410' in exc_text
            )
            if should_remove:
                endpoints_to_remove.append(endpoint)
                continue
            app.logger.warning("WebPush error (%s): %s", status_code if status_code is not None else "unknown", exc)

    if endpoints_to_remove:
        conn = conectar()
        c = conn.cursor()
        for endpoint in set(endpoints_to_remove):
            c.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
            c.execute("DELETE FROM push_subscriptions_users WHERE endpoint = ?", (endpoint,))
        conn.commit()
        conn.close()


def enviar_push_a_usuario(user_id, titulo, mensaje, url="/dashboard-paciente-home.html"):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT endpoint, p256dh, auth FROM push_subscriptions_users WHERE user_id = ?",
        (user_id,)
    )
    suscripciones = cursor.fetchall()
    conn.close()

    payload = json.dumps({
        "title": titulo,
        "body": mensaje,
        "icon": "/assets/img/favicon.png" if os.path.exists(os.path.join(FRONTEND_DIR, "assets/img/favicon.png")) else None,
        "url": url
    })

    if suscripciones:
        send_push_rows(suscripciones, json.loads(payload))


def enviar_push(paciente_id, titulo, mensaje, url="/dashboard-paciente-home.html"):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT u.id
        FROM usuarios u
        JOIN pacientes p ON lower(trim(p.correo)) = lower(trim(u.correo))
        WHERE p.id = ?
        ORDER BY u.id DESC
        LIMIT 1
        """,
        (paciente_id,)
    )
    user_row = cursor.fetchone()

    # Fallback to legacy patient-scoped subscriptions if needed.
    cursor.execute(
        "SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE paciente_id = ?",
        (paciente_id,)
    )
    legacy_rows = cursor.fetchall()
    conn.close()

    if user_row:
        enviar_push_a_usuario(user_row[0], titulo, mensaje, url=url)
        return

    payload = {
        "title": titulo,
        "body": mensaje,
        "icon": "/assets/img/favicon.png" if os.path.exists(os.path.join(FRONTEND_DIR, "assets/img/favicon.png")) else None,
        "url": url
    }
    if legacy_rows:
        send_push_rows(legacy_rows, payload)


def dispatch_push_async(func, *args, **kwargs):
    worker = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
    worker.start()


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
                "INSERT INTO pacientes (usuario_id, nombre, apellidos, fecha_nacimiento, sexo, telefono, correo, terapeuta_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, nombre or "", apellidos or "", fecha_nacimiento, sexo, telefono or "", correo, terapeuta_id)
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


def get_paciente_id_from_user(cursor, user_id):
    cursor.execute(
        """
        SELECT p.id
        FROM pacientes p
        WHERE p.usuario_id = ?
        ORDER BY p.id DESC
        LIMIT 1
        """,
        (user_id,)
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    # Legacy fallback for older rows before usuario_id was filled.
    cursor.execute(
        """
        SELECT p.id
        FROM pacientes p
        JOIN usuarios u ON lower(trim(u.correo)) = lower(trim(p.correo))
        WHERE u.id = ?
        ORDER BY p.id DESC
        LIMIT 1
        """,
        (user_id,)
    )
    row = cursor.fetchone()
    return row[0] if row else None


def resolve_chat_paciente_id(cursor, requested_paciente_id=None):
    if "user_id" not in session:
        return None, ({"error": "No autorizado"}, 401)

    rol = session.get("rol")
    if rol == "paciente":
        own_paciente_id = get_paciente_id_from_user(cursor, session["user_id"])
        if not own_paciente_id:
            return None, ({"error": "Paciente no encontrado"}, 404)
        if requested_paciente_id and requested_paciente_id != own_paciente_id:
            return None, ({"error": "Acceso prohibido"}, 403)
        return own_paciente_id, None

    if rol in ["terapeuta", "admin"]:
        if not requested_paciente_id:
            return None, ({"error": "paciente_id es requerido"}, 400)

        cursor.execute("SELECT terapeuta_id FROM pacientes WHERE id = ?", (requested_paciente_id,))
        row = cursor.fetchone()
        if not row:
            return None, ({"error": "Paciente no encontrado"}, 404)

        if rol == "terapeuta" and row[0] != session["user_id"]:
            return None, ({"error": "No puedes acceder al chat de este paciente"}, 403)

        return requested_paciente_id, None

    return None, ({"error": "Acceso prohibido"}, 403)


def get_terapeuta_id_from_paciente(cursor, paciente_id):
    cursor.execute("SELECT terapeuta_id FROM pacientes WHERE id = ?", (paciente_id,))
    row = cursor.fetchone()
    return row[0] if row else None


def upsert_chat_read(cursor, user_id, paciente_id, last_message_id):
    cursor.execute(
        """
        INSERT INTO chat_reads (user_id, paciente_id, last_read_message_id, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, paciente_id) DO UPDATE SET
            last_read_message_id = excluded.last_read_message_id,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, paciente_id, last_message_id)
    )


def get_unread_count_for_user(cursor, user_id, paciente_ids):
    if not paciente_ids:
        return {}, 0

    placeholders = ",".join(["?"] * len(paciente_ids))
    params = [user_id] + paciente_ids + [user_id]
    cursor.execute(
        f"""
        SELECT m.paciente_id, COUNT(*)
        FROM chat_messages m
        LEFT JOIN chat_reads r ON r.user_id = ? AND r.paciente_id = m.paciente_id
        WHERE m.paciente_id IN ({placeholders})
          AND m.sender_user_id != ?
          AND m.id > COALESCE(r.last_read_message_id, 0)
        GROUP BY m.paciente_id
        """,
        params
    )
    rows = cursor.fetchall()
    by_paciente = {int(r[0]): int(r[1]) for r in rows}
    total = sum(by_paciente.values())
    return by_paciente, total


def get_latest_unread_preview_for_user(cursor, user_id, paciente_ids):
    if not paciente_ids:
        return None

    placeholders = ",".join(["?"] * len(paciente_ids))
    params = [user_id] + paciente_ids + [user_id]
    cursor.execute(
        f"""
        SELECT m.paciente_id, m.mensaje, m.attachment_name, p.nombre, p.apellidos, p.correo
        FROM chat_messages m
        JOIN pacientes p ON p.id = m.paciente_id
        LEFT JOIN chat_reads r ON r.user_id = ? AND r.paciente_id = m.paciente_id
        WHERE m.paciente_id IN ({placeholders})
          AND m.sender_user_id != ?
          AND m.id > COALESCE(r.last_read_message_id, 0)
        ORDER BY m.id DESC
        LIMIT 1
        """,
        params
    )
    row = cursor.fetchone()
    if not row:
        return None

    paciente_id = int(row[0])
    mensaje = (row[1] or "").strip()
    attachment_name = (row[2] or "").strip()
    sender_name = ((row[3] or "") + " " + (row[4] or "")).strip() or (row[5] or f"Paciente {paciente_id}")

    if mensaje:
        preview = mensaje
    elif attachment_name:
        preview = f"Adjunto: {attachment_name}"
    else:
        preview = "Nuevo mensaje"

    preview = preview if len(preview) <= 120 else (preview[:117] + "...")
    return {
        "paciente_id": paciente_id,
        "sender_name": sender_name,
        "preview": preview
    }


def get_peer_typing_state(cursor, paciente_id, current_user_id):
        now = time.time()
        expired = [k for k, exp in typing_state.items() if exp < now]
        for k in expired:
                typing_state.pop(k, None)

        cursor.execute(
                """
                SELECT id, nombre, apellidos, correo
                FROM usuarios
                WHERE id != ?
                    AND (
                        id = (SELECT terapeuta_id FROM pacientes WHERE id = ?)
                        OR id = (SELECT usuario_id FROM pacientes WHERE id = ?)
                    )
                LIMIT 5
                """,
                (current_user_id, paciente_id, paciente_id)
        )
        peers = cursor.fetchall()

        for peer in peers:
                peer_id = peer[0]
                if typing_state.get((paciente_id, peer_id), 0) >= now:
                        peer_name = ((peer[1] or "") + " " + (peer[2] or "")).strip() or (peer[3] or "Usuario")
                        return True, peer_name

        return False, None


@app.route("/chat/context", methods=["GET"])
def chat_context():
    if "user_id" not in session:
        return {"error": "No autorizado"}, 401

    conn = conectar()
    cursor = conn.cursor()

    requested_paciente_id = request.args.get("paciente_id", type=int)
    paciente_id, error = resolve_chat_paciente_id(cursor, requested_paciente_id)
    if error:
        conn.close()
        body, code = error
        return body, code

    cursor.execute("SELECT usuario_id, nombre, apellidos, correo, terapeuta_id FROM pacientes WHERE id = ?", (paciente_id,))
    p = cursor.fetchone()
    if not p:
        conn.close()
        return {"error": "Paciente no encontrado"}, 404

    p_usuario_id, p_nombre, p_apellidos, p_correo, terapeuta_id = p

    cursor.execute("SELECT id, correo, nombre, apellidos FROM usuarios WHERE id = ?", (session["user_id"],))
    me = cursor.fetchone()
    me_data = {
        "id": me[0],
        "correo": me[1],
        "nombre": me[2],
        "apellidos": me[3],
        "rol": session.get("rol")
    } if me else None

    if session.get("rol") == "paciente":
        cursor.execute("SELECT id, correo, nombre, apellidos FROM usuarios WHERE id = ?", (terapeuta_id,))
        peer = cursor.fetchone()
        peer_data = {
            "id": peer[0],
            "correo": peer[1],
            "nombre": peer[2],
            "apellidos": peer[3],
            "rol": "terapeuta"
        } if peer else None
    else:
        patient_display_name = ((p_nombre or "") + " " + (p_apellidos or "")).strip() or f"Paciente {paciente_id}"
        peer_data = {
            "id": p_usuario_id,
            "correo": p_correo,
            "nombre": p_nombre,
            "apellidos": p_apellidos,
            "display_name": patient_display_name,
            "rol": "paciente"
        }

    conn.close()
    return {
        "paciente_id": paciente_id,
        "me": me_data,
        "peer": peer_data
    }


@app.route("/chat/messages", methods=["GET"])
def chat_messages_get():
    if "user_id" not in session:
        return {"error": "No autorizado"}, 401

    conn = conectar()
    cursor = conn.cursor()

    requested_paciente_id = request.args.get("paciente_id", type=int)
    paciente_id, error = resolve_chat_paciente_id(cursor, requested_paciente_id)
    if error:
        conn.close()
        body, code = error
        return body, code

    cursor.execute(
        """
                 SELECT m.id, m.sender_user_id, m.mensaje, m.fecha,
                         m.attachment_url, m.attachment_name, m.attachment_mime,
                             u.rol, u.nombre, u.apellidos, u.correo,
                             p.nombre, p.apellidos
        FROM chat_messages m
        JOIN usuarios u ON u.id = m.sender_user_id
                LEFT JOIN pacientes p ON p.id = m.paciente_id
        WHERE m.paciente_id = ?
        ORDER BY m.id ASC
        LIMIT 500
        """,
        (paciente_id,)
    )
    rows = cursor.fetchall()

    data = []
    max_message_id = 0
    for r in rows:
        sender_rol = r[7]
        if sender_rol in ["terapeuta", "admin"]:
            therapist_name = ((r[8] or "") + " " + (r[9] or "")).strip() or (r[10] or "Terapeuta")
            display_name = f"[TERAPEUTA] {therapist_name}"
        else:
            patient_name = ((r[11] or "") + " " + (r[12] or "")).strip()
            display_name = patient_name or f"Paciente {paciente_id}"

        data.append({
            "id": r[0],
            "sender_user_id": r[1],
            "mensaje": r[2],
            "fecha": r[3],
            "attachment_url": r[4],
            "attachment_name": r[5],
            "attachment_mime": r[6],
            "sender_rol": sender_rol,
            "sender_nombre": display_name
        })
        if r[0] > max_message_id:
            max_message_id = r[0]

    if max_message_id > 0:
        upsert_chat_read(cursor, session["user_id"], paciente_id, max_message_id)
        conn.commit()

    peer_typing, peer_name = get_peer_typing_state(cursor, paciente_id, session["user_id"])
    conn.close()

    return {
        "paciente_id": paciente_id,
        "messages": data,
        "last_read_message_id": max_message_id,
        "peer_typing": peer_typing,
        "peer_name": peer_name
    }


@app.route("/chat/messages", methods=["POST"])
def chat_messages_post():
    if "user_id" not in session:
        return {"error": "No autorizado"}, 401

    data = request.get_json() or {}
    mensaje = (data.get("mensaje") or "").strip()
    attachment_url = (data.get("attachment_url") or "").strip() or None
    attachment_name = (data.get("attachment_name") or "").strip() or None
    attachment_mime = (data.get("attachment_mime") or "").strip() or None
    if not mensaje and not attachment_url:
        return {"error": "Mensaje vacio"}, 400

    conn = conectar()
    cursor = conn.cursor()

    requested_paciente_id = data.get("paciente_id")
    try:
        requested_paciente_id = int(requested_paciente_id) if requested_paciente_id is not None else None
    except ValueError:
        conn.close()
        return {"error": "paciente_id invalido"}, 400

    paciente_id, error = resolve_chat_paciente_id(cursor, requested_paciente_id)
    if error:
        conn.close()
        body, code = error
        return body, code

    cursor.execute(
        """
        INSERT INTO chat_messages (paciente_id, sender_user_id, mensaje, attachment_url, attachment_name, attachment_mime)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (paciente_id, session["user_id"], mensaje, attachment_url, attachment_name, attachment_mime)
    )
    message_id = cursor.lastrowid

    upsert_chat_read(cursor, session["user_id"], paciente_id, message_id)
    conn.commit()
    conn.close()

    chat_url_patient = "/chat.html"
    chat_url_therapist = f"/chat.html?paciente_id={paciente_id}"

    # Push therapist/admin -> patient
    if session.get("rol") in ["terapeuta", "admin"]:
        preview_text = mensaje or f"Archivo: {attachment_name or 'adjunto'}"
        preview = preview_text if len(preview_text) <= 120 else (preview_text[:117] + "...")
        dispatch_push_async(enviar_push, paciente_id, "Nuevo mensaje de tu fisioterapeuta", preview, url=chat_url_patient)

    # Push patient -> therapist
    if session.get("rol") == "paciente":
        conn = conectar()
        cursor = conn.cursor()
        terapeuta_id = get_terapeuta_id_from_paciente(cursor, paciente_id)
        conn.close()
        if terapeuta_id:
            preview_text = mensaje or f"Archivo: {attachment_name or 'adjunto'}"
            preview = preview_text if len(preview_text) <= 120 else (preview_text[:117] + "...")
            dispatch_push_async(enviar_push_a_usuario, terapeuta_id, "Nuevo mensaje de un paciente", preview, url=chat_url_therapist)

    return {"mensaje": "Mensaje enviado", "id": message_id, "paciente_id": paciente_id}


@app.route("/chat/upload", methods=["POST"])
def chat_upload():
    if "user_id" not in session:
        return {"error": "No autorizado"}, 401

    conn = conectar()
    cursor = conn.cursor()

    requested_paciente_id = request.form.get("paciente_id", type=int)
    paciente_id, error = resolve_chat_paciente_id(cursor, requested_paciente_id)
    if error:
        conn.close()
        body, code = error
        return body, code

    if "file" not in request.files:
        conn.close()
        return {"error": "Archivo faltante"}, 400

    file = request.files["file"]
    if not file or not file.filename:
        conn.close()
        return {"error": "Archivo inválido"}, 400

    original_name = secure_filename(file.filename)
    ext = os.path.splitext(original_name)[1].lower()
    unique_name = f"{int(time.time())}_{uuid4().hex[:10]}{ext}"

    os.makedirs(CHAT_UPLOAD_DIR, exist_ok=True)
    absolute_path = os.path.join(CHAT_UPLOAD_DIR, unique_name)
    file.save(absolute_path)

    rel_url = f"/assets/uploads/chat/{unique_name}"
    mime = file.mimetype or mimetypes.guess_type(original_name)[0] or "application/octet-stream"

    conn.close()
    return {
        "mensaje": "Archivo subido",
        "paciente_id": paciente_id,
        "attachment_url": rel_url,
        "attachment_name": original_name,
        "attachment_mime": mime
    }


@app.route("/chat/typing", methods=["POST"])
def chat_typing_post():
    if "user_id" not in session:
        return {"error": "No autorizado"}, 401

    data = request.get_json() or {}
    requested_paciente_id = data.get("paciente_id")
    try:
        requested_paciente_id = int(requested_paciente_id) if requested_paciente_id is not None else None
    except ValueError:
        return {"error": "paciente_id invalido"}, 400

    conn = conectar()
    cursor = conn.cursor()
    paciente_id, error = resolve_chat_paciente_id(cursor, requested_paciente_id)
    conn.close()
    if error:
        body, code = error
        return body, code

    is_typing = bool(data.get("is_typing", True))
    key = (paciente_id, session["user_id"])
    if is_typing:
        typing_state[key] = time.time() + TYPING_TTL_SECONDS
    else:
        typing_state.pop(key, None)

    return {"ok": True}


@app.route("/chat/typing", methods=["GET"])
def chat_typing_get():
    if "user_id" not in session:
        return {"error": "No autorizado"}, 401

    conn = conectar()
    cursor = conn.cursor()
    requested_paciente_id = request.args.get("paciente_id", type=int)
    paciente_id, error = resolve_chat_paciente_id(cursor, requested_paciente_id)
    if error:
        conn.close()
        body, code = error
        return body, code

    peer_typing, peer_name = get_peer_typing_state(cursor, paciente_id, session["user_id"])
    conn.close()

    return {"paciente_id": paciente_id, "peer_typing": peer_typing, "peer_name": peer_name}


@app.route("/chat/unread_count", methods=["GET"])
def chat_unread_count():
    if "user_id" not in session:
        return {"error": "No autorizado"}, 401

    conn = conectar()
    cursor = conn.cursor()
    rol = session.get("rol")

    paciente_ids = []
    if rol == "paciente":
        own_id = get_paciente_id_from_user(cursor, session["user_id"])
        if own_id:
            paciente_ids = [own_id]
    elif rol in ["terapeuta", "admin"]:
        cursor.execute("SELECT id FROM pacientes WHERE terapeuta_id = ?", (session["user_id"],))
        paciente_ids = [r[0] for r in cursor.fetchall()]
    else:
        conn.close()
        return {"error": "Acceso prohibido"}, 403

    by_paciente, total = get_unread_count_for_user(cursor, session["user_id"], paciente_ids)
    latest_preview = get_latest_unread_preview_for_user(cursor, session["user_id"], paciente_ids)
    conn.close()
    return {"total": total, "by_paciente": by_paciente, "latest_preview": latest_preview}


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