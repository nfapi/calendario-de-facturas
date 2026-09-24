"""Selección del parser local según el proveedor."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from .absa import parse_absa_bill
from .edes import parse_edes_bill
from .generic import parse_generic_provider_bill
from .movistar import parse_movistar_bill
from .municipalidad import parse_municipalidad_bill
from .personal import parse_personal_bill


PARSER_BY_PROVIDER = {
    "personal": parse_personal_bill,
    "edes": parse_edes_bill,
    "absa": parse_absa_bill,
    "movistar": parse_movistar_bill,
    "municipalidad": parse_municipalidad_bill,
}


def parse_provider_bills(provider: str, emails_data: list) -> list:
    """Parsea correos del proveedor y devuelve sus facturas detectadas."""
    if not emails_data:
        return []

    parser = PARSER_BY_PROVIDER.get(provider)
    bills = []
    for email_data in emails_data:
        combined_text = "\n".join([
            email_data.get("subject", ""),
            email_data.get("body", ""),
        ])
        parsed = parser(combined_text) if parser else parse_generic_provider_bill(provider, combined_text)
        bills.extend(parsed)
    return bills


def parse_providers_in_parallel(grouped_emails: dict, providers: list | None = None) -> tuple[dict, dict]:
    """Ejecuta todos los parsers y conserva resultados aunque alguno falle."""
    providers_to_process = [
        provider for provider in (providers or grouped_emails)
        if grouped_emails.get(provider)
    ]
    if not providers_to_process:
        return {}, {}

    parsed_bills = {}
    failures = {}
    worker_count = min(len(providers_to_process), 8)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(parse_provider_bills, provider, grouped_emails[provider]): provider
            for provider in providers_to_process
        }
        for future in as_completed(futures):
            provider = futures[future]
            try:
                bills = future.result()
            except Exception as error:
                failures[provider] = f"{type(error).__name__}: {error}"
                continue

            if bills:
                parsed_bills[provider] = bills
            else:
                failures[provider] = "El parser no extrajo ninguna factura."

    return parsed_bills, failures