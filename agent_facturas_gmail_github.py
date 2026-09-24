import argparse
import os
import re
import sys
import json
import base64
import imaplib
import email
import html
import unicodedata
from decimal import Decimal, InvalidOperation
from email.header import decode_header
import requests
from datetime import datetime, timedelta, timezone
from parsers import (
    parse_absa_bill,
    parse_camuzzi_bill,
    parse_edes_bill,
    parse_generic_provider_bill,
    parse_movistar_bill,
    parse_municipalidad_bill,
    parse_personal_bill,
    parse_provider_bills,
    parse_providers_in_parallel,
)

"""
===============================================================================
AGENTE AUTOMATIZADO: GMAIL -> PARSERS LOCALES -> CALENDARIO HTML -> GITHUB PAGES
===============================================================================

Este script realiza el flujo completo:
1. Conecta a Gmail vía IMAP / App Password para buscar correos recientes con facturas.
2. Agrupa los correos por proveedor (Personal, Camuzzi/Gas, EDES, ABSA, ARCA, etc.).
3. Utiliza parsers deterministas por proveedor para extraer:
   - Nombre del servicio
   - Monto a pagar
   - Fecha de vencimiento (YYYY-MM-DD)
   - Dirección / NIS / Detalles
4. Conserva las facturas en 'data/bills.json' sin sobrescribir el histórico.
5. Publica solamente la base JSON; 'index.html' la consume desde el navegador.

Variables de entorno requeridas:
  - GMAIL_USER: Tu dirección de correo (ej: 'ejemplo@gmail.com')
  - GMAIL_APP_PASSWORD: Contraseña de aplicación de Google (16 caracteres)
  - GITHUB_TOKEN: Personal Access Token (PAT) con permisos de 'repo'
  - GITHUB_REPO: Tu repositorio en formato 'usuario/nombre-repo'
===============================================================================
"""

PROVIDER_PRIORITY = [
    "personal",
    "camuzzi",
    "edes",
    "absa",
    "arca",
    "movistar",
    "brubank",
    "municipalidad",
    "bvnet",
    "general",
]

PROVIDER_KEYWORDS = {
    "personal": [
        "personal.com.ar",
        "email.personal.com.ar",
        "personal",
        "internet",
        "cable",
        "fibra",
    ],
    "camuzzi": [
        "camuzzi",
        "camuzzigas.com.ar",
        "factura.camuzzigas.com.ar",
        "gas",
    ],
    "edes": ["edes", "edes.com.ar", "electricidad"],
    "absa": ["absa", "absa.com.ar"],
    "arca": ["arca", "arca.com.ar"],
    "movistar": ["movistar", "movistar.com.ar"],
    "brubank": ["brubank", "brubank.com"],
    "municipalidad": ["municipalidad", "bahia blanca", "municipio"],
    "bvnet": ["bvnet", "bvnet.com.ar"],
}

PROVIDER_EMAILS = {
    "personal": ["@personal.com.ar", "email.personal.com.ar"],
    "camuzzi": ["@camuzzigas.com.ar", "factura.camuzzigas.com.ar"],
    "edes": ["@edessa.com.ar", "@edes.com.ar", "edes"],
    "absa": ["@absa.com.ar", "absa"],
    "arca": ["@arca.com.ar", "arca"],
    "movistar": ["@movistar.com.ar", "movistar"],
    "brubank": ["@brubank.com", "brubank"],
    "municipalidad": ["municipalidad", "bahia blanca"],
    "bvnet": ["@bvnet.com.ar", "bvnet"],
}

def get_env(var_name: str, required: bool = True) -> str:
    """Obtiene y valida variables de entorno."""
    val = os.getenv(var_name)
    if required and not val:
        print(f"❌ Error de configuración: La variable de entorno '{var_name}' es requerida.")
        sys.exit(1)
    return val or ""

def email_matches_provider(provider: str, from_email: str, subject: str = "", body: str = "") -> bool:
    """Valida si un correo pertenece al remitente exacto o dominio del proveedor."""
    if not provider or provider == "general":
        return True

    haystack = " ".join(part for part in [from_email, subject, body] if part).lower()
    patterns = PROVIDER_EMAILS.get(provider, [])
    if not patterns:
        return True
    return any(pattern.lower() in haystack for pattern in patterns)


def fetch_recent_bill_emails(username: str, app_password: str, max_emails: int = 15, provider: str | None = None) -> list:
    """
    Recorre las carpetas seleccionables de Gmail y recupera correos recientes
    relacionados con facturas y vencimientos.
    """
    print(f"📧 Conectando a Gmail vía IMAP{f' para {provider}' if provider else ''}...")
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

                        subject = msg.get("Subject", "")
                        decoded_subject = ""
                        for frag, enc in decode_header(subject):
                            if isinstance(frag, bytes):
                                decoded_subject += frag.decode(enc or "utf-8", errors="ignore")
                            else:
                                decoded_subject += frag
                        if not decoded_subject:
                            decoded_subject = "Sin asunto"

                        from_header = msg.get("From", "")
                        from_email = ""
                        if from_header:
                            match = re.search(r"<([^>]+@[^>]+)>", from_header)
                            if match:
                                from_email = match.group(1).strip().lower()
                            else:
                                from_email = re.search(r"([^\s<]+@[^\s>]+)", from_header)
                                if from_email:
                                    from_email = from_email.group(1).strip().lower()

                        body = ""
                        body_part = None
                        for part in (msg.walk() if msg.is_multipart() else [msg]):
                            content_type = part.get_content_type()
                            content_disposition = str(part.get("Content-Disposition"))
                            if "attachment" in content_disposition:
                                continue
                            if content_type == "text/plain":
                                body_part = part
                                break
                            if content_type == "text/html" and body_part is None:
                                body_part = part

                        if body_part is not None:
                            payload = body_part.get_payload(decode=True) or b""
                            charset = body_part.get_content_charset() or "utf-8"
                            body = payload.decode(charset, errors="ignore")
                            if body_part.get_content_type() == "text/html" or re.search(r"<[^>]+>", body):
                                body = re.sub(r"<[^>]+>", " ", html.unescape(body))

                        if provider and not email_matches_provider(provider, from_email, decoded_subject, body):
                            continue

                        email_contents.append({
                            "from": from_header,
                            "from_email": from_email,
                            "subject": decoded_subject,
                            "date": msg.get("Date"),
                            "body": (body or "")[:3000],
                        })

        mail.logout()
        print(f"✅ Se procesaron {len(email_contents)} correos de facturas con éxito.")
        return email_contents

    except Exception as e:
        print(f"❌ Error al conectar o leer Gmail: {e}")
        sys.exit(1)


def detect_provider(from_email: str = "", subject: str = "", body: str = "") -> str:
    """Detecta el proveedor según remitente, asunto y contenido del correo."""
    haystack = " ".join(part for part in [from_email, subject, body] if part).lower()
    for provider, keywords in PROVIDER_KEYWORDS.items():
        if any(keyword.lower() in haystack for keyword in keywords):
            return provider
    return "general"


def group_emails_by_provider(emails_data: list) -> dict:
    """Agrupa los correos por proveedor para procesar cada flujo por separado."""
    groups = {provider: [] for provider in PROVIDER_PRIORITY}
    for email_data in emails_data:
        provider = detect_provider(
            email_data.get("from_email", ""),
            email_data.get("subject", ""),
            email_data.get("body", ""),
        )
        groups.setdefault(provider, []).append(email_data)

    return {provider: mails for provider, mails in groups.items() if mails}


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

def normalize_service(service: object) -> str:
    """Agrupa nombres alternativos del mismo proveedor o medio de pago."""
    value = unicodedata.normalize("NFKD", str(service or ""))
    value = "".join(character for character in value if not unicodedata.combining(character))
    value = " ".join(value.casefold().split())
    if "arba" in value:
        return "arba"
    if "edes" in value:
        return "edes"
    if "absa" in value:
        return "absa"
    if "roela" in value or "consorcioabierto" in value or "consorcio abierto" in value:
        return "consorcio"
    if "assertia" in value or "zoho" in value:
        return "assertia"
    return value

def bill_identity(bill: dict) -> tuple:
    """Genera una identidad estable aunque cambien textos y ubicaciones del aviso."""
    try:
        amount = Decimal(str(bill.get("amount", ""))).normalize()
    except (InvalidOperation, ValueError):
        amount = str(bill.get("amount", "")).strip()
    return (
        normalize_service(bill.get("service", "")),
        str(bill.get("date", "")).strip(),
        amount,
    )

def append_new_bills(existing_bills: list, extracted_bills: list) -> list:
    """Conserva el histórico y agrega solamente facturas inexistentes."""
    merged_bills = []
    known_bills = set()

    for bill in [*existing_bills, *extracted_bills]:
        bill = normalize_bill(bill)
        identity = bill_identity(bill)
        if identity in known_bills:
            continue
        bill["id"] = str(len(merged_bills) + 1)
        merged_bills.append(bill)
        known_bills.add(identity)

    return merged_bills


def parse_args() -> argparse.Namespace:
    """Permite ejecutar un proveedor y guardar el resultado como artifact."""
    parser = argparse.ArgumentParser(description="Agente de facturas por proveedor")
    parser.add_argument(
        "--provider",
        choices=[*PROVIDER_PRIORITY],
        help="Procesa solo un proveedor: personal, camuzzi, edes, absa, arca, etc.",
    )
    parser.add_argument(
        "--output",
        help="Guarda las facturas extraídas en un JSON para que otro job las consolide.",
    )
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="No actualiza GitHub; se usa en los jobs paralelos de extracción.",
    )
    return parser.parse_args()


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

def build_sync_metadata() -> str:
    """Genera la marca temporal que la página muestra como última sincronización."""
    return json.dumps(
        {"lastSync": datetime.now(timezone.utc).isoformat()},
        ensure_ascii=False,
        indent=2
    ) + "\n"

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
    if res.status_code not in [200, 404]:
        raise RuntimeError(
            f"Error al consultar el archivo en GitHub ({res.status_code}): {res.text}"
        )
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
        raise RuntimeError(
            f"Error al enviar datos a GitHub ({put_res.status_code}): {put_res.text}"
        )

def main():
    print("🤖 Iniciando Agente de Automatización de Facturas...")
    args = parse_args()

    gmail_user = get_env("GMAIL_USER")
    gmail_pass = get_env("GMAIL_APP_PASSWORD")
    github_token = ""
    github_repo = ""
    if not args.no_publish:
        github_token = get_env("GITHUB_TOKEN")
        github_repo = get_env("GITHUB_REPO")

    provider_filter = args.provider if args.provider else None
    raw_emails = fetch_recent_bill_emails(gmail_user, gmail_pass, provider=provider_filter)

    if not raw_emails:
        print(f"ℹ️ No se encontraron facturas recientes para {provider_filter or 'todos los proveedores'}. Finalizando ejecución.")
        if args.output:
            save_bill_database(args.output, [])
        return

    grouped = group_emails_by_provider(raw_emails)
    providers_to_process = [provider_filter] if provider_filter else list(grouped.keys())

    parsed_by_provider, parser_failures = parse_providers_in_parallel(
        grouped,
        providers=providers_to_process,
    )
    bills_data = [
        bill
        for provider_bills in parsed_by_provider.values()
        for bill in provider_bills
    ]

    for provider, error in sorted(parser_failures.items()):
        print(f"⚠️ Falló el parser de {provider.upper()}: {error}")

    if not bills_data:
        if args.output:
            save_bill_database(args.output, [])
        raise RuntimeError("Los parsers locales no devolvieron datos válidos de facturas.")

    if args.output:
        save_bill_database(args.output, bills_data)
        print(f"✅ Se guardaron {len(bills_data)} facturas en {args.output}.")
        if args.no_publish:
            return

    database_path = os.path.join("data", "bills.json")
    existing_bills = load_bill_database(database_path)
    merged_bills = append_new_bills(existing_bills, bills_data)
    new_bills_count = len(merged_bills) - len(existing_bills)
    database_content = save_bill_database(database_path, merged_bills)
    print(f"✅ Se agregaron {new_bills_count} facturas nuevas; histórico total: {len(merged_bills)}.")

    commit_to_github(
        repo=github_repo,
        file_path=database_path,
        content=database_content,
        token=github_token
    )
    commit_to_github(
        repo=github_repo,
        file_path=os.path.join("data", "sync.json"),
        content=build_sync_metadata(),
        token=github_token
    )

if __name__ == "__main__":
    main()
