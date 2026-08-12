"""TB jurnali — yozuv oʻz bosqichi kitobiga saqlanishini tekshiradi."""
from django.test import TestCase

from core.models import Depo, JournalEntry
from api.tests import ishchi_yarat


class JurnalSaqlashTest(TestCase):
    def setUp(self):
        Depo.joriy()
        self.w = ishchi_yarat("10001", ["tb_xodim"], pin="1234")
        d = self.client.post(
            "/api/v1/auth/login",
            {"tabel": "10001", "pin": "1234"},
            content_type="application/json",
        ).json()
        self.tok = d["access"]

    def auth(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.tok}"}

    def post(self, **body):
        return self.client.post(
            "/api/v1/journal", body, content_type="application/json", **self.auth()
        )

    def test_ikkala_bosqich_alohida_kitobga_tushadi(self):
        for b in (1, 2):
            r = self.post(
                bosqich=b,
                sana="2026-08-12",
                komissiya=[{"fio": "Test Ism", "lavozim": "TB muhandisi"}],
                nomuvofiqlik=f"{b}-bosqich nomuvofiqlik",
                chora="chora",
                masul="Masul",
                masulLavozim="Usta",
                muddat="2026-08-20",
                bajarildi=False,
            )
            self.assertEqual(r.status_code, 200)
            st = r.json()["state"]
            rows = [j for j in st["journal"] if j["bosqich"] == b]
            self.assertEqual(len(rows), 1)

        self.assertEqual(JournalEntry.objects.count(), 2)

    def test_ikkinchi_yozuv_ustiga_qoshiladi(self):
        for i in range(3):
            r = self.post(
                bosqich=2,
                sana=f"2026-08-{10 + i:02d}",
                nomuvofiqlik=f"yozuv {i}",
                muddat="2026-08-25",
            )
            self.assertEqual(r.status_code, 200)
        rows = [j for j in r.json()["state"]["journal"] if j["bosqich"] == 2]
        self.assertEqual(len(rows), 3)
        # Eng yangisi tepada
        self.assertEqual([j["sana"] for j in rows], sorted([j["sana"] for j in rows], reverse=True))

    def test_sana_va_komissiya_serverda_toldiriladi(self):
        r = self.post(bosqich=1, nomuvofiqlik="sanasiz", muddat="2026-09-01")
        self.assertEqual(r.status_code, 200)
        j = [x for x in r.json()["state"]["journal"] if x["bosqich"] == 1][0]
        self.assertTrue(j["sana"])
        self.assertEqual(len(j["komissiya"]), 1)

    def test_notogri_bosqich_rad_etiladi(self):
        r = self.post(bosqich=5, nomuvofiqlik="x", muddat="2026-09-01")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(JournalEntry.objects.count(), 0)

    def test_tasdiqlash_qr_imzo_qoyadi(self):
        """7-ustun: “Tasdiqlash” → bajarildi + QR imzo (F.I.Sh. bilan)."""
        r = self.post(bosqich=1, nomuvofiqlik="ekran yoʻq", muddat="2026-09-01")
        j = [x for x in r.json()["state"]["journal"] if x["bosqich"] == 1][0]
        self.assertFalse(j["bajarildi"])
        self.assertIsNone(j["imzo"])

        r = self.client.post(
            f"/api/v1/journal/{j['id']}/sign",
            {"izoh": "Bajarildi, tekshirildi"},
            content_type="application/json",
            **self.auth(),
        )
        self.assertEqual(r.status_code, 200, r.content)

        j = [x for x in r.json()["state"]["journal"] if x["id"] == j["id"]][0]
        self.assertTrue(j["bajarildi"])
        self.assertEqual(j["bajarilganIzoh"], "Bajarildi, tekshirildi")
        # QR uchun kerak boʻlgan hamma narsa imzoda bor
        imzo = j["imzo"]
        self.assertTrue(imzo["id"])
        self.assertTrue(imzo["hash"])
        self.assertTrue(imzo["fio"])          # 7-ustunda F.I.Sh. koʻrinadi
        self.assertEqual(imzo["field"], "07")

    def test_ikki_marta_tasdiqlab_bolmaydi(self):
        r = self.post(bosqich=1, nomuvofiqlik="takror", muddat="2026-09-01")
        jid = [x for x in r.json()["state"]["journal"] if x["bosqich"] == 1][0]["id"]
        yol = f"/api/v1/journal/{jid}/sign"
        self.assertEqual(
            self.client.post(yol, {"izoh": "ok"}, content_type="application/json", **self.auth()).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(yol, {"izoh": "yana"}, content_type="application/json", **self.auth()).status_code,
            409,
        )

    def test_izoh_bosh_bolsa_ham_tasdiqlanadi(self):
        r = self.post(bosqich=2, nomuvofiqlik="izohsiz", muddat="2026-09-01")
        jid = [x for x in r.json()["state"]["journal"] if x["bosqich"] == 2][0]["id"]
        r = self.client.post(
            f"/api/v1/journal/{jid}/sign", {}, content_type="application/json", **self.auth()
        )
        self.assertEqual(r.status_code, 200)
        j = [x for x in r.json()["state"]["journal"] if x["id"] == jid][0]
        self.assertEqual(j["bajarilganIzoh"], "Bajarildi")

    def test_yoq_yozuvni_tasdiqlab_bolmaydi(self):
        import uuid
        r = self.client.post(
            f"/api/v1/journal/{uuid.uuid4()}/sign", {}, content_type="application/json", **self.auth()
        )
        self.assertEqual(r.status_code, 404)

    def test_ruxsatsiz_xodim_yoza_olmaydi(self):
        ishchi_yarat("20002", ["ishchi"], pin="1234")
        tok = self.client.post(
            "/api/v1/auth/login",
            {"tabel": "20002", "pin": "1234"},
            content_type="application/json",
        ).json()["access"]
        r = self.client.post(
            "/api/v1/journal",
            {"bosqich": 1, "nomuvofiqlik": "x", "muddat": "2026-09-01"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {tok}",
        )
        self.assertEqual(r.status_code, 403)
