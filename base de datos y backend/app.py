from flask import Flask, jsonify, request, session, make_response, send_from_directory
import os
import sqlite3
from flask_cors import CORS

app = Flask(__name__)

#para login
app.secret_key = "clave_secreta"

CORS(app, supports_credentials=True)

app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_SECURE"] = True

@app.route("/me", methods=["GET"])
def me():
    print("SESSION EN /me:", dict(session))
    if "user_id" not in session:
        return {"error": "No autenticado"}, 401

    return {
        "user_id": session["user_id"],
        "rol": session.get("rol")
    }

def conectar():
    conn = sqlite3.connect("fisioterapp.db")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@app.route("/")
def frontend():
    return send_from_directory("C:/Users/julic/OneDrive/Desktop/Proyecto innovatec/innovatec-fisioapp", "index-sign_in.html")

@app.route('/<path:path>')
def serve_files(path):
    return send_from_directory(
        "C:/Users/julic/OneDrive/Desktop/Proyecto innovatec/innovatec-fisioapp",
        path
    )


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()

    correo = data.get("correo")
    password = data.get("password")

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, correo, rol FROM usuarios WHERE correo=? AND password=?",
        (correo, password)
    )

    user = cursor.fetchone()
    conn.close()
    print("LOGIN USER:", user)
    if user:
        session.clear()
        session["user_id"] = user[0]
        session["rol"] = user[2]   # 🔥 agregar esto
        return {
            "mensaje": "Login exitoso",
            "usuario": {
                "id": user[0],
                "correo": user[1],
                "rol": user[2]
            }
        }
    else:
        return {"mensaje": "Credenciales incorrectas"}, 401

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
    app.run(debug=True)