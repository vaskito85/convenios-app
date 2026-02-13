# 馃挸 Asistente de Convenios de Pago

Aplicaci贸n **Streamlit** para gestionar convenios de pago con soporte de:

- **Usuarios y roles** (`admin`, `operador`, `cliente`).
- **Creaci贸n de convenios** con **adjuntos** (documentaci贸n de la deuda) y **c谩lculo de cuotas**.
- **Gesti贸n de pagos y comprobantes** (con y **sin** archivo adjunto).
- **Aprobaci贸n/Rechazo** de pagos por operador.
- **M茅tricas** y tableros (admin/operador).
- **Recordatorios autom谩ticos** de cuotas (worker + GitHub Actions).
- **Exportaci贸n a PDF** con detalle del calendario de cuotas (incluye **totales**) y listado/preview de documentaci贸n adjunta.
- **Par谩metro global de inter茅s** (on/off) administrable; si est谩 **off** el m茅todo de c谩lculo queda **fijo** y **deshabilitado**.

Backend: **Firebase** (Firestore + Storage + Auth).  
Email: **SMTP** configurable.

---

## 馃Л 脥ndice

- [Arquitectura](#arquitectura)
- [Roles y permisos](#roles-y-permisos)
- [Modelo de datos](#modelo-de-datos)
- [Estados y ciclo de vida](#estados-y-ciclo-de-vida)
- [C谩lculo de cuotas](#c谩lculo-de-cuotas)
- [Inter茅s (configuraci贸n global)](#inter茅s-configuraci贸n-global)
- [Adjuntos y PDF](#adjuntos-y-pdf)
- [Pagos y comprobantes](#pagos-y-comprobantes)
- [Recordatorios autom谩ticos](#recordatorios-autom谩ticos)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Requisitos e instalaci贸n local](#requisitos-e-instalaci贸n-local)
- [Configuraci贸n (secrets/variables)](#configuraci贸n-secretsvariables)
- [Primer uso (seed admin)](#primer-uso-seed-admin)
- [Despliegue / CI](#despliegue--ci)
- [Colores y estados visuales](#colores-y-estados-visuales)
- [Seguridad y buenas pr谩cticas](#seguridad-y-buenas-pr谩cticas)
- [Soluci贸n de problemas](#soluci贸n-de-problemas)
- [FAQ](#faq)
- [Roadmap sugerido](#roadmap-sugerido)
- [Changelog (esta versi贸n)](#changelog-esta-versi贸n)
- [Licencia y cr茅ditos](#licencia-y-cr茅ditos)
- [Anexo: Gu铆a r谩pida para Copilot](#anexo-gu铆a-r谩pida-para-copilot)

---

## Arquitectura

- **UI/Servidor**: [Streamlit](https://streamlit.io/).
- **Autenticaci贸n**: Firebase Authentication  
  - Alta/gesti贸n con **Firebase Admin SDK**.  
  - Login con **Identity Toolkit REST** (`accounts:signInWithPassword`).
- **Base de datos**: **Cloud Firestore** (Admin SDK).
- **Archivos**: **Firebase Storage** (Admin SDK) para comprobantes y adjuntos.
- **Correo**: SMTP (TLS/SSL), plantillas HTML simples.
- **Recordatorios**: script `send_reminders.py` (CLI/Streamlit opcional) + **GitHub Actions** programado.

Diagrama alto nivel (texto):

```
[Streamlit app]
   鈹溾攢鈹€ auth.py  (login/signup, roles, approval)
   鈹溾攢鈹€ app.py   (UI principal)
   鈹溾攢鈹€ calculations.py (calendarios)
   鈹溾攢鈹€ emailer.py (SMTP + plantillas)
   鈹溾攢鈹€ firebase_init.py (Admin SDK + bucket)
   鈹斺攢鈹€ send_reminders.py (worker)

[Firebase]
   鈹溾攢鈹€ Firestore    (users, agreements, installments, attachments)
   鈹斺攢鈹€ Storage      (receipts/, agreements/*/attachments)
```

---

## Roles y permisos

**Admin**
- Panel de m茅tricas globales.
- Aprobaci贸n/rechazo de usuarios.
- **Configuraci贸n global**: activar/desactivar **inter茅s**.
- Eliminaci贸n de convenios.
- Diagn贸stico.

**Operador**
- Crear convenios con adjuntos.
- Recalcular calendario (en `DRAFT`/`PENDING_ACCEPTANCE`).
- Enviar a aceptaci贸n.
- **Aprobar/Rechazar pagos** (con o sin comprobante).
- Panel de m茅tricas personales.

**Cliente**
- Aceptar/Rechazar convenio.
- Subir comprobante **o** declarar pago **sin** comprobante.
- Ver calendario y estado de cuotas.

---

## Modelo de datos

```
users (colecci贸n)
  {uid}: {
    email, full_name, role 鈭?{admin, operador, cliente},
    status 鈭?{PENDING, APPROVED, REJECTED},
    rejection_note?
  }

agreements (colecci贸n)
  {agreementId}: {
    title, notes,
    operator_id (uid),
    client_id? (uid),         // puede no existir si el cliente a煤n no se registr贸
    client_email,             // fallback para listar/avisar
    principal (float),
    interest_rate (float mensual; 0.05 = 5%),
    installments (int),
    method 鈭?{"french","declining"},
    status 鈭?{DRAFT, PENDING_ACCEPTANCE, ACTIVE, COMPLETED, CANCELLED, REJECTED},
    start_date (YYYY-MM-DD),
    created_at, accepted_at?, completed_at?
  }

agreements/{agreementId}/installments
  {installmentId}: {
    number (1..n), due_date (YYYY-MM-DD), capital, interest, total,
    paid (bool), paid_at?, last_reminder_sent?,
    receipt_status? 鈭?{PENDING, APPROVED, REJECTED},
    receipt_url?, receipt_note?, receipt_uploaded_by?, receipt_uploaded_at?
  }

agreements/{agreementId}/attachments
  {attachmentId}: { name, path, content_type, size, uploaded_by, uploaded_at }
```

> Se guarda `client_email` como **fallback** para listar convenios aunque el cliente a煤n no tenga `uid`.

---

## Estados y ciclo de vida

1. **DRAFT**: borrador creado por operador; se puede recalcular calendario y adjuntar documentaci贸n.
2. **PENDING_ACCEPTANCE**: enviado al cliente; puede **aceptar** o **rechazar**.
3. **ACTIVE**: aceptado; se gestionan pagos/comprobantes.
4. **COMPLETED**: **autom谩tico** cuando **todas** las cuotas est谩n pagadas.
5. **CANCELLED**: cancelado en etapas tempranas.
6. **REJECTED**: rechazo por parte del cliente (guarda `rejection_note`).

Los estados se muestran con color en la UI:  
`PENDING_ACCEPTANCE` = naranja, `REJECTED` = rojo, `ACTIVE/COMPLETED` = verde, `CANCELLED` = gris.

---

## C谩lculo de cuotas

Archivo: `calculations.py`.

- **Sistema Franc茅s** (`french`): cuota fija; la **煤ltima cuota** ajusta redondeos para igualar principal total.
- **Capital Fijo / Inter茅s sobre saldo** (`declining`): capital constante; **煤ltima cuota** ajusta redondeos.

Cada 铆tem del calendario incluye: `number`, `due_date`, `capital`, `interest`, `total`.  
En la UI se muestra una **fila TOTAL** (sumatoria de capital, inter茅s y total).

---

## Inter茅s (configuraci贸n global)

- P谩gina **Configuraci贸n** (solo admin): `config/settings.interest_enabled`.
- Si el **inter茅s est谩 deshabilitado**:
  - El campo **鈥淚nter茅s mensual (%)鈥?* **no se muestra**.
  - El **m茅todo de c谩lculo** aparece **deshabilitado** (_grisado_) y fijo en **鈥淪istema franc茅s (cuota fija)鈥?*.
  - El `interest_rate` se guarda como **0.0**.

---

## Adjuntos y PDF

**Adjuntos** (operador al crear):
- Tipos permitidos: **PDF/JPG/PNG** (hasta **10 MB** por archivo).
- Se guardan en Storage: `agreements/{id}/attachments/<archivo>` y en la subcolecci贸n `attachments`.
- El cliente puede ver/descargar los adjuntos desde el convenio.

**PDF del convenio** (descarga desde la vista del convenio):
- Datos del convenio (cliente, operador, principal, m茅todo, inter茅s, inicio).
- **Calendario** completo con **fila TOTAL**.
- **Listado de adjuntos**; si son im谩genes, se incrustan como **preview**.

---

## Pagos y comprobantes

**Cliente**
- Puede **subir comprobante** (PDF/JPG/PNG) 鈫?`receipt_status = PENDING`.
- **O** puede **declarar pago sin comprobante** 鈫?tambi茅n `PENDING` (queda a revisi贸n del operador).

**Operador**
- En **Comprobantes**: puede **aprobar** (marca `paid=True`, `APPROVED`) o **rechazar** (guarda `receipt_note`).
- En la vista del convenio: puede **marcar pagada** o **revertir** una cuota **con o sin comprobante**.

**Cierre autom谩tico**
- Si **todas** las cuotas est谩n pagadas (`paid=True`), el convenio pasa a `COMPLETED`.

---

## Recordatorios autom谩ticos

Archivo: `send_reminders.py` (worker ejecutable como **script** o desde **Streamlit** para admins).

- Recorre convenios `ACTIVE` y cuotas **impagas**.
- Enviar recordatorios cuando:
  - Est谩n **pr贸ximas a vencer** (鈮?`REMINDER_DAYS_BEFORE`).
  - **Vencen hoy**.
  - Est谩n **vencidas** (鈮?`REMINDER_DAYS_AFTER`).
- Respeta `last_reminder_sent` con `REMINDER_COOLDOWN_DAYS` para evitar spam.
- Notifica al **cliente** (y opcionalmente copia al **operador**).

**Ejecuci贸n**
- Local: `python send_reminders.py` (o `streamlit run send_reminders.py` y usar bot贸n si sos admin).
- CRON en **GitHub Actions**: ver workflow `.github/workflows/reminders.yml` (12:00 UTC).

Variables del worker:
- `APP_TZ` (default `America/Argentina/Buenos_Aires`)
- `REMINDER_DAYS_BEFORE`, `REMINDER_DAYS_AFTER`, `REMINDER_COOLDOWN_DAYS`

---

## Estructura del repositorio

```
.
鈹溾攢 app.py                 # App principal (Streamlit)
鈹溾攢 auth.py                # Registro/login, roles, gesti贸n de usuarios
鈹溾攢 calculations.py        # C谩lculo de cuotas (franc茅s/declining) con ajuste de redondeos
鈹溾攢 emailer.py             # SMTP + plantillas
鈹溾攢 firebase_init.py       # Inicializaci贸n Admin SDK (credenciales/bucket)
鈹溾攢 send_reminders.py      # Worker de recordatorios (CLI/Streamlit opcional)
鈹溾攢 requirements.txt       # Dependencias
鈹斺攢 .github/
   鈹斺攢 workflows/
      鈹斺攢 reminders.yml    # CRON diario a las 12:00 UTC
```

---

## Requisitos e instalaci贸n local

```bash
# 1) Entorno virtual
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate

# 2) Dependencias
pip install --upgrade pip
pip install -r requirements.txt

# 3) Secrets de Streamlit
# Crear .streamlit/secrets.toml (ver m谩s abajo)

# 4) Ejecutar la app
streamlit run app.py
```

`requirements.txt` m铆nimo:

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

## Configuraci贸n (secrets/variables)

### `.streamlit/secrets.toml` (para **app**)

```toml
# Firebase (pegar contenido literal del JSON del service account)
FIREBASE_CREDENTIALS = """{
  "type": "service_account",
  "project_id": "<tu-proyecto>",
  ...
}"""
FIREBASE_PROJECT_ID = "<tu-proyecto>"
# opcional: si quer茅s forzar el bucket
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

# (Opcional) admins a los que se env铆an avisos
ADMIN_EMAILS = "admin1@dominio.com, admin2@dominio.com"
```

### Variables para el **worker** (local/Actions)

- `FIREBASE_CREDENTIALS` (JSON **en una sola l铆nea**, o ADC).  
- `FIREBASE_PROJECT_ID`.  
- `SMTP_*` y `APP_BASE_URL`.  
- Opcionales: `APP_TZ`, `REMINDER_DAYS_BEFORE`, `REMINDER_DAYS_AFTER`, `REMINDER_COOLDOWN_DAYS`.

---

## Primer uso (seed admin)

1. Ejecut谩 `streamlit run app.py`.
2. Si no hay usuarios, la app pedir谩 **crear el Admin** (email + contrase帽a) y se detendr谩.
3. Inici谩 sesi贸n como admin.
4. Entr谩 a **Configuraci贸n** y defin铆 si el **inter茅s** est谩 activo o no.
5. Cre谩 **operadores** y aprob谩 **clientes** registrados.

---

## Despliegue / CI

**GitHub Actions**

- Archivo: `.github/workflows/reminders.yml`.
- Corre el worker `send_reminders.py` diariamente a las **12:00 UTC** (鈮?09:00 Buenos Aires) y permite **disparo manual** (`workflow_dispatch`).
- Usa secrets del repo para credenciales (`FIREBASE_CREDENTIALS`, `SMTP_*`, etc.).

**Streamlit Cloud / VM / Contenedor**

- Ejecutar `streamlit run app.py` con las variables/secrets adecuadas.
- `firebase_init.py` soporta **ADC** (Application Default Credentials) cuando no se define `FIREBASE_CREDENTIALS`.

---

## Colores y estados visuales

- **Convenios**: `PENDING_ACCEPTANCE` 鈫?naranja; `REJECTED` 鈫?rojo; `ACTIVE/COMPLETED` 鈫?verde; `CANCELLED` 鈫?gris.
- **Cuotas**: `PAGADA/APROBADO` 馃煝; `PENDIENTE` 馃煚; `RECHAZADO` 馃敶.

---

## Seguridad y buenas pr谩cticas

- Mantener las credenciales de **Service Account** en **secrets** (no commitear).  
- Usar **TLS/SSL** en SMTP y una cuenta espec铆fica para la app.  
- Las **URL firmadas** de Storage expiran (15 min aprox.).  
- Los **roles** controlan la UI y acciones; `ensure_admin_seed` garantiza un admin inicial.  
- Rotaci贸n peri贸dica de secrets recomendada.  
- Si us谩s emuladores, defin铆 `FIRESTORE_EMULATOR_HOST`/`STORAGE_EMULATOR_HOST`.

---

## Soluci贸n de problemas

- **No conecta a Firestore**: verific谩 `FIREBASE_CREDENTIALS` y `FIREBASE_PROJECT_ID`.
- **No llegan emails**: revis谩 `SMTP_*`; cheque谩 SPF/DKIM/DMARC y carpeta SPAM.
- **Cliente no ve su convenio**: al crear, se usa `client_email` como fallback; confirm谩 que coincida.
- **Error de widgets duplicados** (`StreamlitDuplicateElementId`): se solucion贸 asignando `key=` 煤nico a cada bot贸n.
- **PDF sin im谩genes**: verific谩 que el adjunto sea `image/*` y que el bucket sea accesible por el Service Account.

---

## FAQ

**驴Puedo dejar de usar inter茅s?**  
S铆. Desactivalo en **Configuraci贸n**. La UI oculta el campo y bloquea el m茅todo, fijando inter茅s en 0.

**驴El cliente debe subir comprobante?**  
No. Puede **declarar pago sin comprobante**; quedar谩 `PENDING` para revisi贸n del operador.

**驴El operador puede marcar pagada sin comprobante?**  
S铆. Puede marcar pagada o revertir una cuota independientemente del comprobante.

**驴Se puede adjuntar documentaci贸n de respaldo?**  
S铆. Al crear el convenio, el operador puede adjuntar **PDF/JPG/PNG** m煤ltiples.

**驴C贸mo genero un PDF del convenio?**  
En la vista del convenio 鈫?secci贸n **Exportar PDF** 鈫?鈥淕enerar PDF鈥?鈫?鈥淒escargar PDF鈥?

---

## Roadmap sugerido

- Filtros, orden y paginaci贸n en listados grandes.
- Exportar calendario a CSV/Excel.
- Plantillas HTML de email con branding.
- Gr谩ficos de aceptaci贸n, mora y recaudaci贸n.
- Integraci贸n con S3/R2 (guardando URL firmada p煤blica/temporal).
- Reset de contrase帽a por **link** adem谩s del temporal.

---

## Changelog (esta versi贸n)

- **Totales** en tabla de cuotas (suma de capital, inter茅s y total).
- **Adjuntos** en creaci贸n de convenio (operador) y visualizaci贸n para cliente.
- **PDF** con datos del convenio + calendario (con **TOTAL**) + adjuntos (im谩genes en preview).
- **Inter茅s administrable** (on/off). Si **off**, el campo de inter茅s **no se muestra** y el **m茅todo queda deshabilitado** en 鈥淪istema franc茅s鈥?
- **Colores**: pendiente (naranja), rechazado (rojo), aceptado/pagado (verde).
- **Pagos sin comprobante**: cliente puede declarar; operador puede aprobar o marcar pagada igualmente.
- Correcciones: claves 煤nicas en widgets (Streamlit) y fixes menores.

---

## Licencia y cr茅ditos

- Licencia: **GPL-3.0** (agregar `LICENSE` si no existe).
- Desarrollo: **Germ谩n Berterreix**.
- Colaboraci贸n t茅cnica: contribuyentes del repo.

---

## Anexo: Gu铆a r谩pida para Copilot

> Puntos clave para entender el proyecto en nuevas conversaciones:
>
> - `config/settings.interest_enabled` controla toda la UI: si est谩 **off**, la tasa se oculta y el m茅todo queda **deshabilitado** (fijo en 鈥渇ranc茅s鈥?.
> - El **cliente** puede subir **comprobante** o **declarar pago sin comprobante** (`PENDING`).
> - El **operador** aprueba/rechaza y puede **marcar pagada** sin comprobante.
> - **Auto-complete**: todas pagadas 鈬?estado `COMPLETED`.
> - **Adjuntos**: subcolecci贸n `attachments`; Storage en `agreements/{id}/attachments/`.
> - **PDF**: `reportlab`, incluye calendario con **TOTAL** y preview de im谩genes.
> - **Recordatorios**: `send_reminders.py` (CLI/Streamlit), CRON en `.github/workflows/reminders.yml`.
> - Archivos clave: `app.py`, `auth.py`, `calculations.py`, `emailer.py`, `firebase_init.py`, `send_reminders.py`.
