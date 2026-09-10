import os
import sys
import json
import base64
import hashlib
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
3. Conserva las facturas en 'data/bills.json' sin sobrescribir el histórico.
4. Publica solamente la base JSON; 'index.html' la consume desde el navegador.

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
            # Gmail puede exponer Inbox, archivados y etiquetas como carpetas distintas.
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

        # Un mensaje puede aparecer en varias etiquetas; Message-ID evita procesarlo dos veces.
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
    
    No calcules ni incluyas estados derivados; el frontend los calcula dinámicamente a partir de la fecha.
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
                "extra": {"type": "STRING", "description": "Información adicional relevante"}
            },
              "required": ["id", "service", "date", "amount"]
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
            return [normalize_bill(bill) for bill in data] if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError) as error:
        raise RuntimeError(f"No se pudo leer la base de facturas: {error}") from error

def normalize_bill(bill: dict) -> dict:
    """Elimina estados derivados para que la fecha sea la única fuente de verdad."""
    return {key: value for key, value in bill.items() if key not in {"status", "badge"}}

def bill_identity(bill: dict) -> tuple:
    """Genera una identidad estable aunque Gemini cambie el detalle o el id."""
    return (
        str(bill.get("service", "")).strip().casefold(),
        str(bill.get("location", "")).strip().casefold(),
        str(bill.get("date", "")).strip(),
        str(bill.get("amount", "")).strip(),
    )

def bill_id(bill: dict) -> str:
    """Crea un id determinista para que la misma factura conserve siempre su id."""
    identity = json.dumps(bill_identity(bill), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()

def append_new_bills(existing_bills: list, extracted_bills: list) -> list:
    """Conserva el histórico y agrega solamente facturas inexistentes."""
    merged_bills = []
    known_bills = set()

    for bill in [*existing_bills, *extracted_bills]:
        bill = normalize_bill(bill)
        identity = bill_identity(bill)
        if identity in known_bills:
            continue
        bill["id"] = bill_id(bill)
        merged_bills.append(bill)
        known_bills.add(identity)

    return merged_bills

def save_bill_database(file_path: str, bills_data: list) -> str:
    """Serializa la base de facturas para que el frontend la consuma."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    database_content = json.dumps(
                [normalize_bill(bill) for bill in bills_data],
                ensure_ascii=False,
                indent=2
    ) + "\n"
    with open(file_path, "w", encoding="utf-8") as data_file:
        data_file.write(database_content)
    return database_content

def commit_to_github(repo: str, file_path: str, content: str, token: str):
    """
    Crea o actualiza un archivo del repositorio usando la API REST de GitHub.
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
