import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import patch

from agent_facturas_gmail_github import (
    detect_provider,
    email_matches_provider,
    extract_email_body,
    group_emails_by_provider,
    parse_absa_bill,
    parse_arba_bill,
    parse_brubank_bill,
    parse_camuzzi_bill,
    parse_edes_bill,
    parse_movistar_bill,
    parse_municipalidad_bill,
    parse_mercadopago_bill,
    parse_personal_bill,
    parse_providers_in_parallel,
)
from parsers import dispatcher as parser_dispatcher


class ProviderRoutingTests(unittest.TestCase):
    def test_personal_sender_is_routed_to_personal(self):
        provider = detect_provider(
            "facturacion@email.personal.com.ar",
            "Factura de internet",
            "Vence el 15/10 y corresponde a cable/internet.",
        )
        self.assertEqual(provider, "personal")

    def test_camuzzi_sender_is_routed_to_camuzzi(self):
        provider = detect_provider(
            "factura@factura.camuzzigas.com.ar",
            "Factura de gas",
            "Vence el 10/12. Servicio de gas.",
        )
        self.assertEqual(provider, "camuzzi")

    def test_edes_sender_is_routed_to_edes(self):
        provider = detect_provider(
            "noreply@edes.com.ar",
            "Factura EDES",
            "Pagar la cuota de servicio eléctrico.",
        )
        self.assertEqual(provider, "edes")

    def test_arba_sender_is_routed_to_arba(self):
        provider = detect_provider(
            "boletaelectronica@arba.gov.ar",
            "Boleta por Mail - Vencimiento del Impuesto Automotor Cuota 8",
            "El 9 de octubre vence la cuota 8 del Impuesto Automotor.",
        )

        self.assertEqual(provider, "arba")

    def test_brubank_sender_is_routed_as_aggregator(self):
        provider = detect_provider(
            "info@brubank.com",
            "Servicios por vencer",
            "Absa $ 24.497,46. Edes $ 134.836,32.",
        )

        self.assertEqual(provider, "brubank")

    def test_mercadopago_sender_is_routed_to_mercadopago(self):
        provider = detect_provider(
            "no-responder@mercadopago.com.ar",
            "Debitaremos el total de tu tarjeta el 13 de octubre",
        )

        self.assertEqual(provider, "mercadopago")

    def test_provider_email_filter_matches_only_the_expected_sender(self):
        self.assertTrue(email_matches_provider("personal", "facturacion@email.personal.com.ar"))
        self.assertTrue(email_matches_provider("camuzzi", "factura@factura.camuzzigas.com.ar"))
        self.assertTrue(email_matches_provider("arba", "boletaelectronica@arba.gov.ar"))
        self.assertTrue(email_matches_provider("mercadopago", "no-responder@mercadopago.com.ar"))
        self.assertFalse(email_matches_provider("personal", "factura@factura.camuzzigas.com.ar"))
        self.assertFalse(email_matches_provider("camuzzi", "facturacion@email.personal.com.ar"))
        self.assertFalse(email_matches_provider("arba", "facturacion@email.personal.com.ar"))
        self.assertFalse(email_matches_provider("mercadopago", "facturacion@email.personal.com.ar"))

    def test_parse_personal_bill_extracts_amount_and_due_date(self):
        text = """
        El saldo total es $93.552,09 y vence el 05/10/2026
        Total a pagar
        93.552,09
        Vencimiento
        05/10/2026
        Referente de pago
        1002892082210002
        """

        result = parse_personal_bill(text)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["service"], "Personal")
        self.assertEqual(result[0]["amount"], 93552.09)
        self.assertEqual(result[0]["date"], "2026-10-05")

    def test_parse_edes_bill_extracts_invoice_fields(self):
        text = """
        NIS 255211201
        Te acercamos la factura de tu último periodo de consumo por el servicio de calle
        19 DE MAYO Nro 551 02/A BAHIA BLANCA
        *Importe de factura*
        $46308,62
        *Vencimiento*
        25/09/2026
        """

        result = parse_edes_bill(text)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["service"], "EDES")
        self.assertEqual(result[0]["amount"], 46308.62)
        self.assertEqual(result[0]["date"], "2026-09-25")
        self.assertEqual(result[0]["location"], "19 DE MAYO Nro 551 02/A BAHIA BLANCA")
        self.assertEqual(result[0]["extra"], "NIS 255211201")

    def test_parse_camuzzi_bill_extracts_invoice_fields(self):
        text = """
        Camuzzi te acerca tu factura. Nro. Cuenta: 8000/0-1012-02042924 del periodo 04/26 — liquidación 2 de 2
        Factura 70003-47094827/1
        Total: $29.587,89
        Vencimiento: 06/10/2026
        """

        result = parse_camuzzi_bill(text)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["service"], "Camuzzi")
        self.assertEqual(result[0]["amount"], 29587.89)
        self.assertEqual(result[0]["date"], "2026-10-06")
        self.assertEqual(result[0]["location"], "Cuenta 8000/0-1012-02042924")
        self.assertEqual(result[0]["extra"], "Factura 70003-47094827/1")

    def test_camuzzi_sample_email_is_not_truncated_before_invoice_fields(self):
        sample_path = Path(__file__).resolve().parents[1] / "sample emails" / "camuzzi.eml"
        message = BytesParser(policy=policy.default).parsebytes(sample_path.read_bytes())

        result = parse_camuzzi_bill(extract_email_body(message))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["amount"], 29587.89)
        self.assertEqual(result[0]["date"], "2026-10-06")

    def test_parse_absa_bill_extracts_invoice_fields(self):
        result = parse_absa_bill(
            "Unidad de Facturación: 2220782 Vencimiento | 21/09/2026 Importe | $21514.46"
        )

        self.assertEqual(result[0]["service"], "ABSA")
        self.assertEqual(result[0]["amount"], 21514.46)
        self.assertEqual(result[0]["date"], "2026-09-21")
        self.assertEqual(result[0]["extra"], "Unidad de facturación 2220782")

    def test_parse_arba_automotor_sample(self):
        sample_path = Path(__file__).resolve().parents[1] / "sample emails" / "arba automotor.eml"
        message = BytesParser(policy=policy.default).parsebytes(sample_path.read_bytes())
        email_data = {
            "date": str(message["Date"]),
            "subject": str(message["Subject"]),
            "body": extract_email_body(message),
        }

        result = parser_dispatcher.parse_provider_bills("arba", [email_data])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["service"], "ARBA")
        self.assertEqual(result[0]["detail"], "Impuesto Automotor - Cuota 8")
        self.assertEqual(result[0]["location"], "Patente AD478JM")
        self.assertEqual(result[0]["amount"], 60469.90)
        self.assertEqual(result[0]["date"], "2026-10-09")

    def test_parse_arba_automotor_requires_message_date_for_yearless_due_date(self):
        result = parse_arba_bill(
            "El 9 de octubre vence la cuota 8 del Impuesto Automotor. "
            "Objeto Imponible AD478JM Importe $60.469,90"
        )

        self.assertEqual(result, [])

    def test_parse_brubank_sample_extracts_underlying_bills(self):
        sample_path = Path(__file__).resolve().parents[1] / "sample emails" / "brubank.eml"
        message = BytesParser(policy=policy.default).parsebytes(sample_path.read_bytes())

        result = parse_brubank_bill(extract_email_body(message))

        self.assertEqual([bill["service"] for bill in result], ["ABSA", "EDES"])
        self.assertEqual([bill["amount"] for bill in result], [24497.46, 134836.32])
        self.assertEqual([bill["date"] for bill in result], ["2026-07-20", "2026-07-20"])
        self.assertNotIn("Brubank", [bill["service"] for bill in result])

    def test_parse_brubank_credit_card_sample_as_brubank_bill(self):
        sample_path = Path(__file__).resolve().parents[1] / "sample emails" / "brubank tc.eml"
        message = BytesParser(policy=policy.default).parsebytes(sample_path.read_bytes())
        email_data = {
            "subject": str(message["Subject"]),
            "body": extract_email_body(message),
        }

        result = parser_dispatcher.parse_provider_bills("brubank", [email_data])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["service"], "Brubank")
        self.assertEqual(result[0]["detail"], "Resumen de tarjeta de crédito")
        self.assertEqual(result[0]["amount"], 795189.09)
        self.assertEqual(result[0]["date"], "2026-09-10")

    def test_parse_mercadopago_credit_card_sample(self):
        sample_path = Path(__file__).resolve().parents[1] / "sample emails" / "tarjeta mercadopago.eml"
        message = BytesParser(policy=policy.default).parsebytes(sample_path.read_bytes())
        email_data = {
            "date": str(message["Date"]),
            "subject": str(message["Subject"]),
            "body": extract_email_body(message),
        }

        result = parser_dispatcher.parse_provider_bills("mercadopago", [email_data])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["service"], "Mercado Pago")
        self.assertEqual(result[0]["detail"], "Resumen de tarjeta de crédito")
        self.assertEqual(result[0]["amount"], 799167.60)
        self.assertEqual(result[0]["date"], "2026-10-13")

    def test_parse_mercadopago_credit_card_uses_next_year_when_due_month_passed(self):
        result = parse_mercadopago_bill(
            "Tarjeta de crédito. El 10 de enero haremos el débito automático $ 5.000,00",
            "Sun, 28 Dec 2025 10:00:00 +0000",
        )

        self.assertEqual(result[0]["date"], "2026-01-10")

    def test_parse_movistar_bill_extracts_invoice_fields(self):
        result = parse_movistar_bill(
            "Vencimiento 19/07/2026 Total a pagar $52.049,99 "
            "Número de cuenta 11683637 Número de línea 2914186999"
        )

        self.assertEqual(result[0]["service"], "Movistar")
        self.assertEqual(result[0]["amount"], 52049.99)
        self.assertEqual(result[0]["date"], "2026-07-19")
        self.assertEqual(result[0]["extra"], "Cuenta 11683637")

    def test_parse_municipalidad_bill_extracts_invoice_fields(self):
        result = parse_municipalidad_bill(
            "Partida 201378- Cuota 09-2026 Vencimiento el 15/09/2026 "
            "Importe $50.800,00"
        )

        self.assertEqual(result[0]["service"], "Municipalidad de Bahía Blanca")
        self.assertEqual(result[0]["amount"], 50800.00)
        self.assertEqual(result[0]["date"], "2026-09-15")
        self.assertEqual(result[0]["extra"], "Cuota 09-2026")

    def test_grouping_keeps_provider_steps_separated(self):
        emails = [
            {
                "from": "facturacion@email.personal.com.ar",
                "from_email": "facturacion@email.personal.com.ar",
                "subject": "Factura de internet",
                "body": "Pagar su factura de cable e internet.",
            },
            {
                "from": "noreply@edes.com.ar",
                "from_email": "noreply@edes.com.ar",
                "subject": "EDES - Factura",
                "body": "Servicio eléctrico disponible.",
            },
        ]

        grouped = group_emails_by_provider(emails)

        self.assertIn("personal", grouped)
        self.assertIn("edes", grouped)
        self.assertEqual(len(grouped["personal"]), 1)
        self.assertEqual(len(grouped["edes"]), 1)

    def test_parallel_parsers_keep_successes_when_one_fails(self):
        def working_parser(_email_text):
            return [{"service": "Proveedor OK", "amount": 1}]

        def failing_parser(_email_text):
            raise ValueError("formato inesperado")

        grouped = {
            "working": [{"subject": "ok", "body": "factura"}],
            "broken": [{"subject": "error", "body": "factura"}],
        }
        with patch.dict(
            parser_dispatcher.PARSER_BY_PROVIDER,
            {"working": working_parser, "broken": failing_parser},
            clear=True,
        ):
            parsed, failures = parse_providers_in_parallel(grouped)

        self.assertEqual(parsed["working"][0]["service"], "Proveedor OK")
        self.assertIn("broken", failures)
        self.assertIn("formato inesperado", failures["broken"])


if __name__ == "__main__":
    unittest.main()
