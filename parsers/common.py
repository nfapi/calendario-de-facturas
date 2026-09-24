"""Funciones compartidas por los parsers locales."""

import re
import unicodedata
from datetime import datetime
from decimal import Decimal


def normalize_text(value: str) -> str:
    """Normaliza texto para evitar errores de formato en expresiones regulares."""
    if not value:
        return ""
    return unicodedata.normalize("NFKC", value).replace("\r", " ").replace("\n", " ")


def parse_amount(value: str) -> float:
    """Convierte importes argentinos como 46.308,62 a número."""
    amount_raw = value.replace(" ", "")
    if "," in amount_raw:
        amount_raw = amount_raw.replace(".", "").replace(",", ".")
    elif amount_raw.count(".") == 1 and len(amount_raw.rsplit(".", 1)[1]) == 2:
        pass
    else:
        amount_raw = amount_raw.replace(".", "")
    return float(Decimal(amount_raw))


def parse_date(value: str) -> str:
    """Convierte una fecha dd/mm/yyyy al formato persistido por la aplicación."""
    return datetime.strptime(value, "%d/%m/%Y").strftime("%Y-%m-%d")


def first_match(pattern: str, text: str, flags: int = re.IGNORECASE) -> str:
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else ""