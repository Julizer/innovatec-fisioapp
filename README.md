# innovatec-fisioapp
Proyecto ITH

## Requisitos

- Python 3.10+
- pip

## Instalacion rapida (Windows)

1. Abrir terminal en la raiz del proyecto.
2. Crear entorno virtual:

```powershell
python -m venv .venv
```

3. Activar entorno virtual:

```powershell
.\.venv\Scripts\Activate.ps1
```

4. Instalar dependencias:

```powershell
pip install flask flask-cors
```

## Ejecutar la app

1. Desde la raiz del proyecto, ejecutar:

```powershell
python "base de datos y backend\app.py"
```

2. Abrir en navegador:

```text
http://127.0.0.1:5000
```

## Flujo recomendado para probar

1. Ir a `index-sign_up.html` y crear usuario.
2. Iniciar sesion en `index-sign_in.html`.
3. Entrar a `dashboard-terapeuta-patients.html` para validar lectura de pacientes.

## Notas tecnicas

- La base SQLite se crea automaticamente en `base de datos y backend/fisioterapp.db`.
- El backend sirve los archivos HTML del frontend desde la raiz del proyecto.
- En local, la sesion usa cookies configuradas para funcionar con HTTP.
