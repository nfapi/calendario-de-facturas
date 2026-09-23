import unittest

from agent_facturas_gmail_github import detect_provider, group_emails_by_provider


class ProviderRoutingTests(unittest.TestCase):
    def test_personal_sender_is_routed_to_personal(self):
        provider = detect_provider(
            "facturacion@email.personal.com.ar",
            "Factura de internet",
            "Vence el 15/10 y corresponde a cable/internet.",
        )
        self.assertEqual(provider, "personal")

    def test_edes_sender_is_routed_to_edes(self):
        provider = detect_provider(
            "noreply@edes.com.ar",
            "Factura EDES",
            "Pagar la cuota de servicio eléctrico.",
        )
        self.assertEqual(provider, "edes")

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
