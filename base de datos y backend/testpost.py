import requests

url = "http://127.0.0.1:5000/pacientes"

datos = {
    "nombre": "pedro",
    "apellidos": "pascal",
    "fecha_nacimiento": "2006-01-01",
    "sexo": "",
    "telefono": "6621234532",
    "correo": "pedro@test.com"
}

respuesta = requests.post(url, json=datos)

print(respuesta.status_code)
print(respuesta.json())