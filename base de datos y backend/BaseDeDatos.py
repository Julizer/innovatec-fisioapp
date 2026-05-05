import sqlite3

conn = sqlite3.connect("fisioterapp.db")
conn.execute("PRAGMA foreign_keys = ON")
cursor = conn.cursor()

cursor.executescript("""
-- =========================
-- USUARIOS (login del sistema)
-- =========================
CREATE TABLE usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    correo TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    rol TEXT CHECK(rol IN ('admin', 'terapeuta')) NOT NULL
);

-- =========================
-- PACIENTES
-- =========================
CREATE TABLE pacientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    apellidos TEXT NOT NULL,
    fecha_nacimiento DATE,
    sexo TEXT,
    telefono TEXT,
    correo TEXT,
    fecha_registro DATE DEFAULT CURRENT_DATE
);

-- =========================
-- TERAPEUTAS
-- =========================
CREATE TABLE terapeutas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    especialidad TEXT,
    telefono TEXT,
    correo TEXT
);

-- =========================
-- CITAS
-- =========================
CREATE TABLE citas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL,
    terapeuta_id INTEGER NOT NULL,
    fecha DATE NOT NULL,
    hora TIME NOT NULL,
    estado TEXT CHECK(estado IN ('pendiente', 'completada', 'cancelada')) NOT NULL,
    FOREIGN KEY (paciente_id) REFERENCES pacientes(id),
    FOREIGN KEY (terapeuta_id) REFERENCES terapeutas(id)
);

-- =========================
-- SESIONES (1 a 1 con citas)
-- =========================
CREATE TABLE sesiones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cita_id INTEGER UNIQUE NOT NULL,
    diagnostico TEXT,
    notas TEXT,
    FOREIGN KEY (cita_id) REFERENCES citas(id)
);

-- =========================
-- PLANES DE TRATAMIENTO
-- =========================
CREATE TABLE planes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL,
    descripcion TEXT,
    fecha_inicio DATE,
    fecha_fin DATE,
    FOREIGN KEY (paciente_id) REFERENCES pacientes(id)
);

-- =========================
-- EJERCICIOS
-- =========================
CREATE TABLE ejercicios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    descripcion TEXT
);

-- =========================
-- RELACIÓN PLAN-EJERCICIOS (N:M)
-- =========================
CREATE TABLE plan_ejercicios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    ejercicio_id INTEGER NOT NULL,
    repeticiones INTEGER,
    frecuencia TEXT,
    FOREIGN KEY (plan_id) REFERENCES planes(id),
    FOREIGN KEY (ejercicio_id) REFERENCES ejercicios(id)
);

-- =========================
-- PROGRESO DEL PACIENTE
-- =========================
CREATE TABLE progreso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sesion_id INTEGER NOT NULL,
    dolor_nivel INTEGER CHECK(dolor_nivel BETWEEN 1 AND 10),
    movilidad TEXT,
    observaciones TEXT,
    fecha DATE DEFAULT CURRENT_DATE,
    FOREIGN KEY (sesion_id) REFERENCES sesiones(id)
);
""")

conn.commit()
conn.close()

print("Base de datos creada correctamente")