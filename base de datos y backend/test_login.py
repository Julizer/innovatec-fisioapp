import requests

url = "http://127.0.0.1:5000/login"

datos = {
    "correo": "admin@test.com",
    "password": "1234"
}

res = requests.post(url, json=datos)
print(res.json())