# Calendario de facturas

Agente que lee correos de Gmail, extrae facturas con Gemini y mantiene un calendario publicado en GitHub Pages.

## Arquitectura

- `agent_facturas_gmail_github.py`: integración Gmail + Gemini y actualización de datos.
- `data/bills.json`: base de datos JSON versionada con el histórico de facturas.
- `data/sync.json`: fecha y hora UTC de la última sincronización completada correctamente.
- `index.html`: calendario estático que carga `data/bills.json` desde el navegador.
- `.github/workflows/facturas-agent.yml`: ejecución automática diaria y ejecución manual.

El agente no genera ni modifica el HTML. Busca correos de los últimos 30 días en las carpetas seleccionables de Gmail, incluyendo Inbox, archivados y etiquetas. Excluye Spam, Papelera, Enviados y Borradores. Los mensajes repetidos por distintas etiquetas se procesan una sola vez.

## Datos y estados

`data/bills.json` conserva únicamente datos persistentes de cada factura, por ejemplo:

```json
{
  "id": "identificador",
  "service": "EDES",
  "detail": "Factura de servicio eléctrico",
  "location": "Bahía Blanca",
  "date": "2026-09-17",
  "amount": 152294.76,
  "extra": "Información adicional"
}
```

El agente agrega facturas nuevas y conserva el histórico. La identidad se determina por servicio normalizado, fecha de vencimiento y monto; el detalle, la ubicación y el `id` recibido desde Gemini no se usan porque pueden variar entre correos. Los `id` se asignan como números consecutivos al guardar la lista.

El estado no se guarda en JSON: `index.html` lo calcula según la fecha actual. Las facturas futuras o de hoy aparecen como próximas y las anteriores como vencidas. El día actual se resalta en el calendario.

## Configuración local

Requisitos:

- Python 3.10 o superior.
- Una cuenta Gmail con IMAP habilitado y una contraseña de aplicación.
- Una clave de Gemini API.
- Un token de GitHub con permiso para escribir contenidos del repositorio.

Instala las dependencias:

```powershell
pip install google-genai requests
```

Define estas variables de entorno:

```text
GMAIL_USER=tu-correo@gmail.com
GMAIL_APP_PASSWORD=contraseña-de-aplicación
GEMINI_API_KEY=clave-de-gemini
GITHUB_TOKEN=token-de-github
GITHUB_REPO=usuario/nombre-repositorio
```

Ejecuta el agente desde la raíz del repositorio:

```powershell
python agent_facturas_gmail_github.py
```

El agente actualiza localmente `data/bills.json` y luego crea o actualiza ese archivo mediante la API de GitHub.

## GitHub Actions

El workflow se ejecuta todos los días y también puede iniciarse manualmente desde GitHub Actions. Configura estos secretos en el repositorio:

- `GMAIL_USER`
- `GMAIL_APP_PASSWORD`
- `GEMINI_API_KEY`
- `PAT_GITHUB_TOKEN`

El workflow deriva `GITHUB_REPO` de `${{ github.repository }}` y usa `actions/checkout@v5` y `actions/setup-python@v6`.

## Proveedores considerados

El análisis presta especial atención a EDES, ABSA, ARCA, Camuzzi, Brubank, Movistar, Personal, Municipalidad de Bahía Blanca y BVNET. También puede extraer otros servicios cuando el correo contiene datos de vencimiento.

## Publicación

GitHub Pages sirve `index.html`. Para que el navegador pueda cargar el JSON, `data/bills.json` debe estar publicado en la misma raíz del sitio. No abras `index.html` con `file://`; usa GitHub Pages o un servidor HTTP local, por ejemplo:

```powershell
python -m http.server 8000
```

Luego abre `http://localhost:8000`.
