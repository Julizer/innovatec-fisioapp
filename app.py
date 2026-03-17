from flask import Flask, request, jsonify
import mysql.connector

app = Flask(__name__)

#Conexión a MySQL
conexion = mysql.connector.connect(
    host="localhost",
    user="root",
    password="tu_password",
    database="fisioterapp"
)

#LOGIN
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()

    usuario = data.get("usuario")
    password = data.get("password")

    cursor = conexion.cursor()
    cursor.execute(
        "SELECT * FROM usuarios WHERE usuario=%s AND password=%s",
        (usuario, password)
    )

    user = cursor.fetchone()

    if user:
        return jsonify({"success": True})
    else:
        return jsonify({"success": False})


#REGISTRO
@app.route("/register", methods=["POST"])
def register():
    data = request.get_json()

    usuario = data.get("usuario")
    password = data.get("password")

    cursor = conexion.cursor()

    #Verificar si ya existe
    cursor.execute(
        "SELECT * FROM usuarios WHERE usuario=%s",
        (usuario,)
    )

    if cursor.fetchone():
        return jsonify({"success": False, "error": "Usuario ya existe"})

    #Insertar usuario
    cursor.execute(
        "INSERT INTO usuarios (usuario, password) VALUES (%s, %s)",
        (usuario, password)
    )

    conexion.commit()

    return jsonify({"success": True})


#Ejecutar servidor
if __name__ == "__main__":
    app.run(debug=True)