import unittest

from agent_facturas_gmail_github import (
    detect_provider,
    email_matches_provider,
    group_emails_by_provider,
    parse_absa_bill,
    parse_edes_bill,
    parse_movistar_bill,
    parse_municipalidad_bill,
    parse_personal_bill,
)


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

    def test_provider_email_filter_matches_only_the_expected_sender(self):
        self.assertTrue(email_matches_provider("personal", "facturacion@email.personal.com.ar"))
        self.assertTrue(email_matches_provider("camuzzi", "factura@factura.camuzzigas.com.ar"))
        self.assertFalse(email_matches_provider("personal", "factura@factura.camuzzigas.com.ar"))
        self.assertFalse(email_matches_provider("camuzzi", "facturacion@email.personal.com.ar"))

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

    def test_parse_absa_bill_extracts_invoice_fields(self):
        result = parse_absa_bill(
            "Unidad de Facturación: 2220782 Vencimiento | 21/09/2026 Importe | $21514.46"
        )

        self.assertEqual(result[0]["service"], "ABSA")
        self.assertEqual(result[0]["amount"], 21514.46)
        self.assertEqual(result[0]["date"], "2026-09-21")
        self.assertEqual(result[0]["extra"], "Unidad de facturación 2220782")

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


if __name__ == "__main__":
    unittest.main()
