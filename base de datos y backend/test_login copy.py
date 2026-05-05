import requests

url = "http://127.0.0.1:5000/login"

datos = {
    "correo": "terapeuta@medico.com",
    "password": "4321"
}

res = requests.post(url, json=datos)
print(res.json())