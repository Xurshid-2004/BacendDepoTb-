"""
Koʻrik boʻlimlari — tibbiy koʻrik va psixolog.

Tekshiriladi:
  • tibbiy   — qayta oʻtish sanasi toʻgʻridan kiritiladi (muddat hisoblanmaydi);
  • psixolog — oʻtgan sana + muddat (3/6/12) → tugash serverda hisoblanadi;
  • ruxsat   — yozish uchun <turi>.write shart (403);
  • cheklov  — oddiy ishchi faqat OʻZINING yozuvini koʻradi;
  • kolonna  — mashinist yoʻriqchisi faqat OʻZ KOLONNASINI koʻradi;
  • oʻchirish — yozuv oʻchadi, QR imzo bekor qilinadi.
"""
from datetime import date

from django.test import TestCase

from api.tests import ishchi_yarat
from core.logic import add_months
from core.models import Depo, Korik, Kolonna, Notification, Position, Signature


def login(client, tabel, pin):
    d = client.post(
        "/api/v1/auth/login",
        {"tabel": tabel, "pin": pin},
        content_type="application/json",
    ).json()
    return {"HTTP_AUTHORIZATION": f"Bearer {d['access']}"}


class KorikYozishTest(TestCase):
    def setUp(self):
        Depo.joriy()
        self.admin = ishchi_yarat("90001", ["admin"], pin="1234")
        self.worker = ishchi_yarat("90002", ["ishchi"], pin="1111")
        self.auth = login(self.client, "90001", "1234")

    def post(self, **body):
        return self.client.post(
            "/api/v1/koriklar", body, content_type="application/json", **self.auth
        )

    def test_tibbiy_qayta_otish_sanasi_togridan(self):
        r = self.post(turi="tibbiy", workerId=str(self.worker.id), tugash="2027-03-01")
        self.assertEqual(r.status_code, 200)
        k = Korik.objects.get(worker=self.worker, turi="tibbiy")
        self.assertEqual(k.tugash, date(2027, 3, 1))
        self.assertIsNone(k.muddat_oy)          # tibbiyda muddat hisoblanmaydi
        self.assertTrue(k.imzo_id)              # QR imzo qoʻyildi
        self.assertTrue(
            Notification.objects.filter(worker=self.worker, sarlavha="Tibbiy koʻrik").exists()
        )

    def test_psixolog_muddatdan_hisoblanadi(self):
        r = self.post(turi="psixolog", workerId=str(self.worker.id),
                      sana="2026-09-01", muddatOy=6)
        self.assertEqual(r.status_code, 200)
        k = Korik.objects.get(worker=self.worker, turi="psixolog")
        self.assertEqual(k.muddat_oy, 6)
        self.assertEqual(k.tugash, add_months(date(2026, 9, 1), 6))

    def test_bitta_yozuv_yangilanadi(self):
        self.post(turi="tibbiy", workerId=str(self.worker.id), tugash="2027-03-01")
        self.post(turi="tibbiy", workerId=str(self.worker.id), tugash="2027-06-01")
        self.assertEqual(
            Korik.objects.filter(worker=self.worker, turi="tibbiy").count(), 1
        )
        k = Korik.objects.get(worker=self.worker, turi="tibbiy")
        self.assertEqual(k.tugash, date(2027, 6, 1))

    def test_tibbiy_va_psixolog_alohida(self):
        self.post(turi="tibbiy", workerId=str(self.worker.id), tugash="2027-03-01")
        self.post(turi="psixolog", workerId=str(self.worker.id), sana="2026-09-01", muddatOy=3)
        self.assertEqual(Korik.objects.filter(worker=self.worker).count(), 2)

    # --- xato holatlari ---

    def test_tibbiy_sanasiz_400(self):
        r = self.post(turi="tibbiy", workerId=str(self.worker.id))
        self.assertEqual(r.status_code, 400)

    def test_psixolog_notogri_muddat_400(self):
        r = self.post(turi="psixolog", workerId=str(self.worker.id),
                      sana="2026-09-01", muddatOy=5)
        self.assertEqual(r.status_code, 400)

    def test_notogri_turi_400(self):
        r = self.post(turi="boshqa", workerId=str(self.worker.id), tugash="2027-03-01")
        self.assertEqual(r.status_code, 400)

    def test_ruxsatsiz_403(self):
        # oddiy ishchida tibbiy.write yoʻq
        auth = login(self.client, "90002", "1111")
        r = self.client.post(
            "/api/v1/koriklar",
            {"turi": "tibbiy", "workerId": str(self.worker.id), "tugash": "2027-03-01"},
            content_type="application/json", **auth,
        )
        self.assertEqual(r.status_code, 403)

    def test_ochirish_imzoni_bekor_qiladi(self):
        self.post(turi="tibbiy", workerId=str(self.worker.id), tugash="2027-03-01")
        k = Korik.objects.get(worker=self.worker, turi="tibbiy")
        imzo_id = k.imzo_id
        r = self.client.delete(
            f"/api/v1/koriklar/{self.worker.id}/tibbiy", **self.auth
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Korik.objects.filter(id=k.id).exists())
        self.assertTrue(Signature.objects.get(id=imzo_id).bekor)


class KorikKorinishTest(TestCase):
    """build_state — kim qaysi yozuvni koʻradi."""

    def setUp(self):
        Depo.joriy()
        self.admin = ishchi_yarat("90010", ["admin"], pin="1234")
        self.w1 = ishchi_yarat("90011", ["ishchi"], pin="1111")
        self.w2 = ishchi_yarat("90012", ["ishchi"], pin="2222")
        aut = login(self.client, "90010", "1234")
        for w in (self.w1, self.w2):
            self.client.post(
                "/api/v1/koriklar",
                {"turi": "tibbiy", "workerId": str(w.id), "tugash": "2027-03-01"},
                content_type="application/json", **aut,
            )

    def state(self, tabel, pin):
        aut = login(self.client, tabel, pin)
        return self.client.get("/api/v1/state", **aut).json()["data"]

    def test_admin_hammani_koradi(self):
        data = self.state("90010", "1234")
        self.assertEqual(len(data["koriklar"]), 2)

    def test_oddiy_ishchi_faqat_ozini(self):
        data = self.state("90011", "1111")
        self.assertEqual(len(data["koriklar"]), 1)
        self.assertEqual(data["koriklar"][0]["workerId"], str(self.w1.id))


class KorikKolonnaTest(TestCase):
    """Mashinist yoʻriqchisi faqat oʻz kolonnasi koʻriklarini koʻradi."""

    def setUp(self):
        Depo.joriy()
        pos = Position.objects.create(depo=Depo.joriy(), nomi="Teplovoz mashinisti", tartib=1)
        self.admin = ishchi_yarat("90020", ["admin"], pin="1234")
        self.yoriqchi = ishchi_yarat("90021", ["yoriqchi"], pin="1111")
        self.kol = Kolonna.objects.create(
            nomi="1-kolonna", turi="teplovoz", instruktor=self.yoriqchi, faol=True
        )
        self.menda = ishchi_yarat("90022", ["ishchi"], pos)
        self.menda.kolonna_ref = self.kol
        self.menda.save(update_fields=["kolonna_ref"])
        self.boshqa = ishchi_yarat("90023", ["ishchi"], pos)  # kolonnasiz

        aut = login(self.client, "90020", "1234")
        for w in (self.menda, self.boshqa):
            self.client.post(
                "/api/v1/koriklar",
                {"turi": "tibbiy", "workerId": str(w.id), "tugash": "2027-03-01"},
                content_type="application/json", **aut,
            )

    def test_yoriqchi_faqat_kolonnasini(self):
        aut = login(self.client, "90021", "1111")
        data = self.client.get("/api/v1/state", **aut).json()["data"]
        ids = {k["workerId"] for k in data["koriklar"]}
        self.assertIn(str(self.menda.id), ids)
        self.assertNotIn(str(self.boshqa.id), ids)
