# 💳 Asistente de Convenios de Pago

Aplicación **Streamlit** para gestionar convenios de pago con soporte de:
- **Usuarios y roles** (`admin`, `operador`, `cliente`)
- **Creación de convenios** con **adjuntos** (documentación de la deuda)
- **Cálculo de cuotas** (Sistema Francés y, si está habilitado el interés, también Capital Fijo/Interés sobre saldo)
- **Gestión de pagos/comprobantes** (con y sin archivo adjunto)
- **Aprobación/rechazo** de pagos por el operador
- **Métricas** (tableros admin/operador)
- **Recordatorios automáticos** (worker + GitHub Actions)
- **Exportación a PDF** con detalle de cuotas (incluye totales) y documentación adjunta

Backend: **Firebase** (Firestore + Storage + Auth)  
Email: **SMTP** configurable

---

## 🧭 Índice

- [Arquitectura](#arquitectura)
- [Roles y permisos](#roles-y-permisos)
- [Modelo de datos](#modelo-de-datos)
- [Estados y ciclo de vida del convenio](#estados-y-ciclo-de-vida-del-convenio)
- [Cálculo de cuotas](#cálculo-de-cuotas)
- [Interés: configuración global](#interés-configuración-global)
- [Adjuntos y PDF del convenio](#adjuntos-y-pdf-del-convenio)
- [Pagos y comprobantes](#pagos-y-comprobantes)
- [Recordatorios automáticos](#recordatorios-automáticos)
- [Estructura del repo](#estructura-del-repo)
- [Requisitos e instalación local](#requisitos-e-instalación-local)
- [Configuración (secrets/variables)](#configuración-secretsvariables)
- [Primer uso (seed admin)](#primer-uso-seed-admin)
- [Despliegue / CI](#despliegue--ci)
- [Colores y estado visual](#colores-y-estado-visual)
- [Solución de problemas](#solución-de-problemas)
- [Roadmap sugerido](#roadmap-sugerido)
- [Licencia y créditos](#licencia-y-créditos)
- [Anexo: Guía rápida para Copilot](#anexo-guía-rápida-para-copilot)

---

## Arquitectura

- **UI/Servidor**: [Streamlit](https://streamlit.io)
- **Auth**: Firebase Authentication  
  - Alta/gestión via **Firebase Admin SDK**  
  - Login con **Identity Toolkit REST** (`accounts:signInWithPassword`)
- **Base de datos**: **Cloud Firestore** (Admin SDK)
- **Archivos**: **Firebase Storage** (Admin SDK)  
  - Comprobantes y adjuntos de convenios
- **Correo**: SMTP estándar (TLS/SSL) con plantillas HTML simples
- **Worker de recordatorios**: script Python ejecutado por **GitHub Actions** en cron

---

## Roles y permisos

- **Admin**
  - Panel de métricas globales
  - Aprobación/rechazo de usuarios
  - **Configuración global** (habilitar/deshabilitar interés)
  - Eliminar convenios
  - Diagnóstico
- **Operador**
  - Crear convenios y **adjuntar documentos**
  - Recalcular calendario (mientras esté en `DRAFT`/`PENDING_ACCEPTANCE`)
  - Enviar a aceptación
  - **Aprobar/rechazar pagos** (con o sin comprobante)
  - Panel de métricas personales
- **Cliente**
  - Aceptar/rechazar convenio
  - **Subir comprobante** de pago
  - **Marcar pago sin comprobante** (queda `PENDING` hasta revisión)
  - Ver su calendario de cuotas y estado

---

## Modelo de datos
users (colección)
{uid}: {
email, full_name, role ∈ {admin, operador, cliente},
status ∈ {PENDING, APPROVED, REJECTED},
rejection_note?
}
agreements (colección)
{agreementId}: {
title, notes,
operator_id (uid),
client_id? (uid),          // puede no existir si el cliente aún no se registró
client_email,              // fallback
principal (float),
interest_rate (float mensual, p.ej. 0.05 representa 5%),
installments (int),
method ∈ {"french","declining"},
status ∈ {DRAFT, PENDING_ACCEPTANCE, ACTIVE, COMPLETED, CANCELLED, REJECTED},
start_date (YYYY-MM-DD),
created_at, accepted_at?, completed_at?
}
agreements/{agreementId}/installments (subcolección)
{installmentId}: {
number (1..n),
due_date (YYYY-MM-DD),
capital (float),
interest (float),
total (float),
paid (bool),
paid_at?,
last_reminder_sent?,
// flujo de comprobantes/pagos
receipt_status? ∈ {PENDING, APPROVED, REJECTED},
receipt_url?, receipt_note?,
receipt_uploaded_by?, receipt_uploaded_at?
}
agreements/{agreementId}/attachments (subcolección)
{attachmentId}: {
name, path, content_type, size,
uploaded_by, uploaded_at
> **Nota**: `client_email` se guarda como *fallback* para listar convenios del cliente aunque todavía no tenga `uid`.

---

## Estados y ciclo de vida del convenio

1. **DRAFT**: creado por operador; puede recalcular cuotas y adjuntar documentos.
2. **PENDING_ACCEPTANCE**: enviado al cliente; este **acepta** o **rechaza**.
3. **ACTIVE**: aceptado y vigente; se registran pagos (con o sin comprobante).
4. **COMPLETED**: **automático** cuando **todas** las cuotas están `paid = True`.
5. **CANCELLED**: cancelado (solo en etapas iniciales).
6. **REJECTED**: rechazado por el cliente (se guarda `rejection_note`).

---

## Cálculo de cuotas

Módulo `calculations.py`:
- **Sistema Francés** (`french`): cuota fija; última cuota ajusta por redondeo.
- **Capital Fijo / Interés sobre saldo** (`declining`): capital constante, última cuota ajusta por redondeo.

> **Totales visibles**: en la tabla de cuotas se muestra una fila **TOTAL** (suma de capital, interés y total).

---

## Interés: configuración global

- **Admin → Configuración**: `interest_enabled` (on/off) persistido en `config/settings`.
- Si **está deshabilitado**:
  - **No** se muestra el campo “Interés mensual (%)”.
  - El **método** queda **fijo / deshabilitado** (“Sistema francés”), **no seleccionable**.
  - `interest_rate` se guarda en 0.0.

---

## Adjuntos y PDF del convenio

- **Adjuntos** (operador, al crear el convenio):
  - PDF/JPG/PNG múltiples (máx. 10MB c/u).
  - Se guardan en `agreements/{id}/attachments` y en Storage.
- **PDF** exportable desde la vista del convenio:
  - Portada con datos clave (cliente, operador, principal, método, interés).
  - **Calendario de cuotas con fila TOTAL**.
  - **Documentación adjunta**: imágenes incrustadas; PDFs listados.

---

## Pagos y comprobantes

- **Cliente**:
  - Sube comprobante (PDF/JPG/PNG) → `receipt_status = PENDING`.
  - **O** declara pago **sin comprobante** → también `PENDING`.
- **Operador**:
  - En **Comprobantes**: **aprueba** (marca `paid=True`, `APPROVED`) o **rechaza** (guarda `receipt_note`).
  - En el listado del convenio: puede **marcar pagada / revertir** una cuota **aunque no haya comprobante**.
- **Auto-complete**: si **todas** las cuotas quedan `paid=True`, el convenio pasa a `COMPLETED`.

---

## Recordatorios automáticos

Archivo `send_reminders.py` (worker):
- Recorre convenios `ACTIVE` y cuotas **impagas**:
  - Próximas a vencer (≤ N días)
  - **Hoy**
  - Vencidas (≤ M días)
- Respeta `last_reminder_sent` con un **cooldown** para no spamear.
- Notifica al cliente (y copia opcional al operador).
- Se ejecuta:
  - **Local**: `python send_reminders.py`
  - **GitHub Actions** (CRON): ver workflow.

---

## Estructura del repo


.
├─ app.py                 # App principal (Streamlit)
├─ auth.py                # Registro/login, roles, gestión de usuarios
├─ calculations.py        # Cálculo de cuotas (francés/declining) con ajuste de redondeos
├─ emailer.py             # SMTP y plantillas
├─ firebase_init.py       # Inicialización Admin SDK (credenciales/bucket)
├─ send_reminders.py      # Worker de recordatorios (CLI/Streamlit opcional)
├─ requirements.txt       # Dependencias
└─ .github/
└─ workflows/
└─ reminders.yml    # CRON diario de recordatorios (12:00 UTC)

---

## Requisitos e instalación local

bash
# 1) Entorno
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate

# 2) Dependencias
pip install --upgrade pip
pip install -r requirements.txt

# 3) Configurar secrets de Streamlit
# Crear .streamlit/secrets.toml (ver abajo)

# 4) Ejecutar la app
streamlit run app.py

requirements.txt:
streamlit
firebase-admin
google-cloud-firestore
requests
pytz
reportlab
pandas
Configuración (secrets/variables)
.streamlit/secrets.toml (app)

# Firebase (pegar contenido literal del JSON del service account)
FIREBASE_CREDENTIALS = """{
  "type":"service_account",
  "project_id":"<tu-proyecto>",
  ...
}"""
FIREBASE_PROJECT_ID = "<tu-proyecto>"
# opcional, si querés forzar el bucket:
FIREBASE_STORAGE_BUCKET = "<tu-proyecto>.appspot.com"

# Web API Key para login por REST (Identity Toolkit)
FIREBASE_WEB_API_KEY = "<apikey>"

# Base URL de la app (para links en emails)
APP_BASE_URL = "https://tu-app.streamlit.app"

# SMTP
SMTP_HOST   = "smtp.tu-dominio.com"
SMTP_PORT   = "587"
SMTP_USER   = "no-reply@tu-dominio.com"
SMTP_PASS   = "********"
SMTP_USE_TLS = "true"
SMTP_SENDER = "Asistente de Convenios <no-reply@tu-dominio.com>"

# (Opcional) admins a los que se envían avisos de nuevos usuarios/convenios
ADMIN_EMAILS = "admin1@dominio.com, admin2@dominio.com"

Variables para el worker (local o Actions)

FIREBASE_CREDENTIALS (JSON en una sola línea, o archivo en local con ADC)
FIREBASE_PROJECT_ID
SMTP_*
APP_BASE_URL
Opcionales del worker:

APP_TZ (default: America/Argentina/Buenos_Aires)
REMINDER_DAYS_BEFORE, REMINDER_DAYS_AFTER, REMINDER_COOLDOWN_DAYS
Primer uso (seed admin)

Levantá streamlit run app.py.
Si no existen usuarios, la app te pedirá crear el Admin (email/contraseña).
Iniciá sesión como admin.
Configuración: habilitá o deshabilitá interés según tu operación.
Creá operadores y aprobá clientes según corresponda.


Despliegue / CI

GitHub Actions: .github/workflows/reminders.yml corre el worker a las 12:00 UTC (≈ 09:00 Buenos Aires), con disparo manual disponible.
Streamlit Cloud o VM/Contenedor: ejecutar streamlit run app.py.
ADC (Application Default Credentials): firebase_init.py intentará ADC si no hay FIREBASE_CREDENTIALS.


Colores y estado visual

PENDING_ACCEPTANCE → naranja
REJECTED → rojo
ACTIVE / COMPLETED → verde
CANCELLED → gris

En cuotas:

PAGADA / APROBADO → 🟢
PENDIENTE → 🟠
RECHAZADO → 🔴


Solución de problemas

No conecta a Firestore: revisá FIREBASE_CREDENTIALS y FIREBASE_PROJECT_ID.
No llegan emails: validá SMTP_*; verificá SPF/DKIM/DMARC y carpeta SPAM.
Cliente no ve su convenio: si aún no tiene cuenta, igual se lista por client_email. Asegurate de que el correo coincida.
Error de widgets duplicados (StreamlitDuplicateElementId) → ya se corrige asignando key= único en cada botón (se hizo en el código).
PDF no incrusta imágenes: verificá el tipo de contenido y permisos del bucket.


Roadmap sugerido

Filtros/orden/paginación en listados grandes
Exportación CSV/Excel del calendario
Templates HTML más ricos para emails
Gráficos de aceptación y mora
Integraciones alternativas de storage (S3/R2)
Reset de contraseña por link (además del temporal)


Licencia y créditos

Licencia: GPL-3.0
Desarrollo: Germán Berterreix
Soporte y mejoras: colaboradores del repo


Anexo: Guía rápida para Copilot

Contexto clave para entender el proyecto en futuras conversaciones:


Interés globalmente configurable: config/settings.interest_enabled.

Si está apagado, la UI no muestra el campo de interés y el método queda deshabilitado en “Sistema francés”.


Pagos:

El cliente puede subir comprobante o declarar pago sin comprobante (queda PENDING).
El operador puede aprobar/rechazar y también marcar pagada/revertir sin comprobante.
Cuando todas están pagadas → convenio COMPLETED.


Adjuntos:

Se guardan como subcolección attachments en cada convenio y en Storage.
El PDF incluye calendario con totales + adjuntos (imágenes incrustadas; PDFs listados).


Recordatorios:

send_reminders.py corre diario por Actions y puede ejecutarse manual/local.


Archivos clave:

app.py (toda la UI y flujos)
auth.py, emailer.py, firebase_init.py
calculations.py (francés/declining con ajuste de redondeos)
send_reminders.py (worker)
Workflow: .github/workflows/reminders.yml


