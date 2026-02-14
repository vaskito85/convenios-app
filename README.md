#  Asistente de Convenios de Pago

**Asistente de Convenios de Pago** es una aplicación web construida con **Python + Streamlit** y un backend serverless sobre **Firebase (Firestore, Storage y Authentication)**. Permite crear y administrar convenios de pago, adjuntar documentación, calcular cuotas bajo distintos métodos, gestionar comprobantes, emitir PDFs y enviar recordatorios automáticos.

> Este README está pensado como documentación **completa** (200+ líneas) para que cualquier colaborador, agente o futuro mantenedor comprenda el sistema sin necesidad de leer primero el código.

---

## ­ Tabla de Contenidos
1. [Descripción General](#-descripción-general)
2. [Arquitectura del Sistema](#-arquitectura-del-sistema)
3. [Tecnologías Utilizadas](#-tecnologías-utilizadas)
4. [Flujo General de la Aplicación](#-flujo-general-de-la-aplicación)
5. [Roles y Permisos](#-roles-y-permisos)
6. [Modelo de Datos (Firestore)](#-modelo-de-datos-firestore)
7. [Estados del Convenio](#-estados-del-convenio)
8. [Cálculo de Cuotas](#-cálculo-de-cuotas)
9. [Gestión de Adjuntos](#-gestión-de-adjuntos)
10. [Comprobantes y Pagos](#-comprobantes-y-pagos)
11. [Generación de PDFs](#-generación-de-pdfs)
12. [Recordatorios Automáticos (Worker)](#-recordatorios-automáticos-worker)
13. [Estructura del Proyecto](#-estructura-del-proyecto)
14. [Instalación y Ejecución](#-instalación-y-ejecución)
15. [Configuración `.streamlit/secrets.toml` y Variables](#-configuración-streamlitsecretstoml-y-variables)
16. [Guía para Desarrolladores](#-guía-para-desarrolladores)
17. [Resolución de Problemas](#-resolución-de-problemas)
18. [Roadmap](#-roadmap)
19. [Licencia y Créditos](#-licencia-y-créditos)

---

##  Descripción General

La aplicación permite que **operadores** creen convenios de pago para **clientes**, configurando monto principal, cantidad de cuotas, tasa de interés (si está habilitada globalmente) y método de cálculo (Sistema Francés o Capital Fijo / interés sobre saldo). El sistema genera el **calendario** completo, permite **adjuntar documentación** de respaldo, manejar **comprobantes** (con o sin archivo), **aprobar/rechazar pagos**, y **cerrar automáticamente** el convenio cuando todas las cuotas están pagadas.

Incluye **paneles** por rol, **exportación a PDF** con totales y documentos incrustados (si son imágenes), y **recordatorios automáticos** de cuotas (antes, el día y después del vencimiento) mediante un **worker** ejecutable localmente o por **GitHub Actions**.

---

##  Arquitectura del Sistema

```
[Streamlit App]
 - Autenticación (REST Identity Toolkit + Firebase Admin)
 - UI (páginas en /pages)
 - NÃºcleo (/core): Firebase, auth, email, cálculo
 - Servicios (/services): lógica de negocio y utilidades
 - Exportación PDF (ReportLab)
 - Worker de recordatorios (/worker)

[Firebase]
 - Firestore: users, agreements, installments, attachments
 - Storage: adjuntos y comprobantes
 - Authentication: identidad y gestión de cuentas
```

La app es **stateless** y delega la persistencia y archivos a Firebase. Las URL de Storage se firman por tiempo limitado para descarga segura.

---

##  Tecnologías Utilizadas

- **Python 3.x**
- **Streamlit** (frontend + servidor)
- **Firebase Admin SDK** (Auth, Firestore, Storage)
- **Identity Toolkit REST** para login con email/clave
- **Firestore** (base de datos documental)
- **Firebase Storage** (archivos adjuntos y comprobantes)
- **SMTP** (notificaciones por correo)
- **ReportLab** (generación de PDF)
- **pytz** (zonas horarias en worker)

---

##  Flujo General de la Aplicación

1. **Inicio**: operador/admin inicia sesión.
2. **Creación de convenio**: se define cliente, título, notas, principal, tasa (si aplica), método y cuotas.
3. **Adjuntos**: se suben archivos (PDF/JPG/PNG) de respaldo.
4. **Calendario**: el servicio calcula y escribe la subcolección de cuotas.
5. **Envío**: se notifica a cliente (si no está registrado, puede hacerlo luego). Estado pasa a `PENDING_ACCEPTANCE` cuando corresponda.
6. **Aceptación**: cliente acepta convenio `ACTIVE`; o rechaza `REJECTED`.
7. **Pagos**: cliente sube comprobante o declara pago sin archivo; operador aprueba/rechaza o marca pagada manual.
8. **Cierre**: si todas las cuotas están pagadas â†?estado `COMPLETED` automáticamente.
9. **Recordatorios**: worker envía emails en fechas clave.

---

##  Roles y Permisos

**Administrador**
- Panel de métricas globales.
- Alta/gestión de usuarios, aprobación/rechazo.
- Configuración global de **interés on/off**.
- Eliminación de convenios.
- Reset de contraseÃ±as.

**Operador**
- Crea convenios con adjuntos.
- Recalcula calendario en `DRAFT` / `PENDING_ACCEPTANCE`.
- Aprueba/Rechaza comprobantes.
- Marca cuotas como pagadas.
- Panel de métricas personales.

**Cliente**
- Acepta/Rechaza convenio.
- Sube comprobantes o declara pagos sin comprobante.
- Visualiza calendario y estado de cuotas.

**Estados de usuarios**: `PENDING`, `APPROVED`, `REJECTED`.

---

## ?Modelo de Datos (Firestore)

### `users`
```json
{
  "uid": "...",
  "email": "user@dominio.com",
  "full_name": "Nombre Apellido",
  "role": "admin|operador|cliente",
  "status": "PENDING|APPROVED|REJECTED",
  "rejection_note": "?"
}
```

### `agreements`
```json
{
  "title": "Convenio de pago",
  "notes": "Origen de la deuda...",
  "operator_id": "uid_operador",
  "client_id": "uid_cliente?",
  "client_email": "cliente@dom.com",
  "principal": 100000.0,
  "interest_rate": 0.05,  // mensual; 0.0 si interés deshabilitado globalmente
  "installments": 12,
  "method": "french|declining",
  "status": "DRAFT|PENDING_ACCEPTANCE|ACTIVE|COMPLETED|CANCELLED|REJECTED",
  "created_at": "timestamp",
  "accepted_at": "timestamp?",
  "completed_at": "timestamp?",
  "start_date": "YYYY-MM-DD"
}
```

#### Subcolección `agreements/{id}/installments`
```json
{
  "number": 1,
  "due_date": "YYYY-MM-DD",
  "capital": 8000.0,
  "interest": 1200.0,
  "total": 9200.0,
  "paid": false,
  "paid_at": null,
  "receipt_status": "PENDING|APPROVED|REJECTED|null",
  "receipt_url": "agreements/.../receipts/....pdf",
  "receipt_note": "opcional",
  "last_reminder_sent": "timestamp|null"
}
```

#### Subcolección `agreements/{id}/attachments`
```json
{
  "name": "documento.pdf",
  "path": "agreements/{id}/attachments/documento.pdf",
  "content_type": "application/pdf",
  "size": 123456,
  "uploaded_by": "uid",
  "uploaded_at": "timestamp"
}
```

---

##  Estados del Convenio

| Estado                | Descripción                                                      |
|-----------------------|------------------------------------------------------------------|
| `DRAFT`               | Borrador editable por el operador.                              |
| `PENDING_ACCEPTANCE`  | Enviado al cliente; pendiente de aceptación/rechazo.            |
| `ACTIVE`              | Aceptado; habilita gestión de pagos/comprobantes.               |
| `COMPLETED`           | Todas las cuotas pagadas; cierre automático.                    |
| `CANCELLED`           | Cancelado en etapas tempranas.                                  |
| `REJECTED`            | Rechazado por el cliente (con nota opcional).                   |

> La UI diferencia estos estados con colores; los pagos aprobados también se destacan visualmente.

---

##  Cálculo de Cuotas

Implementado en `/core/calc.py` y consumido por `services/installments.py`.

**Sistema Francés (`french`)**
- Cuota fija calculada por fórmula; interés decreciente, capital creciente.
- La **Ãºltima cuota** ajusta redondeos para igualar el principal.

**Capital Fijo / Interés sobre saldo (`declining`)**
- Capital constante en cada cuota; interés sobre saldo remanente.
- La **Ãºltima cuota** ajusta redondeos.

Cuando **interés global** está **deshabilitado**, la UI oculta el campo de tasa y el método queda **fijo en Francés** con tasa 0.0.

---

##  Gestión de Adjuntos

- Tipos permitidos: **PDF/JPG/PNG**.
- TamaÃ±o máximo: **10 MB** por archivo.
- Se almacenan en **Firebase Storage** bajo `agreements/{id}/attachments/{archivo}`.
- Se indexan en Firestore (subcolección `attachments`) para listado y exportación.
- Si el adjunto es **imagen**, se **incrusta** como **preview** en el PDF.

---

##  Comprobantes y Pagos

**Cliente**
- Puede **subir comprobante** (archivo) `receipt_status = PENDING`.
- O **declarar pago sin comprobante** también `PENDING`.

**Operador**
- Puede **aprobar** (marca `paid=true`, `APPROVED`) o **rechazar** (guarda `receipt_note`).
- Puede **marcar pagada** o **revertir** una cuota con o sin comprobante.

**Cierre automático**
- Si **todas** las cuotas están `paid=true`, el convenio pasa a `COMPLETED`.

---

##  Generación de PDFs

- Implementado en `services/pdf_export.py` usando **ReportLab**.
- Contenido:
  - Datos del convenio (cliente, operador, principal, método, interés, inicio)
  - **Calendario** de cuotas completo con **fila TOTAL** (cap., int., total)
  - **Listado de adjuntos**; si son imágenes â†?**preview** incrustado

---

## Recordatorios Automáticos (Worker)

- Script: `worker/send_reminders.py`.
- Recorre convenios `ACTIVE` y cuotas **impagas** (`paid=false`).
- Envía recordatorios cuando:
  - Están **próximas** a vencer (`REMINDER_DAYS_BEFORE`).
  - **Vencen hoy**.
  - Están **vencidas** (`REMINDER_DAYS_AFTER`).
- Respeta `last_reminder_sent` y `REMINDER_COOLDOWN_DAYS` para evitar spam.
- Se puede ejecutar **local** (`python worker/send_reminders.py`) o por **GitHub Actions** (CRON diario).
- Variables clave:
  - `APP_TZ` (default `America/Argentina/Buenos_Aires`)
  - `REMINDER_DAYS_BEFORE`, `REMINDER_DAYS_AFTER`, `REMINDER_COOLDOWN_DAYS`

---

##  Estructura del Proyecto

```text
.
- app.py                   # App principal (Streamlit)
- requirements.txt         # Dependencias
- README.md                # Este archivo
- core/
  - auth.py              # Login/Signup (REST + Admin), seed de admin, gestión usuarios
  - calc.py              # Cálculo de cuotas (francés/declining) con ajuste final
  - firebase.py          # Inicialización Admin SDK + bucket
  - mail.py              # SMTP + armado de mensajes + adjuntos
- pages/
  - common.py            # Header, logout y cambio de contraseÃ±a
  - dashboard_admin.py   # Panel global (admin)
  - dashboard_operator.py# Panel de operador
  - agreements_create.py # Creación de convenio + adjuntos
  - agreements_list.py   # (Listado/gestión; puede compartir lógica con create)
  - receipts_review.py   # Revisión de comprobantes (operador)
  - settings.py          # Configuración global (interés on/off)
- services/
  - agreements.py        # CRUD de convenios + borrado profundo + listados por rol
  - config.py            # Lectura/escritura de settings
  - installments.py      # Generación de calendario; marcar pagada/revertir; autocompletado
  - notifications.py     # Email a operador/cliente/admins ante eventos
  - pdf_export.py        # Construcción del PDF (calendario + adjuntos)
  - storage.py           # Upload/delete + URLs firmadas
- worker/
  - send_reminders.py    # Recordatorios automáticos
```

---

## Instalación y Ejecución

```bash
# 1) Crear entorno virtual
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 2) Instalar dependencias
pip install --upgrade pip
pip install -r requirements.txt

# 3) Configurar secretos de Streamlit
# Crear .streamlit/secrets.toml (ver sección de configuración)

# 4) Ejecutar la app
streamlit run app.py
```

**requirements.txt (mínimo)**
```
streamlit
firebase-admin
google-cloud-firestore
requests
pytz
reportlab
pandas
```

---

##  Configuración `.streamlit/secrets.toml` y Variables

```toml
# Firebase (pegar contenido literal del JSON del Service Account)
FIREBASE_CREDENTIALS = """{
  "type": "service_account",
  "project_id": "<tu-proyecto>",
  ...
}"""
FIREBASE_PROJECT_ID = "<tu-proyecto>"
# (Opcional) forzar bucket
FIREBASE_STORAGE_BUCKET = "<tu-proyecto>.appspot.com"

# Web API Key para login por REST (Identity Toolkit)
FIREBASE_WEB_API_KEY = "<apikey>"

# Base URL de la app (links en emails)
APP_BASE_URL = "https://tu-app.streamlit.app"

# SMTP
SMTP_HOST = "smtp.tu-dominio.com"
SMTP_PORT = "587"
SMTP_USER = "no-reply@tu-dominio.com"
SMTP_PASS = "********"
SMTP_USE_TLS = "true"
SMTP_SENDER = "Asistente de Convenios <no-reply@tu-dominio.com>"

# (Opcional) admins que reciben avisos
ADMIN_EMAILS = "admin1@dominio.com, admin2@dominio.com"

# Worker (si se ejecuta fuera de Streamlit)
APP_TZ = "America/Argentina/Buenos_Aires"
REMINDER_DAYS_BEFORE = "3"
REMINDER_DAYS_AFTER  = "3"
REMINDER_COOLDOWN_DAYS = "3"
```

---

## Guía para Desarrolladores

### Primer uso (seed admin)
1. `streamlit run app.py`.
2. Si no hay usuarios, la app pedirá **crear el Admin inicial** (email + contraseÃ±a). 
3. Iniciar sesión como admin y configurar **interés on/off** en `pages/settings.py` (vía `services/config.py`).

### Convenciones
- **Servicios** no deben importar componentes de UI.
- **Páginas** usan servicios y `core`.
- Las **URL firmadas** de Storage expiran (~15 min); generar bajo demanda.
- Evitar exponerse a timeouts de red largos en la UI (manejo defensivo de requests y firestore).

### Recalcular calendario
- Al cambiar parámetros clave (principal, tasa, método, cuotas, inicio), invocar `services/installments.generate_schedule`.
- Se borra y reescribe la subcolección `installments` de forma transaccional (batch).

### Eliminación de convenios
- Usar `services/agreements.delete_agreement` para borrar **cuotas + recibos + adjuntos**.

### Notificaciones por email
- Centralizadas en `core/mail.py` + `services/notifications.py`.
- Utilizan SMTP autenticado; se recomienda **cuenta dedicada**.

---

##  Resolución de Problemas

- **No conecta a Firestore**: verificar `FIREBASE_CREDENTIALS` y `FIREBASE_PROJECT_ID`.
- **No llegan emails**: revisar `SMTP_*`; chequear SPF/DKIM/DMARC y carpeta SPAM.
- **Cliente no ve su convenio**: al crear se usa `client_email` como fallback; validar coincidencia exacta.
- **URLs de Storage expiran**: las firmas tienen tiempo limitado; regenerar al mostrar.
- **Error de widgets duplicados (Streamlit)**: usar `key=` Ãºnico por widget dinámico.
- **PDF sin imágenes**: confirmar `content_type` y permisos del bucket.

---

## Roadmap

- Filtros, orden y paginación en listados grandes.
- Exportar calendario a CSV/Excel.
- Gráficos de aceptación, mora y recaudación.
- Plantillas HTML de email con branding.
- Reset de contraseÃ±a vía **link** (además de temporal).
- Integración opcional con S3/R2 (URLs firmadas pÃºblicas/temporales).
- Internacionalización (i18n) de la UI.

---

##  Licencia y Créditos

- **Licencia**: GPL-3.0 (sugerida; podés cambiar a MIT si preferís más permisiva).
- **Autor**: Germán Berterreix.
- **Colaboradores**: Bienvenidos PRs y Issues.

---

##  Anexo Rápido para Nuevos Colaboradores

- El switch global `interest_enabled` (en `config/settings`) controla la UI: si está **off**, la tasa **no se muestra** y el método de cálculo queda **fijo** en Francés con tasa 0.0.
- El **cliente** puede subir **comprobante** o **declarar pago sin comprobante** (`PENDING`).
- El **operador** aprueba/rechaza y puede **marcar pagada** sin comprobante.
- **Auto-complete**: si **todas** las cuotas están pagadas â†?`COMPLETED`.
- **Adjuntos**: subcolección `attachments`; Storage `agreements/{id}/attachments/*`.
- **PDF**: incluye calendario con **TOTAL** + preview de imágenes.
- **Recordatorios**: `worker/send_reminders.py` (CRON diario opcional por Actions).

