"""
Med-punkt (METROBOT kiosk) — testlar.

Tekshiriladi:
  • kalit    — sozlanmagan boʻlsa 503, notoʻgʻri boʻlsa 401, boʻsh tana 400;
  • xulosa   — «meʼyorda / meʼyordan chetda» qarorini SERVER chiqaradi;
  • meʼyor   — shaxsiy meʼyor umumiy chegaradan ustun;
  • idempotentlik — bir xil `unikKalit` ikkinchi yozuv yaratmaydi;
  • tabel    — BLD0000212 → bazadagi 0212 ga bogʻlanadi;
  • egasiz   — tabelsiz oʻlchov hech kimga bogʻlanmaydi;
  • ruxsat   — panel maʼlumotlari faqat ruxsati borga, kolonna kesimida.
"""

from django.test import TestCase, override_settings

from api.tests import ishchi_yarat
from core.models import AccessOverride, Depo, Kolonna
from medpunkt.models import Hodisa, IshchiMeyor, MedPunkt, Olchov, Sozlama

KALIT = "sinov-kaliti-12345"
KIOSK = {"HTTP_X_API_KEY": KALIT}

INGEST = "/api/v1/medpunkt/ingest"
HODISA = "/api/v1/medpunkt/hodisa"
SYNC = "/api/v1/medpunkt/sync"


def login(client, tabel, pin):
    d = client.post(
        "/api/v1/auth/login",
        {"tabel": tabel, "pin": pin},
        content_type="application/json",
    ).json()
    return {"HTTP_AUTHORIZATION": f"Bearer {d['access']}"}


@override_settings(MEDPUNKT_API_KEY=KALIT)
class KioskIngestTest(TestCase):
    def setUp(self):
        Depo.joriy()
        self.worker = ishchi_yarat("0212", ["ishchi"])
        self.punkt = MedPunkt.objects.create(kod="BUX-1", nom="Buxoro deposi")

    def yubor(self, **body):
        body.setdefault("medPunkt", "BUX-1")
        return self.client.post(INGEST, body, content_type="application/json", **KIOSK)

    # --- kalit ---

    def test_kalitsiz_401(self):
        r = self.client.post(INGEST, {}, content_type="application/json")
        self.assertEqual(r.status_code, 401)

    def test_notogri_kalit_401(self):
        r = self.client.post(
            INGEST, {}, content_type="application/json", HTTP_X_API_KEY="boshqa"
        )
        self.assertEqual(r.status_code, 401)

    @override_settings(MEDPUNKT_API_KEY="")
    def test_kalit_sozlanmagan_503(self):
        """Kalit unutilsa endpoint ochiq qolmaydi, aksincha — yopiladi."""
        r = self.client.post(INGEST, {}, content_type="application/json", **KIOSK)
        self.assertEqual(r.status_code, 503)

    def test_bosh_tana_400(self):
        """Serverga qoʻyilgandan keyingi tekshiruv aynan shuni kutadi."""
        r = self.client.post(INGEST, {}, content_type="application/json", **KIOSK)
        self.assertEqual(r.status_code, 400)

    # --- xulosa serverda ---

    def test_alko_meyorda(self):
        r = self.yubor(tur="alko", tabel="0212", unikKalit="A|1",
                       qiymatlar={"mg_l": 0.0, "aktiv": True})
        self.assertEqual(r.status_code, 200)
        o = Olchov.objects.get(unik_kalit="A|1")
        self.assertEqual(o.holat, "normal")
        self.assertEqual(o.worker, self.worker)

    def test_javobda_kiosk_kutayotgan_holat_bor(self):
        """METROBOT `outbox.rs` xulosani javobning eng yuqori darajasidan oʻqiydi."""
        r = self.yubor(tur="alko", tabel="0212", unikKalit="A|K1",
                       qiymatlar={"mg_l": 0.3, "aktiv": True})
        self.assertEqual(r.json()["holat"], "flagged")
        self.assertIn("izoh", r.json())

    def test_alko_chegaradan_yuqori_flagged(self):
        self.yubor(tur="alko", tabel="0212", unikKalit="A|2",
                   qiymatlar={"mg_l": 0.3, "aktiv": True})
        self.assertEqual(Olchov.objects.get(unik_kalit="A|2").holat, "flagged")

    def test_passiv_rejim_chegarasi_pastroq(self):
        """0.05 mg/L aktivda meʼyorda, passivda — chetda."""
        self.yubor(tur="alko", tabel="0212", unikKalit="A|3",
                   qiymatlar={"mg_l": 0.05, "aktiv": True})
        self.yubor(tur="alko", tabel="0212", unikKalit="A|4",
                   qiymatlar={"mg_l": 0.05, "aktiv": False})
        self.assertEqual(Olchov.objects.get(unik_kalit="A|3").holat, "normal")
        self.assertEqual(Olchov.objects.get(unik_kalit="A|4").holat, "flagged")

    def test_qon_meyorda(self):
        self.yubor(tur="qon", tabel="0212", unikKalit="Q|1",
                   qiymatlar={"sistolik": 114, "diastolik": 73, "puls": 85})
        self.assertEqual(Olchov.objects.get(unik_kalit="Q|1").holat, "normal")

    def test_qon_chetda_sabab_izohda(self):
        self.yubor(tur="qon", tabel="0212", unikKalit="Q|2",
                   qiymatlar={"sistolik": 147, "diastolik": 95, "puls": 119})
        o = Olchov.objects.get(unik_kalit="Q|2")
        self.assertEqual(o.holat, "flagged")
        self.assertIn("sistolik 147 > 140", o.izoh)
        self.assertIn("puls 119 > 110", o.izoh)

    def test_kiosk_holatni_ozi_belgilay_olmaydi(self):
        """Kiosk `holat` yuborsa ham server oʻz xulosasini qoʻyadi."""
        self.yubor(tur="alko", tabel="0212", unikKalit="A|5", holat="normal",
                   qiymatlar={"mg_l": 0.9, "aktiv": True})
        self.assertEqual(Olchov.objects.get(unik_kalit="A|5").holat, "flagged")

    # --- shaxsiy meʼyor ---

    def test_shaxsiy_meyor_umumiy_chegaradan_ustun(self):
        IshchiMeyor.objects.create(
            worker=self.worker, sis_max=160, dia_max=100, puls_min=45, puls_max=120
        )
        self.yubor(tur="qon", tabel="0212", unikKalit="Q|3",
                   qiymatlar={"sistolik": 147, "diastolik": 95, "puls": 119})
        o = Olchov.objects.get(unik_kalit="Q|3")
        self.assertEqual(o.holat, "normal")
        self.assertIn("shaxsiy", o.izoh)

    # --- xodimni topish ---

    def test_karta_id_tabelga_keltiriladi(self):
        """Kiosk BLD0000212 yuboradi, bazada esa 0212 turadi."""
        self.yubor(tur="alko", tabel="BLD0000212", unikKalit="A|6",
                   qiymatlar={"mg_l": 0.0, "aktiv": True})
        o = Olchov.objects.get(unik_kalit="A|6")
        self.assertEqual(o.worker, self.worker)
        self.assertEqual(o.tabel, "BLD0000212")   # kioskdagi xom qiymat saqlanadi

    def test_tabelsiz_olchov_egasiz(self):
        self.yubor(tur="alko", unikKalit="A|7", qiymatlar={"mg_l": 0.0, "aktiv": False})
        o = Olchov.objects.get(unik_kalit="A|7")
        self.assertEqual(o.holat, "egasiz")
        self.assertTrue(o.egasiz)
        self.assertIsNone(o.worker)

    def test_notanish_tabel_baholanadi_lekin_belgilanadi(self):
        """Xodim bazada yoʻq — oʻlchov baribir baholanadi va yoʻqolmaydi."""
        self.yubor(tur="alko", tabel="BLD0009999", unikKalit="A|8",
                   qiymatlar={"mg_l": 0.0, "aktiv": False})
        o = Olchov.objects.get(unik_kalit="A|8")
        self.assertEqual(o.holat, "normal")
        self.assertIsNone(o.worker)
        self.assertIn("xodim serverda yoʻq", o.izoh)

    # --- idempotentlik va toʻplam ---

    def test_takroriy_yuborish_yangi_yozuv_yaratmaydi(self):
        for _ in range(3):
            self.yubor(tur="alko", tabel="0212", unikKalit="A|9",
                       qiymatlar={"mg_l": 0.0, "aktiv": True})
        self.assertEqual(Olchov.objects.filter(unik_kalit="A|9").count(), 1)

    def test_toplam_qabul_qilinadi(self):
        r = self.client.post(
            INGEST,
            {"olchovlar": [
                {"medPunkt": "BUX-1", "tur": "alko", "tabel": "0212",
                 "unikKalit": "B|1", "qiymatlar": {"mg_l": 0.0, "aktiv": True}},
                {"medPunkt": "BUX-1", "tur": "qon", "tabel": "0212",
                 "unikKalit": "B|2",
                 "qiymatlar": {"sistolik": 120, "diastolik": 80, "puls": 70}},
            ]},
            content_type="application/json", **KIOSK,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["qabul"], 2)
        self.assertEqual(Olchov.objects.count(), 2)

    def test_notanish_tur_rad_etiladi(self):
        r = self.yubor(tur="issiqlik", tabel="0212", unikKalit="X|1", qiymatlar={})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Olchov.objects.exists())

    def test_aloqa_vaqti_yangilanadi(self):
        self.assertIsNone(self.punkt.oxirgi_aloqa)
        self.yubor(tur="alko", tabel="0212", unikKalit="A|10",
                   qiymatlar={"mg_l": 0.0, "aktiv": True})
        self.punkt.refresh_from_db()
        self.assertIsNotNone(self.punkt.oxirgi_aloqa)

    def test_notanish_punkt_ozi_ochiladi(self):
        self.yubor(medPunkt="BUX-2", tur="alko", tabel="0212", unikKalit="A|11",
                   qiymatlar={"mg_l": 0.0, "aktiv": True})
        self.assertTrue(MedPunkt.objects.filter(kod="BUX-2").exists())


@override_settings(MEDPUNKT_API_KEY=KALIT)
class KioskHodisaSyncTest(TestCase):
    def setUp(self):
        Depo.joriy()
        self.worker = ishchi_yarat("0212", ["ishchi"])
        MedPunkt.objects.create(kod="BUX-1")

    def test_hodisa_yoziladi(self):
        r = self.client.post(
            HODISA,
            {"medPunkt": "BUX-1", "tur": "timeout", "tabel": "BLD0000212",
             "sessiyaId": "S-1", "tafsilot": "ALKO bosqichida vaqt tugadi",
             "vaqt": "2026-09-16T09:20:00+05:00"},
            content_type="application/json", **KIOSK,
        )
        self.assertEqual(r.status_code, 200)
        h = Hodisa.objects.get()
        self.assertEqual(h.worker, self.worker)
        self.assertFalse(h.korildi)

    def test_ayni_hodisa_ikki_marta_yozilmaydi(self):
        body = {"medPunkt": "BUX-1", "tur": "timeout", "sessiyaId": "S-2",
                "vaqt": "2026-09-16T09:20:00+05:00"}
        for _ in range(2):
            self.client.post(HODISA, body, content_type="application/json", **KIOSK)
        self.assertEqual(Hodisa.objects.count(), 1)

    def test_sync_xodimlar_va_chegaralarni_beradi(self):
        IshchiMeyor.objects.create(worker=self.worker, sis_max=160, dia_max=100)
        d = self.client.get(SYNC, **KIOSK).json()
        self.assertEqual(d["sozlamalar"]["qonSisMax"], 140)
        meniki = [x for x in d["xodimlar"] if x["tabel"] == "0212"][0]
        self.assertEqual(meniki["meyor"]["sisMax"], 160)

    def test_sync_yuz_vektorini_bermaydi(self):
        """Maxfiylik: kioskka yuz vektori ham, surat ham yuborilmaydi."""
        d = self.client.get(SYNC, **KIOSK).json()
        for x in d["xodimlar"]:
            self.assertNotIn("faceVector", x)
            self.assertNotIn("rasm", x)

    def test_sync_kalitsiz_401(self):
        self.assertEqual(self.client.get(SYNC).status_code, 401)


@override_settings(MEDPUNKT_API_KEY=KALIT)
class PanelTest(TestCase):
    def setUp(self):
        Depo.joriy()
        self.admin = ishchi_yarat("90001", ["admin"], pin="1234")
        self.ishchi = ishchi_yarat("90002", ["ishchi"], pin="1111")
        self.yoriqchi = ishchi_yarat("90003", ["yoriqchi"], pin="2222")
        self.begona = ishchi_yarat("90004", ["ishchi"])

        self.kolonna = Kolonna.objects.create(nomi="1-kolonna", instruktor=self.yoriqchi)
        self.ishchi.kolonna_ref = self.kolonna
        self.ishchi.save(update_fields=["kolonna_ref"])

        self.punkt = MedPunkt.objects.create(kod="BUX-1")
        self.meniki = self._olchov(self.ishchi, "O|1")
        self.begonaniki = self._olchov(self.begona, "O|2")

        self.auth = login(self.client, "90001", "1234")

    def _olchov(self, worker, kalit):
        from django.utils import timezone

        return Olchov.objects.create(
            med_punkt=self.punkt, worker=worker, tabel=worker.tabel,
            tur="alko", unik_kalit=kalit, olchov_vaqti=timezone.now(),
            qiymatlar={"mg_l": 0.0, "aktiv": True}, tasdiq={}, holat="normal",
        )

    def olchovlar(self, auth, **q):
        return self.client.get("/api/v1/medpunkt/olchovlar", q, **auth).json()

    # --- koʻrinish ---

    def test_admin_hammasini_koradi(self):
        self.assertEqual(self.olchovlar(self.auth)["jami"], 2)

    def test_ruxsatsiz_ishchi_403(self):
        r = self.client.get("/api/v1/medpunkt/olchovlar", **login(self.client, "90002", "1111"))
        self.assertEqual(r.status_code, 403)

    def test_yoriqchi_faqat_oz_kolonnasini_koradi(self):
        d = self.olchovlar(login(self.client, "90003", "2222"))
        idlar = [o["id"] for o in d["olchovlar"]]
        self.assertIn(str(self.meniki.id), idlar)
        self.assertNotIn(str(self.begonaniki.id), idlar)

    def test_ruxsat_berilsa_hammasini_koradi(self):
        AccessOverride.objects.create(
            scope="user", scope_id=str(self.yoriqchi.id),
            key="medpunkt.read.all", value=True,
        )
        self.assertEqual(self.olchovlar(login(self.client, "90003", "2222"))["jami"], 2)

    def test_tokensiz_401(self):
        self.assertEqual(self.client.get("/api/v1/medpunkt/olchovlar").status_code, 401)

    # --- filtrlar ---

    def test_filtr_holat_boyicha(self):
        self.begonaniki.holat = "flagged"
        self.begonaniki.save(update_fields=["holat"])
        self.assertEqual(self.olchovlar(self.auth, holat="flagged")["jami"], 1)

    def test_filtr_tabel_boyicha(self):
        self.assertEqual(self.olchovlar(self.auth, tabel="90002")["jami"], 1)

    # --- meʼyorlar ---

    def test_meyor_kiritish_va_ochirish(self):
        r = self.client.post(
            "/api/v1/medpunkt/meyorlar",
            {"tabel": "90002", "sisMax": 160, "diaMax": 100,
             "pulsMin": 45, "pulsMax": 120, "izoh": "gipertoniya"},
            content_type="application/json", **self.auth,
        )
        self.assertEqual(r.status_code, 200)
        m = IshchiMeyor.objects.get(worker=self.ishchi)
        self.assertEqual(m.sis_max, 160)
        self.assertEqual(m.shifokor, self.admin.fio)

        r = self.client.delete(
            f"/api/v1/medpunkt/meyorlar/{self.ishchi.id}", **self.auth
        )
        self.assertEqual(r.status_code, 200)
        m.refresh_from_db()
        self.assertTrue(m.deleted)

    def test_meyor_chegaradan_tashqari_400(self):
        r = self.client.post(
            "/api/v1/medpunkt/meyorlar",
            {"tabel": "90002", "sisMax": 400, "diaMax": 100,
             "pulsMin": 45, "pulsMax": 120},
            content_type="application/json", **self.auth,
        )
        self.assertEqual(r.status_code, 400)
        self.assertFalse(IshchiMeyor.objects.exists())

    def test_meyor_dia_sisdan_katta_400(self):
        r = self.client.post(
            "/api/v1/medpunkt/meyorlar",
            {"tabel": "90002", "sisMax": 100, "diaMax": 120,
             "pulsMin": 45, "pulsMax": 120},
            content_type="application/json", **self.auth,
        )
        self.assertEqual(r.status_code, 400)

    def test_meyor_yozish_ruxsatsiz_403(self):
        r = self.client.post(
            "/api/v1/medpunkt/meyorlar",
            {"tabel": "90002", "sisMax": 150, "diaMax": 95,
             "pulsMin": 45, "pulsMax": 120},
            content_type="application/json", **login(self.client, "90003", "2222"),
        )
        self.assertEqual(r.status_code, 403)

    # --- chegaralar ---

    def test_sozlama_saqlanadi(self):
        r = self.client.post(
            "/api/v1/medpunkt/sozlamalar",
            {"alkoChegaraMgL": 0.15, "qonSisMax": 145},
            content_type="application/json", **self.auth,
        )
        self.assertEqual(r.status_code, 200)
        s = Sozlama.joriy()
        self.assertEqual(s.qon_sis_max, 145)
        self.assertAlmostEqual(s.alko_chegara_mg_l, 0.15)

    def test_notogri_sozlama_saqlanmaydi(self):
        r = self.client.post(
            "/api/v1/medpunkt/sozlamalar",
            {"qonPulsMin": 150},
            content_type="application/json", **self.auth,
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Sozlama.joriy().qon_puls_min, 50)

    # --- hodisalar ---

    def test_hodisa_korildi(self):
        from django.utils import timezone

        h = Hodisa.objects.create(
            med_punkt=self.punkt, worker=self.ishchi, tur="timeout",
            vaqt=timezone.now(),
        )
        r = self.client.post(
            f"/api/v1/medpunkt/hodisalar/{h.id}/korildi", **self.auth
        )
        self.assertEqual(r.status_code, 200)
        h.refresh_from_db()
        self.assertTrue(h.korildi)

        d = self.client.get(
            "/api/v1/medpunkt/hodisalar", {"faqatYangi": "1"}, **self.auth
        ).json()
        self.assertEqual(d["hodisalar"], [])
