import os
import sys
import json
import base64
import imaplib
import email
from email.header import decode_header
import requests
from datetime import datetime, timedelta
from google import genai
from google.genai import types

"""
===============================================================================
AGENTE AUTOMATIZADO: GMAIL -> GEMINI API -> CALENDARIO HTML -> GITHUB PAGES
===============================================================================

Este script realiza el flujo completo:
1. Conecta a Gmail vía IMAP / App Password para buscar correos recientes con facturas.
2. Utiliza Gemini API con Salida Estructurada (JSON Schema) para extraer:
   - Nombre del servicio
   - Monto a pagar
   - Fecha de vencimiento (YYYY-MM-DD)
   - Dirección / NIS / Detalles
3. Regenera dinámicamente un archivo 'index.html' con un calendario interactivo.
4. Hace Commit & Push directo a tu repositorio en GitHub para actualizar el sitio web.

Variables de entorno requeridas:
  - GMAIL_USER: Tu dirección de correo (ej: 'ejemplo@gmail.com')
  - GMAIL_APP_PASSWORD: Contraseña de aplicación de Google (16 caracteres)
  - GEMINI_API_KEY: Clave de Google AI Studio
  - GITHUB_TOKEN: Personal Access Token (PAT) con permisos de 'repo'
  - GITHUB_REPO: Tu repositorio en formato 'usuario/nombre-repo'
===============================================================================
"""

def get_env(var_name: str, required: bool = True) -> str:
    """Obtiene y valida variables de entorno."""
    val = os.getenv(var_name)
    if required and not val:
        print(f"❌ Error de configuración: La variable de entorno '{var_name}' es requerida.")
        sys.exit(1)
    return val or ""

def fetch_recent_bill_emails(username: str, app_password: str, max_emails: int = 15) -> list:
    """
    Recorre las carpetas seleccionables de Gmail y recupera correos recientes
    relacionados con facturas y vencimientos.
    """
    print("📧 Conectando a Gmail vía IMAP...")
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(username, app_password)
        status, mailbox_data = mail.list()
        if status != "OK":
            raise RuntimeError("No se pudieron listar las carpetas de Gmail")

        mailboxes = []
        for mailbox_data_item in mailbox_data or []:
            mailbox_line = mailbox_data_item.decode("utf-8", errors="replace")
            mailbox_name = mailbox_line.rsplit(' "/" ', 1)[-1].strip('"')
            mailbox_name_lower = mailbox_name.casefold()
            mailbox_flags = mailbox_line.split(")", 1)[0].casefold()
            if (
                mailbox_name
                and "\\noselect" not in mailbox_flags
                and "\\sent" not in mailbox_flags
                and "\\drafts" not in mailbox_flags
                and "\\spam" not in mailbox_flags
                and "\\trash" not in mailbox_flags
                and not mailbox_name_lower.endswith(("/spam", "/trash", "/papelera"))
                and mailbox_name_lower not in {"spam", "trash", "papelera"}
            ):
                mailboxes.append(mailbox_name)

        email_contents = []
        seen_message_ids = set()
        since_date = (datetime.now() - timedelta(days=30)).strftime("%d-%b-%Y")

        for mailbox_name in mailboxes:
            status, _ = mail.select(f'"{mailbox_name}"')
            if status != "OK":
                continue

            status, messages = mail.search(None, "SINCE", since_date)
            if status != "OK" or not messages[0]:
                continue

            email_ids = messages[0].split()
            latest_ids = email_ids[-max_emails:]
            print(f"📩 Leyendo hasta {len(latest_ids)} correos de {mailbox_name}...")

            for e_id in reversed(latest_ids):
                _, msg_data = mail.fetch(e_id, "(RFC822)")
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        message_id = msg.get("Message-ID")
                        if message_id and message_id in seen_message_ids:
                            continue
                        if message_id:
                            seen_message_ids.add(message_id)

                        # Decodificar asunto
                        subject, encoding = decode_header(msg["Subject"])[0]
                        if isinstance(subject, bytes):
                            subject = subject.decode(encoding or "utf-8", errors="ignore")

                        # Extraer cuerpo del correo
                        body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                content_type = part.get_content_type()
                                content_disposition = str(part.get("Content-Disposition"))
                                if content_type == "text/plain" and "attachment" not in content_disposition:
                                    body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                    break
                        else:
                            body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

                        email_contents.append({
                            "subject": subject,
                            "date": msg.get("Date"),
                            "body": body[:3000] # Limitar longitud
                        })

        mail.logout()
        print(f"✅ Se procesaron {len(email_contents)} correos de facturas con éxito.")
        return email_contents

    except Exception as e:
        print(f"❌ Error al conectar o leer Gmail: {e}")
        sys.exit(1)

def extract_bills_with_gemini(emails_data: list, api_key: str) -> list:
    """
    Envía los textos de los correos a Gemini utilizando Structured Outputs (JSON Schema)
    para garantizar que la respuesta sea un arreglo estricto de objetos de factura.
    """
    print("🤖 Analizando y extrayendo datos de facturas con Gemini API...")
    
    client = genai.Client(api_key=api_key)

    system_instruction = """
    Eres un asistente contable automatizado. Tu tarea es analizar el texto de los correos electrónicos 
    de facturas y extraer una lista estructurada con todas las facturas vigentes o recientes.
    Asegúrate de formatear la fecha estrictamente como YYYY-MM-DD.
    Asegurate de revisar los correos archivados, pospuestos o en la bandeja de entrada, y extraer todas las facturas que contengan información de vencimiento.
    Los emails de Brubank suelen tener vencimientos de varias empresas, asegúrate de extraer cada factura individualmente y que no sean redundantes, por ejemplo, la factura del gas de Grecia puede venir de un mail de Camuzzi pero tambien en uno de Brubank.
    Presta especial atención a correos de EDES, ABSA, ARCA, Camuzzi, Brubank, Movistar, Personal,
    Municipalidad de Bahía Blanca y BVNET. Identifícalos por el remitente, asunto o contenido,
    aunque no usen literalmente la palabra "factura".
    
    Para el estado: 'pending' si vence en el futuro, 'overdue' si la fecha de vencimiento ya pasó, o 'issued' si es solo una notificación/cuenta corriente.
    """

    prompt = f"Analiza los siguientes correos electrónicos y extrae el listado de facturas:\n\n{json.dumps(emails_data, indent=2)}"

    # Definir el esquema JSON estricto
    schema = {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "id": {"type": "STRING"},
                "service": {"type": "STRING", "description": "Nombre de la empresa o servicio (ej: EDES, ABSA, Camuzzi)"},
                "detail": {"type": "STRING", "description": "Concepto o detalle del servicio"},
                "location": {"type": "STRING", "description": "Dirección, NIS o número de cuenta/unidad"},
                "date": {"type": "STRING", "description": "Fecha de vencimiento en formato YYYY-MM-DD"},
                "amount": {"type": "NUMBER", "description": "Monto total a pagar en ARS u otra moneda local"},
                "status": {"type": "STRING", "enum": ["pending", "overdue", "issued"]},
                "badge": {"type": "STRING", "description": "Etiqueta corta (ej: Próxima, Vencida, Emitida)"},
                "extra": {"type": "STRING", "description": "Información adicional relevante"}
            },
            "required": ["id", "service", "date", "amount", "status"]
        }
    }

    try:
        response = client.models.generate_content(
            model='models/gemini-3.6-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0.1
            )
        )

        extracted_bills = json.loads(response.text)
        print(f"✅ Gemini identificó {len(extracted_bills)} facturas únicas.")
        return extracted_bills

    except Exception as e:
        print(f"❌ Error al procesar datos con Gemini: {e}")
        return []

def load_bill_database(file_path: str) -> list:
    """Lee la base JSON existente sin modificar su histórico."""
    try:
        with open(file_path, "r", encoding="utf-8") as data_file:
            data = json.load(data_file)
            return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError) as error:
      raise RuntimeError(f"No se pudo leer la base de facturas: {error}") from error

def bill_identity(bill: dict) -> tuple:
    """Genera una identidad estable para evitar duplicados entre ejecuciones."""
    return (
        str(bill.get("service", "")).strip().casefold(),
        str(bill.get("detail", "")).strip().casefold(),
        str(bill.get("location", "")).strip().casefold(),
        str(bill.get("date", "")).strip(),
        str(bill.get("amount", "")).strip(),
    )

def append_new_bills(existing_bills: list, extracted_bills: list) -> list:
    """Conserva el histórico y agrega solamente facturas inexistentes."""
    merged_bills = list(existing_bills)
    known_bills = {bill_identity(bill) for bill in merged_bills}

    for bill in extracted_bills:
        identity = bill_identity(bill)
        if identity not in known_bills:
            merged_bills.append(bill)
            known_bills.add(identity)

    return merged_bills

def save_bill_database(file_path: str, bills_data: list) -> str:
    """Serializa la base de facturas para que el frontend la consuma."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    database_content = json.dumps(bills_data, ensure_ascii=False, indent=2) + "\n"
    with open(file_path, "w", encoding="utf-8") as data_file:
        data_file.write(database_content)
    return database_content

def generate_html_calendar(bills_data: list) -> str:
    """
    Genera el código HTML completo con la interfaz del calendario e inyecta
    los datos extraídos directamente en la variable JavaScript 'bills'.
    """
    print("🎨 Generando código HTML actualizado para el panel...")
    
    today_str = datetime.now().strftime("%d de %B, %Y")
    bills_json_str = json.dumps(bills_data, indent=6)

    html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Calendario de Vencimiento de Facturas</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <script src="https://unpkg.com/lucide@latest"></script>
  <style>
    body {{ font-family: 'Inter', sans-serif; }}
  </style>
</head>
<body class="bg-slate-900 text-slate-100 min-h-screen pb-12">

  <!-- Header -->
  <header class="border-b border-slate-800 bg-slate-950/70 backdrop-blur sticky top-0 z-30">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex flex-col sm:flex-row justify-between items-center gap-4">
      <div class="flex items-center gap-3">
        <div class="p-2.5 bg-indigo-600/20 text-indigo-400 rounded-xl border border-indigo-500/30">
          <i data-lucide="calendar" class="w-6 h-6"></i>
        </div>
        <div>
          <h1 class="text-xl font-bold text-white">Calendario de Facturas</h1>
          <p class="text-xs text-slate-400">Actualizado automáticamente desde Gmail por Gemini Agent</p>
        </div>
      </div>
      
      <div class="flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-slate-800 border border-slate-700 text-xs font-medium text-slate-300">
        <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
        Última sincronización: <span class="text-white font-semibold">{today_str}</span>
      </div>
    </div>
  </header>

  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 mt-8 space-y-8">

    <!-- Calendar Container -->
    <div class="bg-slate-800/40 border border-slate-700/80 rounded-2xl overflow-hidden shadow-2xl backdrop-blur-sm">
      <div class="p-5 border-b border-slate-700/80 flex flex-col md:flex-row justify-between items-center gap-4 bg-slate-800/80">
        <div class="flex items-center gap-3">
          <button id="prev-month-btn" class="p-2 hover:bg-slate-700 rounded-xl transition text-slate-300 hover:text-white border border-slate-600/50">
            <i data-lucide="chevron-left" class="w-5 h-5"></i>
          </button>
          <h2 id="current-month-title" class="text-xl font-bold text-white min-w-[200px] text-center sm:text-left"></h2>
          <button id="next-month-btn" class="p-2 hover:bg-slate-700 rounded-xl transition text-slate-300 hover:text-white border border-slate-600/50">
            <i data-lucide="chevron-right" class="w-5 h-5"></i>
          </button>
        </div>

        <div class="flex flex-wrap items-center gap-4 text-xs font-medium">
          <div class="flex items-center gap-1.5"><span class="w-3 h-3 rounded-full bg-amber-500/20 border border-amber-500"></span><span class="text-slate-300">Próximo Vencimiento</span></div>
          <div class="flex items-center gap-1.5"><span class="w-3 h-3 rounded-full bg-rose-500/20 border border-rose-500"></span><span class="text-slate-300">Vencida</span></div>
          <div class="flex items-center gap-1.5"><span class="w-3 h-3 rounded-full bg-blue-500/20 border border-blue-500"></span><span class="text-slate-300">Emitida</span></div>
        </div>
      </div>

      <div class="grid grid-cols-7 text-center bg-slate-900/60 border-b border-slate-700/60 text-xs font-semibold text-slate-400 py-3">
        <div>DOM</div><div>LUN</div><div>MAR</div><div>MIÉ</div><div>JUE</div><div>VIE</div><div>SÁB</div>
      </div>

      <div id="calendar-grid" class="grid grid-cols-7 auto-rows-fr gap-px bg-slate-700/50"></div>
    </div>

    <!-- Table Section -->
    <div class="bg-slate-800/40 border border-slate-700/80 rounded-2xl p-6 shadow-xl space-y-6">
      <h3 class="text-lg font-bold text-white flex items-center gap-2">
        <i data-lucide="list" class="w-5 h-5 text-indigo-400"></i>
        Detalle de Facturas Registradas
      </h3>

      <div class="overflow-x-auto">
        <table class="w-full text-left text-sm text-slate-300">
          <thead class="text-xs uppercase bg-slate-900/80 text-slate-400 border-b border-slate-700">
            <tr>
              <th class="py-3 px-4">Estado</th>
              <th class="py-3 px-4">Servicio</th>
              <th class="py-3 px-4">Dirección / Ref</th>
              <th class="py-3 px-4">Vencimiento</th>
              <th class="py-3 px-4 text-right">Monto</th>
            </tr>
          </thead>
          <tbody id="bills-table-body" class="divide-y divide-slate-700/50"></tbody>
        </table>
      </div>
    </div>
  </main>

  <script>
    // Structured JSON Injected by Agent
    const bills = {bills_json_str};

    let todayDate = new Date();
    let currentYear = todayDate.getFullYear();
    let currentMonth = todayDate.getMonth();

    const monthNames = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];

    function formatCurrency(val) {{
      return new Intl.NumberFormat('es-AR', {{ style: 'currency', currency: 'ARS' }}).format(val);
    }}

    function renderCalendar() {{
      const grid = document.getElementById('calendar-grid');
      const title = document.getElementById('current-month-title');
      grid.innerHTML = '';
      title.textContent = `${{monthNames[currentMonth]}} ${{currentYear}}`;

      const firstDay = new Date(currentYear, currentMonth, 1).getDay();
      const daysInMonth = new Date(currentYear, currentMonth + 1, 0).getDate();
      const prevMonthDays = new Date(currentYear, currentMonth, 0).getDate();

      for (let i = firstDay - 1; i >= 0; i--) {{
        const cell = document.createElement('div');
        cell.className = 'bg-slate-900/40 p-2 min-h-[100px] text-slate-600 select-none';
        cell.innerHTML = `<span class="text-xs font-semibold">${{prevMonthDays - i}}</span>`;
        grid.appendChild(cell);
      }}

      for (let day = 1; day <= daysInMonth; day++) {{
        const monthFormatted = String(currentMonth + 1).padStart(2, '0');
        const dayFormatted = String(day).padStart(2, '0');
        const dateStr = `${{currentYear}}-${{monthFormatted}}-${{dayFormatted}}`;
        const dayBills = bills.filter(b => b.date === dateStr);

        const cell = document.createElement('div');
        cell.className = 'p-2 min-h-[100px] flex flex-col justify-start bg-slate-800/90 border-t border-slate-800';

        let billItemsHtml = '';
        dayBills.forEach(bill => {{
          let badgeClass = 'bg-slate-700 text-slate-300';
          if (bill.status === 'pending') badgeClass = 'bg-amber-500/20 text-amber-300 border border-amber-500/40';
          if (bill.status === 'overdue') badgeClass = 'bg-rose-500/20 text-rose-300 border border-rose-500/40';
          if (bill.status === 'issued') badgeClass = 'bg-blue-500/20 text-blue-300 border border-blue-500/40';

          billItemsHtml += `
            <div class="p-1.5 mb-1 rounded-lg text-[11px] leading-tight ${{badgeClass}} shadow-sm">
              <div class="font-bold truncate">${{bill.service}}</div>
              <div class="text-[10px] opacity-90">${{formatCurrency(bill.amount)}}</div>
            </div>
          `;
        }});

        cell.innerHTML = `
          <div class="flex justify-between items-center mb-1">
            <span class="text-xs font-bold text-slate-300">${{day}}</span>
          </div>
          <div class="space-y-1 overflow-y-auto max-h-[75px]">${{billItemsHtml}}</div>
        `;
        grid.appendChild(cell);
      }}

      lucide.createIcons();
    }}

    function renderTable() {{
      const tbody = document.getElementById('bills-table-body');
      tbody.innerHTML = '';
      bills.sort((a, b) => new Date(a.date) - new Date(b.date));

      bills.forEach(bill => {{
        const row = document.createElement('tr');
        row.className = 'hover:bg-slate-800/50 transition';

        let statusBadge = bill.status === 'pending' 
          ? `<span class="px-2 py-0.5 text-xs font-medium bg-amber-500/20 text-amber-400 border border-amber-500/30 rounded-full">Próxima</span>`
          : (bill.status === 'overdue' 
              ? `<span class="px-2 py-0.5 text-xs font-medium bg-rose-500/20 text-rose-400 border border-rose-500/30 rounded-full">Vencida</span>`
              : `<span class="px-2 py-0.5 text-xs font-medium bg-blue-500/20 text-blue-400 border border-blue-500/30 rounded-full">Emitida</span>`);

        row.innerHTML = `
          <td class="py-3 px-4">${{statusBadge}}</td>
          <td class="py-3 px-4 font-semibold text-white">${{bill.service}}</td>
          <td class="py-3 px-4 text-xs text-slate-400">${{bill.location || '-'}}</td>
          <td class="py-3 px-4 font-mono text-xs">${{bill.date}}</td>
          <td class="py-3 px-4 text-right font-bold text-white">${{formatCurrency(bill.amount)}}</td>
        `;
        tbody.appendChild(row);
      }});
    }}

    document.getElementById('prev-month-btn').addEventListener('click', () => {{
      currentMonth--; if (currentMonth < 0) {{ currentMonth = 11; currentYear--; }} renderCalendar();
    }});

    document.getElementById('next-month-btn').addEventListener('click', () => {{
      currentMonth++; if (currentMonth > 11) {{ currentMonth = 0; currentYear++; }} renderCalendar();
    }});

    document.addEventListener('DOMContentLoaded', () => {{
      renderCalendar();
      renderTable();
      lucide.createIcons();
    }});
  </script>
</body>
</html>
"""
    return html_content

def commit_to_github(repo: str, file_path: str, content: str, token: str):
    """
    Suba o actualiza 'index.html' en la rama principal de GitHub usando la API REST.
    """
    print(f"🚀 Enviando actualización a GitHub ({repo}/{file_path})...")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    url = f"https://api.github.com/repos/{repo}/contents/{file_path}"

    # Check if file exists to get SHA
    res = requests.get(url, headers=headers)
    sha = res.json().get("sha") if res.status_code == 200 else None

    encoded_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')
    payload = {
        "message": f"feat(agent): actualización automática de facturas - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "content": encoded_content
    }
    if sha:
        payload["sha"] = sha

    put_res = requests.put(url, headers=headers, json=payload)
    if put_res.status_code in [200, 201]:
        print("🎉 ¡Sincronización con GitHub finalizada con éxito!")
        print("🌐 GitHub Pages desplegará los cambios automáticamente en instantes.")
    else:
        print(f"❌ Error al enviar datos a GitHub ({put_res.status_code}): {put_res.text}")

def main():
    print("🤖 Iniciando Agente de Automatización de Facturas...")
    
    # 1. Validar variables de entorno
    gmail_user = get_env("GMAIL_USER")
    gmail_pass = get_env("GMAIL_APP_PASSWORD")
    gemini_key = get_env("GEMINI_API_KEY")
    github_token = get_env("GITHUB_TOKEN")
    github_repo = get_env("GITHUB_REPO")

    # 2. Leer correos de Gmail
    raw_emails = fetch_recent_bill_emails(gmail_user, gmail_pass)

    if not raw_emails:
        print("ℹ️ No se encontraron facturas recientes. Finalizando ejecución.")
        return

    # 3. Analizar y estructurar datos con Gemini
    bills_data = extract_bills_with_gemini(raw_emails, gemini_key)

    if not bills_data:
        print("⚠️ No se pudieron extraer datos válidos de facturas.")
        return

    # 4. Conservar el histórico y agregar solamente facturas nuevas
    database_path = os.path.join("data", "bills.json")
    existing_bills = load_bill_database(database_path)
    merged_bills = append_new_bills(existing_bills, bills_data)
    new_bills_count = len(merged_bills) - len(existing_bills)
    database_content = save_bill_database(database_path, merged_bills)
    print(f"✅ Se agregaron {new_bills_count} facturas nuevas; histórico total: {len(merged_bills)}.")

    # 5. Publicar solamente la base de datos; index.html la lee desde el navegador
    commit_to_github(
        repo=github_repo,
        file_path=database_path,
        content=database_content,
        token=github_token
    )

if __name__ == "__main__":
    main()
