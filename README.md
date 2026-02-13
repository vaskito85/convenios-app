# 馃挸 Asistente de Convenios de Pago

Aplicación **Streamlit** para gestionar convenios de pago con soporte de:

- **Usuarios y roles** (`admin`, `operador`, `cliente`).
- **Creación de convenios** con **adjuntos** (documentación de la deuda) y **cálculo de cuotas**.
- **Gestión de pagos y comprobantes** (con y **sin** archivo adjunto).
- **Aprobación/Rechazo** de pagos por operador.
- **Métricas** y tableros (admin/operador).
- **Recordatorios automáticos** de cuotas (worker + GitHub Actions).
- **Exportación a PDF** con detalle del calendario de cuotas (incluye **totales**) y listado/preview de documentación adjunta.
- **Parámetro global de interés** (on/off) administrable; si está **off** el método de cálculo queda **fijo** y **deshabilitado**.

Backend: **Firebase** (Firestore + Storage + Auth).  
Email: **SMTP** configurable.

---

## Índice

- [Arquitectura](#arquitectura)
- [Roles y permisos](#roles-y-permisos)
- [Modelo de datos](#modelo-de-datos)
- [Estados y ciclo de vida](#estados-y-ciclo-de-vida)
- [Cálculo de cuotas](#cálculo-de-cuotas)
- [Interés (configuración global)](#interés-configuración-global)
- [Adjuntos y PDF](#adjuntos-y-pdf)
- [Pagos y comprobantes](#pagos-y-comprobantes)
- [Recordatorios automáticos](#recordatorios-automáticos)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Requisitos e instalación local](#requisitos-e-instalación-local)
- [Configuración (secrets/variables)](#configuración-secretsvariables)
- [Primer uso (seed admin)](#primer-uso-seed-admin)
- [Despliegue / CI](#despliegue--ci)
- [Colores y estados visuales](#colores-y-estados-visuales)
- [Seguridad y buenas prácticas](#seguridad-y-buenas-prácticas)
- [Solución de problemas](#solución-de-problemas)
- [FAQ](#faq)
- [Roadmap sugerido](#roadmap-sugerido)
- [Changelog (esta versión)](#changelog-esta-versión)
- [Licencia y créditos](#licencia-y-créditos)
- [Anexo: Guía rápida para Copilot](#anexo-guía-rápida-para-copilot)

---

## Arquitectura

- **UI/Servidor**: [Streamlit](https://streamlit.io/).
- **Autenticación**: Firebase Authentication  
  - Alta/gestión con **Firebase Admin SDK**.  
  - Login con **Identity Toolkit REST** (`accounts:signInWithPassword`).
- **Base de datos**: **Cloud Firestore** (Admin SDK).
- **Archivos**: **Firebase Storage** (Admin SDK) para comprobantes y adjuntos.
- **Correo**: SMTP (TLS/SSL), plantillas HTML simples.
- **Recordatorios**: script `send_reminders.py` (CLI/Streamlit opcional) + **GitHub Actions** programado.

Diagrama alto nivel (texto):

```
[Streamlit app]
   - auth.py  (login/signup, roles, approval)
   - app.py   (UI principal)
   - calculations.py (calendarios)
   - emailer.py (SMTP + plantillas)
   - firebase_init.py (Admin SDK + bucket)
   - send_reminders.py (worker)

[Firebase]
   - Firestore    (users, agreements, installments, attachments)
   - Storage      (receipts/, agreements/*/attachments)
```

---

## Roles y permisos

**Admin**
- Panel de métricas globales.
- Aprobación/rechazo de usuarios.
- **Configuración global**: activar/desactivar **interés**.
- Eliminación de convenios.
- Diagnóstico.

**Operador**
- Crear convenios con adjuntos.
- Recalcular calendario (en `DRAFT`/`PENDING_ACCEPTANCE`).
- Enviar a aceptación.
- **Aprobar/Rechazar pagos** (con o sin comprobante).
- Panel de métricas personales.

**Cliente**
- Aceptar/Rechazar convenio.
- Subir comprobante **o** declarar pago **sin** comprobante.
- Ver calendario y estado de cuotas.

---

## Modelo de datos

```
users (colección)
  {uid}: {
    email, full_name, role {admin, operador, cliente},
    status {PENDING, APPROVED, REJECTED},
    rejection_note?
  }

agreements (colección)
  {agreementId}: {
    title, notes,
    operator_id (uid),
    client_id? (uid),         // puede no existir si el cliente aún no se registró
    client_email,             // fallback para listar/avisar
    principal (float),
    interest_rate (float mensual; 0.05 = 5%),
    installments (int),
    method {"french","declining"},
    status {DRAFT, PENDING_ACCEPTANCE, ACTIVE, COMPLETED, CANCELLED, REJECTED},
    start_date (YYYY-MM-DD),
    created_at, accepted_at, completed_at
  }

agreements/{agreementId}/installments
  {installmentId}: {
    number (1..n), due_date (YYYY-MM-DD), capital, interest, total,
    paid (bool), paid_at, last_reminder_sent,
    receipt_status {PENDING, APPROVED, REJECTED},
    receipt_url, receipt_note, receipt_uploaded_by, receipt_uploaded_at
  }

agreements/{agreementId}/attachments
  {attachmentId}: { name, path, content_type, size, uploaded_by, uploaded_at }
```

> Se guarda `client_email` como **fallback** para listar convenios aunque el cliente aún no tenga `uid`.

---

## Estados y ciclo de vida

1. **DRAFT**: borrador creado por operador; se puede recalcular calendario y adjuntar documentación.
2. **PENDING_ACCEPTANCE**: enviado al cliente; puede **aceptar** o **rechazar**.
3. **ACTIVE**: aceptado; se gestionan pagos/comprobantes.
4. **COMPLETED**: **automático** cuando **todas** las cuotas están pagadas.
5. **CANCELLED**: cancelado en etapas tempranas.
6. **REJECTED**: rechazo por parte del cliente (guarda `rejection_note`).

Los estados se muestran con color en la UI:  
`PENDING_ACCEPTANCE` = naranja, `REJECTED` = rojo, `ACTIVE/COMPLETED` = verde, `CANCELLED` = gris.

---

## Cálculo de cuotas

Archivo: `calculations.py`.

- **Sistema Francés** (`french`): cuota fija; la **última cuota** ajusta redondeos para igualar principal total.
- **Capital Fijo / Interés sobre saldo** (`declining`): capital constante; **última cuota** ajusta redondeos.

Cada ítem del calendario incluye: `number`, `due_date`, `capital`, `interest`, `total`.  
En la UI se muestra una **fila TOTAL** (sumatoria de capital, interés y total).

---

## Interés (configuración global)

- Página **Configuración** (solo admin): `config/settings.interest_enabled`.
- Si el **interés está deshabilitado**:
  - El campo **Ínterés mensual (%)* **no se muestra**.
  - El **método de cálculo** aparece **deshabilitado** (_grisado_) y fijo en **Sistema francés (cuota fija)**.
  - El `interest_rate` se guarda como **0.0**.

---

## Adjuntos y PDF

**Adjuntos** (operador al crear):
- Tipos permitidos: **PDF/JPG/PNG** (hasta **10 MB** por archivo).
- Se guardan en Storage: `agreements/{id}/attachments/<archivo>` y en la subcolección `attachments`.
- El cliente puede ver/descargar los adjuntos desde el convenio.

**PDF del convenio** (descarga desde la vista del convenio):
- Datos del convenio (cliente, operador, principal, método, interés, inicio).
- **Calendario** completo con **fila TOTAL**.
- **Listado de adjuntos**; si son imágenes, se incrustan como **preview**.

---

## Pagos y comprobantes

**Cliente**
- Puede **subir comprobante** (PDF/JPG/PNG) `receipt_status = PENDING`.
- **O** puede **declarar pago sin comprobante** también `PENDING` (queda a revisión del operador).

**Operador**
- En **Comprobantes**: puede **aprobar** (marca `paid=True`, `APPROVED`) o **rechazar** (guarda `receipt_note`).
- En la vista del convenio: puede **marcar pagada** o **revertir** una cuota **con o sin comprobante**.

**Cierre automático**
- Si **todas** las cuotas están pagadas (`paid=True`), el convenio pasa a `COMPLETED`.

---

## Recordatorios automáticos

Archivo: `send_reminders.py` (worker ejecutable como **script** o desde **Streamlit** para admins).

- Recorre convenios `ACTIVE` y cuotas **impagas**.
- Enviar recordatorios cuando:
  - Están **próximas a vencer** (`REMINDER_DAYS_BEFORE`).
  - **Vencen hoy**.
  - Están **vencidas** (`REMINDER_DAYS_AFTER`).
- Respeta `last_reminder_sent` con `REMINDER_COOLDOWN_DAYS` para evitar spam.
- Notifica al **cliente** (y opcionalmente copia al **operador**).

**Ejecución**
- Local: `python send_reminders.py` (o `streamlit run send_reminders.py` y usar botón si sos admin).
- CRON en **GitHub Actions**: ver workflow `.github/workflows/reminders.yml` (12:00 UTC).

Variables del worker:
- `APP_TZ` (default `America/Argentina/Buenos_Aires`)
- `REMINDER_DAYS_BEFORE`, `REMINDER_DAYS_AFTER`, `REMINDER_COOLDOWN_DAYS`

---

## Estructura del repositorio

```
.
- app.py                 # App principal (Streamlit)
- auth.py                # Registro/login, roles, gestión de usuarios
- calculations.py        # Cálculo de cuotas (francés/declining) con ajuste de redondeos
- emailer.py             # SMTP + plantillas
- firebase_init.py       # Inicialización Admin SDK (credenciales/bucket)
- send_reminders.py      # Worker de recordatorios (CLI/Streamlit opcional)
- requirements.txt       # Dependencias
- .github/
   - workflows/
      - reminders.yml    # CRON diario a las 12:00 UTC
```

---

## Requisitos e instalación local

```bash
# 1) Entorno virtual
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate

# 2) Dependencias
pip install --upgrade pip
pip install -r requirements.txt

# 3) Secrets de Streamlit
# Crear .streamlit/secrets.toml (ver más abajo)

# 4) Ejecutar la app
streamlit run app.py
```

`requirements.txt` mínimo:

```
streamlit
firebase-admin
google-cloud-firestore
requests
pytz
reportlab
pandas
```

> **Nota**: `reportlab` se usa para generar PDFs; `pandas` para formatear tablas con totales.

---

## Configuración (secrets/variables)

### `.streamlit/secrets.toml` (para **app**)

```toml
# Firebase (pegar contenido literal del JSON del service account)
FIREBASE_CREDENTIALS = """{
  "type": "service_account",
  "project_id": "<tu-proyecto>",
  ...
}"""
FIREBASE_PROJECT_ID = "<tu-proyecto>"
# opcional: si querés forzar el bucket
FIREBASE_STORAGE_BUCKET = "<tu-proyecto>.appspot.com"

# Web API Key para login por REST (Identity Toolkit)
FIREBASE_WEB_API_KEY = "<apikey>"

# Base URL de la app (links en emails)
APP_BASE_URL = "https://tu-app.streamlit.app"

# SMTP
SMTP_HOST    = "smtp.tu-dominio.com"
SMTP_PORT    = "587"
SMTP_USER    = "no-reply@tu-dominio.com"
SMTP_PASS    = "********"
SMTP_USE_TLS = "true"
SMTP_SENDER  = "Asistente de Convenios <no-reply@tu-dominio.com>"

# (Opcional) admins a los que se envían avisos
ADMIN_EMAILS = "admin1@dominio.com, admin2@dominio.com"
```

### Variables para el **worker** (local/Actions)

- `FIREBASE_CREDENTIALS` (JSON **en una sola línea**, o ADC).  
- `FIREBASE_PROJECT_ID`.  
- `SMTP_*` y `APP_BASE_URL`.  
- Opcionales: `APP_TZ`, `REMINDER_DAYS_BEFORE`, `REMINDER_DAYS_AFTER`, `REMINDER_COOLDOWN_DAYS`.

---

## Primer uso (seed admin)

1. Ejecutá `streamlit run app.py`.
2. Si no hay usuarios, la app pedirá **crear el Admin** (email + contraseña) y se detendrá.
3. Iniciá sesión como admin.
4. Entrá a **Configuración** y definí si el **interés** está activo o no.
5. Creá **operadores** y aprobá **clientes** registrados.

---

## Despliegue / CI

**GitHub Actions**

- Archivo: `.github/workflows/reminders.yml`.
- Corre el worker `send_reminders.py` diariamente a las **12:00 UTC** (09:00 Buenos Aires) y permite **disparo manual** (`workflow_dispatch`).
- Usa secrets del repo para credenciales (`FIREBASE_CREDENTIALS`, `SMTP_*`, etc.).

**Streamlit Cloud / VM / Contenedor**

- Ejecutar `streamlit run app.py` con las variables/secrets adecuadas.
- `firebase_init.py` soporta **ADC** (Application Default Credentials) cuando no se define `FIREBASE_CREDENTIALS`.

---

## Colores y estados visuales

- **Convenios**: `PENDING_ACCEPTANCE` naranja; `REJECTED` rojo; `ACTIVE/COMPLETED` verde; `CANCELLED` gris.
- **Cuotas**: `PAGADA/APROBADO` ; `PENDIENTE` ; `RECHAZADO` .

---

## Seguridad y buenas prácticas

- Mantener las credenciales de **Service Account** en **secrets** (no commitear).  
- Usar **TLS/SSL** en SMTP y una cuenta específica para la app.  
- Las **URL firmadas** de Storage expiran (15 min aprox.).  
- Los **roles** controlan la UI y acciones; `ensure_admin_seed` garantiza un admin inicial.  
- Rotación periódica de secrets recomendada.  
- Si usás emuladores, definí `FIRESTORE_EMULATOR_HOST`/`STORAGE_EMULATOR_HOST`.

---

## Solución de problemas

- **No conecta a Firestore**: verificá `FIREBASE_CREDENTIALS` y `FIREBASE_PROJECT_ID`.
- **No llegan emails**: revisá `SMTP_*`; chequeá SPF/DKIM/DMARC y carpeta SPAM.
- **Cliente no ve su convenio**: al crear, se usa `client_email` como fallback; confirmá que coincida.
- **Error de widgets duplicados** (`StreamlitDuplicateElementId`): se solucionó asignando `key=` único a cada botón.
- **PDF sin imágenes**: verificá que el adjunto sea `image/*` y que el bucket sea accesible por el Service Account.

---

## FAQ

**驴Puedo dejar de usar interés?**  
Sí. Desactivalo en **Configuración**. La UI oculta el campo y bloquea el método, fijando interés en 0.

**驴El cliente debe subir comprobante?**  
No. Puede **declarar pago sin comprobante**; quedará `PENDING` para revisión del operador.

**驴El operador puede marcar pagada sin comprobante?**  
Sí. Puede marcar pagada o revertir una cuota independientemente del comprobante.

**驴Se puede adjuntar documentación de respaldo?**  
Sí. Al crear el convenio, el operador puede adjuntar **PDF/JPG/PNG** múltiples.

**驴Cómo genero un PDF del convenio?**  
En la vista del convenio sección **Exportar PDF** **Generar PDF** **Descargar PDF**

---

## Roadmap sugerido

- Filtros, orden y paginación en listados grandes.
- Exportar calendario a CSV/Excel.
- Plantillas HTML de email con branding.
- Gráficos de aceptación, mora y recaudación.
- Integración con S3/R2 (guardando URL firmada pública/temporal).
- Reset de contraseña por **link** además del temporal.

---

## Changelog (esta versión)

- **Totales** en tabla de cuotas (suma de capital, interés y total).
- **Adjuntos** en creación de convenio (operador) y visualización para cliente.
- **PDF** con datos del convenio + calendario (con **TOTAL**) + adjuntos (imágenes en preview).
- **Interés administrable** (on/off). Si **off**, el campo de interés **no se muestra** y el **método queda deshabilitado** en Sistema francés
- **Colores**: pendiente (naranja), rechazado (rojo), aceptado/pagado (verde).
- **Pagos sin comprobante**: cliente puede declarar; operador puede aprobar o marcar pagada igualmente.
- Correcciones: claves únicas en widgets (Streamlit) y fixes menores.

---

## Licencia y créditos

- Licencia: **GPL-3.0** (agregar `LICENSE` si no existe).
- Desarrollo: **Germán Berterreix**.
- Colaboración técnica: contribuyentes del repo.

---

## Anexo: Guía rápida para Copilot

> Puntos clave para entender el proyecto en nuevas conversaciones:
>
> - `config/settings.interest_enabled` controla toda la UI: si está **off**, la tasa se oculta y el método queda **deshabilitado** (fijo en Francés).
> - El **cliente** puede subir **comprobante** o **declarar pago sin comprobante** (`PENDING`).
> - El **operador** aprueba/rechaza y puede **marcar pagada** sin comprobante.
> - **Auto-complete**: todas pagadas 鈬?estado `COMPLETED`.
> - **Adjuntos**: subcolección `attachments`; Storage en `agreements/{id}/attachments/`.
> - **PDF**: `reportlab`, incluye calendario con **TOTAL** y preview de imágenes.
> - **Recordatorios**: `send_reminders.py` (CLI/Streamlit), CRON en `.github/workflows/reminders.yml`.
> - Archivos clave: `app.py`, `auth.py`, `calculations.py`, `emailer.py`, `firebase_init.py`, `send_reminders.py`.
