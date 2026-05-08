from flask import Flask, jsonify, request, session, send_from_directory
import os
import sqlite3
import random
import string
import bcrypt
from flask_cors import CORS

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


def initialize_database():
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
        """
    )

    # Asegura compatibilidad con bases antiguas sin terapeuta_id.
    cursor.execute("PRAGMA table_info(pacientes)")
    columnas = [col[1] for col in cursor.fetchall()]
    if "terapeuta_id" not in columnas:
        cursor.execute("ALTER TABLE pacientes ADD COLUMN terapeuta_id INTEGER")

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

    if not correo or not password:
        return {"mensaje": "Correo y password son obligatorios"}, 400

    if rol not in ["admin", "terapeuta", "paciente"]:
        return {"mensaje": "Rol inválido"}, 400

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
                "INSERT INTO pacientes (nombre, apellidos, correo, terapeuta_id) VALUES (?, ?, ?, ?)",
                (nombre or "", apellidos or "", correo, terapeuta_id)
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


#logout
@app.route("/logout", methods=["POST", "GET"])
def logout():
    session.clear()
    return {"mensaje": "Sesión cerrada"}

if __name__ == "__main__":
    initialize_database()
    app.run(debug=True)