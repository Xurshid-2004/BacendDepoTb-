"""
=====================================================================
API testlari.

Ishga tushirish:
    python manage.py test api

Testlar SQLite (xotirada) bazasida ishlaydi — Postgres talab qilinmaydi.
Qamrov: autentifikatsiya, ruxsatlar, ariza oqimi, ombor, holat shakli.
=====================================================================
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.logic import add_months, make_hash, today
from core.models import (
    AccessOverride, Card, Depo, Item, Kip, Kolonna, Norm, Position, Qurilma,
    RefreshToken, Request, Stock, Talon, Worker,
)
from core.pin import hash_pin, verify_pin


def ishchi_yarat(tabel: str, roles: list[str], position=None, pin: str | None = None) -> Worker:
    w = Worker.objects.create(
        depo=Depo.joriy(),
        tabel=tabel,
        familiya=f"Familiya{tabel}",
        ism="Ism",
        roles=roles,
        position=position,
        faol=True,
    )
    w.set_unusable_password()
    if pin:
        w.set_pin(pin)
    w.save()
    if position:
        w.positions.set([position])
    Card.objects.create(worker=w, ochilgan=today())
    for r in (1, 2, 3):
        Talon.objects.create(worker=w, raqam=r)
    return w


class PinTest(TestCase):
    """PIN ikkala formatda ham tanilishi kerak."""

    def test_pbkdf2_aylanma(self):
        h = hash_pin("1234")
        self.assertIn(":", h)
        self.assertTrue(verify_pin("1234", h))
        self.assertFalse(verify_pin("4321", h))

    def test_bosh_qiymatlar(self):
        self.assertFalse(verify_pin("1234", None))
        self.assertFalse(verify_pin("1234", ""))
        self.assertFalse(verify_pin("", hash_pin("1234")))

    def test_eski_scrypt_formati(self):
        """Eski Next.js backend'i yozgan scrypt hash'i ham ishlashi kerak."""
        import hashlib
        import secrets

        salt = secrets.token_bytes(16)
        dk = hashlib.scrypt(b"1234", salt=salt, n=16384, r=8, p=1,
                            dklen=32, maxmem=64 * 1024 * 1024)
        eski = f"{salt.hex()}:{dk.hex()}"
        self.assertTrue(verify_pin("1234", eski))
        self.assertFalse(verify_pin("0000", eski))

    def test_hash_frontend_bilan_mos(self):
        """makeHash frontend'dagi bilan bir xil natija berishi kerak."""
        self.assertEqual(len(make_hash("test")), 16)
        self.assertEqual(make_hash("abc"), make_hash("abc"))
        self.assertNotEqual(make_hash("abc"), make_hash("abd"))


class AuthTest(TestCase):
    def setUp(self):
        self.depo = Depo.joriy()
        self.w = ishchi_yarat("10001", ["admin"], pin="1234")

    def test_login_muvaffaqiyatli(self):
        r = self.client.post("/api/v1/auth/login",
                             {"tabel": "10001", "pin": "1234"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertIn("access", d)
        self.assertIn("refresh", d)
        self.assertIn("user", d)

    def test_pin_hash_hech_qachon_chiqmaydi(self):
        """Eng muhim tekshiruv — PIN hash mijozga ketmasligi kerak."""
        r = self.client.post("/api/v1/auth/login",
                             {"tabel": "10001", "pin": "1234"},
                             content_type="application/json")
        matn = r.content.decode()
        self.assertNotIn("pinHash", matn)
        self.assertNotIn(self.w.pin_hash, matn)
        self.assertTrue(r.json()["user"]["pinSet"])

    def test_notogri_pin(self):
        r = self.client.post("/api/v1/auth/login",
                             {"tabel": "10001", "pin": "0000"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 401)

    def test_pin_yoq_bolsa_needsPin(self):
        ishchi_yarat("10002", ["ishchi"])
        r = self.client.post("/api/v1/auth/login",
                             {"tabel": "10002", "pin": ""},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("needsPin"))

    def test_set_pin_faqat_bir_marta(self):
        ishchi_yarat("10003", ["ishchi"])
        r1 = self.client.post("/api/v1/auth/set-pin",
                              {"tabel": "10003", "pin": "5555"},
                              content_type="application/json")
        self.assertEqual(r1.status_code, 200)
        # Ikkinchi marta — rad etilishi kerak
        r2 = self.client.post("/api/v1/auth/set-pin",
                              {"tabel": "10003", "pin": "6666"},
                              content_type="application/json")
        self.assertEqual(r2.status_code, 409)

    def test_pin_format_tekshiruvi(self):
        ishchi_yarat("10004", ["ishchi"])
        r = self.client.post("/api/v1/auth/set-pin",
                             {"tabel": "10004", "pin": "abc"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_state_tokensiz_yopiq(self):
        self.assertEqual(self.client.get("/api/v1/state").status_code, 401)

    def test_refresh_va_logout(self):
        d = self.client.post("/api/v1/auth/login",
                             {"tabel": "10001", "pin": "1234"},
                             content_type="application/json").json()
        r = self.client.post("/api/v1/auth/refresh", {"refresh": d["refresh"]},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", r.json())

        self.client.post("/api/v1/auth/logout", {"refresh": d["refresh"]},
                         content_type="application/json")
        # Chiqishdan keyin refresh ishlamasligi kerak
        r2 = self.client.post("/api/v1/auth/refresh", {"refresh": d["refresh"]},
                              content_type="application/json")
        self.assertEqual(r2.status_code, 401)

    def test_faolsiz_ishchi_kira_olmaydi(self):
        self.w.faol = False
        self.w.save()
        r = self.client.post("/api/v1/auth/login",
                             {"tabel": "10001", "pin": "1234"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 401)


class StateShakliTest(TestCase):
    """GET /state frontend'dagi DB interfeysiga mos boʻlishi shart."""

    KUTILGAN = {
        "depo", "positions", "items", "norms", "workers", "cards", "requests",
        "journal", "stock", "moves", "talons", "exams", "kips", "notifications",
        "incidents", "audit", "lines", "units", "kolonnalar", "yoriqnoma", "access", "seq",
    }

    def setUp(self):
        Depo.joriy()
        self.w = ishchi_yarat("10001", ["admin"], pin="1234")
        d = self.client.post("/api/v1/auth/login",
                             {"tabel": "10001", "pin": "1234"},
                             content_type="application/json").json()
        self.tok = d["access"]

    def auth(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.tok}"}

    def test_barcha_kalitlar_mavjud(self):
        st = self.client.get("/api/v1/state", **self.auth()).json()["data"]
        self.assertEqual(set(st.keys()), self.KUTILGAN)

    def test_access_tuzilmasi(self):
        st = self.client.get("/api/v1/state", **self.auth()).json()["data"]
        self.assertEqual(
            set(st["access"].keys()),
            {"roleOverrides", "positionOverrides", "userOverrides"},
        )

    def test_workerda_pin_va_surat_yoq(self):
        st = self.client.get("/api/v1/state", **self.auth()).json()["data"]
        for w in st["workers"]:
            self.assertNotIn("pinHash", w)
            self.assertNotIn("faceImage", w)
            self.assertIn("pinSet", w)


class ArizaOqimiTest(TestCase):
    """Ariza bosqichma-bosqich oʻtishi va ruxsatlar."""

    def setUp(self):
        self.depo = Depo.joriy()
        self.pos = Position.objects.create(depo=self.depo, nomi="Chilangar", tartib=1)
        self.item = Item.objects.create(nomi="Kaska", unit="dona", narx=100000)
        Stock.objects.create(item=self.item, qoldiq=50)
        # muddat_oy = None → "Ish. Chiqqun", doim soʻrash mumkin
        Norm.objects.create(position=self.pos, item=self.item, muddat_oy=None)

        self.ishchi = ishchi_yarat("2001", ["ishchi"], self.pos, pin="1111")
        self.bugalter = ishchi_yarat("2002", ["bugalter"], pin="2222")
        self.bosh_xis = ishchi_yarat("2003", ["bosh_xisobchi"], pin="3333")
        self.boshliq = ishchi_yarat("2004", ["depo_boshligi"], pin="4444")
        self.ombor = ishchi_yarat("2005", ["ombor_mudiri"], pin="5555")

    def kir(self, tabel: str, pin: str) -> dict:
        d = self.client.post("/api/v1/auth/login", {"tabel": tabel, "pin": pin},
                             content_type="application/json").json()
        return {"HTTP_AUTHORIZATION": f"Bearer {d['access']}"}

    def test_toliq_oqim(self):
        # 1. Ishchi ariza yuboradi
        r = self.client.post("/api/v1/requests",
                             {"itemIds": [str(self.item.id)]},
                             content_type="application/json",
                             **self.kir("2001", "1111"))
        self.assertEqual(r.status_code, 200, r.content)

        req = Request.objects.get()
        self.assertEqual(req.status, "SUBMITTED")
        self.assertTrue(req.raqam.startswith("TCH6-"))

        # 2. Bosqichma-bosqich tasdiqlash
        yol = [
            ("2002", "2222", "ACCOUNTANT_APPROVED"),
            ("2003", "3333", "CHIEF_APPROVED"),
            ("2004", "4444", "HEAD_APPROVED"),
            ("2005", "5555", "ISSUED"),
            ("2001", "1111", "RECEIVED"),      # ishchi oʻzi tasdiqlaydi
            ("2005", "5555", "COMPLETED"),
        ]
        for tabel, pin, kutilgan in yol:
            r = self.client.post(f"/api/v1/requests/{req.id}/advance", {},
                                 content_type="application/json",
                                 **self.kir(tabel, pin))
            self.assertEqual(r.status_code, 200, f"{tabel}: {r.content}")
            req.refresh_from_db()
            self.assertEqual(req.status, kutilgan)

        # 3. Yakunlangach: ombordan chiqim va kartochkaga yozuv
        self.assertEqual(Stock.objects.get(item=self.item).qoldiq, 49)
        card = Card.objects.get(worker=self.ishchi)
        self.assertEqual(card.berilgan.count(), 1)
        self.assertIsNotNone(req.yakunlangan)

    def test_notogri_rol_otkaza_olmaydi(self):
        self.client.post("/api/v1/requests", {"itemIds": [str(self.item.id)]},
                         content_type="application/json", **self.kir("2001", "1111"))
        req = Request.objects.get()

        # Ombor mudiri SUBMITTED bosqichida harakat qila olmaydi
        r = self.client.post(f"/api/v1/requests/{req.id}/advance", {},
                             content_type="application/json", **self.kir("2005", "5555"))
        self.assertEqual(r.status_code, 403)
        req.refresh_from_db()
        self.assertEqual(req.status, "SUBMITTED")

    def test_ochiq_ariza_takrorlanmaydi(self):
        h = self.kir("2001", "1111")
        r1 = self.client.post("/api/v1/requests", {"itemIds": [str(self.item.id)]},
                              content_type="application/json", **h)
        self.assertEqual(r1.status_code, 200)
        # Ayni buyumga ikkinchi ariza — rad etilishi kerak
        r2 = self.client.post("/api/v1/requests", {"itemIds": [str(self.item.id)]},
                              content_type="application/json", **h)
        self.assertEqual(r2.status_code, 400)
        self.assertEqual(Request.objects.count(), 1)

    def test_rad_etish_sabab_talab_qiladi(self):
        self.client.post("/api/v1/requests", {"itemIds": [str(self.item.id)]},
                         content_type="application/json", **self.kir("2001", "1111"))
        req = Request.objects.get()

        # Bugalter sababsiz rad eta olmaydi
        r = self.client.post(f"/api/v1/requests/{req.id}/reject", {},
                             content_type="application/json", **self.kir("2002", "2222"))
        self.assertEqual(r.status_code, 400)

        r = self.client.post(f"/api/v1/requests/{req.id}/reject", {"izoh": "Muddati kelmagan"},
                             content_type="application/json", **self.kir("2002", "2222"))
        self.assertEqual(r.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.status, "REJECTED")

    def test_ariza_raqami_takrorlanmaydi(self):
        """800 foydalanuvchi uchun muhim — raqam ketma-ketligi atomik."""
        item2 = Item.objects.create(nomi="Koʻzoynak", unit="dona", narx=50000)
        Norm.objects.create(position=self.pos, item=item2, muddat_oy=None)
        Stock.objects.create(item=item2, qoldiq=10)

        h = self.kir("2001", "1111")
        self.client.post("/api/v1/requests", {"itemIds": [str(self.item.id)]},
                         content_type="application/json", **h)
        self.client.post("/api/v1/requests", {"itemIds": [str(item2.id)]},
                         content_type="application/json", **h)

        raqamlar = list(Request.objects.values_list("raqam", flat=True))
        self.assertEqual(len(raqamlar), 2)
        self.assertEqual(len(set(raqamlar)), 2)


class RuxsatTest(TestCase):
    def setUp(self):
        Depo.joriy()
        self.item = Item.objects.create(nomi="Kaska", unit="dona", narx=1000)
        Stock.objects.create(item=self.item, qoldiq=5)
        self.ishchi = ishchi_yarat("3001", ["ishchi"], pin="1111")
        self.ombor = ishchi_yarat("3002", ["ombor_mudiri"], pin="2222")

    def kir(self, tabel, pin):
        d = self.client.post("/api/v1/auth/login", {"tabel": tabel, "pin": pin},
                             content_type="application/json").json()
        return {"HTTP_AUTHORIZATION": f"Bearer {d['access']}"}

    def test_ishchi_omborga_kirim_qila_olmaydi(self):
        r = self.client.post("/api/v1/stock/in",
                             {"itemId": str(self.item.id), "soni": 10, "izoh": "sinov"},
                             content_type="application/json", **self.kir("3001", "1111"))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Stock.objects.get(item=self.item).qoldiq, 5)

    def test_ombor_mudiri_kirim_qila_oladi(self):
        r = self.client.post("/api/v1/stock/in",
                             {"itemId": str(self.item.id), "soni": 10, "izoh": "sinov"},
                             content_type="application/json", **self.kir("3002", "2222"))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Stock.objects.get(item=self.item).qoldiq, 15)

    def test_manfiy_kirim_rad_etiladi(self):
        r = self.client.post("/api/v1/stock/in",
                             {"itemId": str(self.item.id), "soni": -5},
                             content_type="application/json", **self.kir("3002", "2222"))
        self.assertEqual(r.status_code, 400)

    def test_ishchi_admin_amalini_bajara_olmaydi(self):
        r = self.client.put("/api/v1/workers",
                            {"tabel": "9999", "familiya": "X", "ism": "Y"},
                            content_type="application/json", **self.kir("3001", "1111"))
        self.assertEqual(r.status_code, 403)


class YangiIshchiTest(TestCase):
    """
    Admin panelida qoʻshilgan ishchi jadvalda koʻrinishi va oʻsha ishchi
    tizimga kira olishi kerak.
    """

    def setUp(self):
        self.depo = Depo.joriy()
        self.pos = Position.objects.create(depo=self.depo, nomi="Slesar", tartib=1)
        self.admin = ishchi_yarat("3001", ["admin"], pin="1234")

    def kir(self, tabel: str, pin: str) -> dict:
        d = self.client.post("/api/v1/auth/login", {"tabel": tabel, "pin": pin},
                             content_type="application/json").json()
        return {"HTTP_AUTHORIZATION": f"Bearer {d['access']}"}

    def qosh(self, **qoshimcha) -> "object":
        tana = {
            "tabel": "5001",
            "familiya": "Testov",
            "ism": "Test",
            "otasi": "Testovich",
            "positionId": str(self.pos.id),
            "positionIds": [str(self.pos.id)],
            "roles": ["ishchi"],
            "faol": True,
        }
        tana.update(qoshimcha)
        return self.client.put("/api/v1/workers", tana, content_type="application/json",
                               **self.kir("3001", "1234"))

    def test_soxta_id_bilan_qoshiladi(self):
        """
        Frontend yangi ishchi uchun UUID boʻlmagan vaqtinchalik id
        yuborsa ham yozuv yaratilishi kerak (ilgari 400 qaytardi).
        """
        r = self.qosh(id="w1754745600000")
        self.assertEqual(r.status_code, 200, r.content)

        w = Worker.objects.filter(tabel="5001").first()
        self.assertIsNotNone(w)
        self.assertNotEqual(str(w.id), "w1754745600000")

        # Javobdagi holatda — yaʼni admin jadvalida — koʻrinadi
        tabellar = [x["tabel"] for x in r.json()["state"]["workers"]]
        self.assertIn("5001", tabellar)

        # Yangi ishchiga kartochka va 3 ta talon ochiladi
        self.assertTrue(Card.objects.filter(worker=w).exists())
        self.assertEqual(Talon.objects.filter(worker=w).count(), 3)

    def test_pinsiz_ishchi_ozi_ornatib_kiradi(self):
        self.qosh()

        # PIN yoʻq — server yangisini soʻraydi
        r = self.client.post("/api/v1/auth/login", {"tabel": "5001", "pin": ""},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["needsPin"])

        # Ishchi oʻzi oʻrnatadi va darrov tokenlarni oladi
        r = self.client.post("/api/v1/auth/set-pin", {"tabel": "5001", "pin": "4321"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("access", r.json())

        # Endi oddiy kirish ishlaydi
        r = self.client.post("/api/v1/auth/login", {"tabel": "5001", "pin": "4321"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("access", r.json())

    def test_admin_boshlangich_pin_beradi(self):
        r = self.qosh(pin="8765")
        self.assertEqual(r.status_code, 200, r.content)

        # Oʻsha PIN bilan darrov kiradi — set-pin bosqichisiz
        r = self.client.post("/api/v1/auth/login", {"tabel": "5001", "pin": "8765"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("access", r.json())

    def test_notogri_pin_formati_rad_etiladi(self):
        r = self.qosh(pin="12")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Worker.objects.filter(tabel="5001").exists())

    def test_takror_tabel_rad_etiladi(self):
        self.assertEqual(self.qosh().status_code, 200)
        r = self.qosh(familiya="Boshqa")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Worker.objects.filter(tabel="5001").count(), 1)

    def test_haqiqiy_uuid_bilan_tahrirlanadi(self):
        """Mavjud ishchi yangi yozuv sifatida takrorlanmasligi kerak."""
        self.qosh(pin="8765")
        w = Worker.objects.get(tabel="5001")

        r = self.qosh(id=str(w.id), familiya="Tuzatildi")
        self.assertEqual(r.status_code, 200, r.content)

        self.assertEqual(Worker.objects.filter(tabel="5001").count(), 1)
        w.refresh_from_db()
        self.assertEqual(w.familiya, "Tuzatildi")
        # Tahrirlash PIN'ni yoʻqotmasligi kerak
        self.assertTrue(w.check_pin("8765"))

    # --- oʻchirish ---

    def och(self, worker) -> "object":
        return self.client.delete(f"/api/v1/workers/{worker.id}",
                                  **self.kir("3001", "1234"))

    def test_ochirish_soft_delete(self):
        """Yozuv bazadan yoʻqolmasligi kerak — tarix saqlanadi."""
        self.qosh(pin="4321")
        w = Worker.objects.get(tabel="5001")

        r = self.och(w)
        self.assertEqual(r.status_code, 200, r.content)

        w.refresh_from_db()
        self.assertTrue(w.deleted)
        self.assertFalse(w.faol)
        # Kartochka va talonlar joyida — hujjat tarixi buzilmadi
        self.assertTrue(Card.objects.filter(worker=w).exists())
        self.assertEqual(Talon.objects.filter(worker=w).count(), 3)

    def test_ochirilgan_ishchi_kira_olmaydi(self):
        self.qosh(pin="4321")
        w = Worker.objects.get(tabel="5001")
        self.assertEqual(
            self.client.post("/api/v1/auth/login", {"tabel": "5001", "pin": "4321"},
                             content_type="application/json").status_code,
            200,
        )
        self.och(w)
        r = self.client.post("/api/v1/auth/login", {"tabel": "5001", "pin": "4321"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 401)

    def test_ochirilgan_ishchi_holatda_korinmaydi(self):
        self.qosh()
        w = Worker.objects.get(tabel="5001")
        r = self.och(w)
        tabellar = [x["tabel"] for x in r.json()["state"]["workers"]]
        self.assertNotIn("5001", tabellar)

    def test_ozini_ochira_olmaydi(self):
        r = self.och(self.admin)
        self.assertEqual(r.status_code, 400)
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.deleted)

    def test_oxirgi_admin_ochirilmaydi(self):
        """Tizim administratorsiz qolib ketmasligi kerak."""
        boshqa = ishchi_yarat("3005", ["admin"], pin="1234")

        # Ikkinchi admin bor — oʻchirish mumkin
        r = self.client.delete(f"/api/v1/workers/{boshqa.id}", **self.kir("3001", "1234"))
        self.assertEqual(r.status_code, 200, r.content)

        # Endi self.admin yagona qoldi. Uni boshqa admin oʻchira olmaydi:
        yana = ishchi_yarat("3006", ["admin"], pin="1234")
        r = self.client.delete(f"/api/v1/workers/{self.admin.id}", **self.kir("3006", "1234"))
        self.assertEqual(r.status_code, 200, r.content)   # 3006 qolgani uchun mumkin

        # 3006 endi yagona admin — oʻzini ham oʻchira olmaydi
        r = self.client.delete(f"/api/v1/workers/{yana.id}", **self.kir("3006", "1234"))
        self.assertEqual(r.status_code, 400)

    def test_oddiy_ishchi_ochira_olmaydi(self):
        self.qosh()
        w = Worker.objects.get(tabel="5001")
        oddiy = ishchi_yarat("3007", ["ishchi"], pin="1111")
        r = self.client.delete(f"/api/v1/workers/{w.id}", **self.kir("3007", "1111"))
        self.assertEqual(r.status_code, 403)
        w.refresh_from_db()
        self.assertFalse(w.deleted)
        self.assertTrue(oddiy.faol)

    def test_faqat_admin_qosha_oladi(self):
        oddiy = ishchi_yarat("3002", ["ishchi"], pin="1111")
        r = self.client.put("/api/v1/workers", {
            "tabel": "5009", "familiya": "X", "ism": "Y",
            "positionId": str(self.pos.id), "roles": ["ishchi"], "faol": True,
        }, content_type="application/json", **self.kir(oddiy.tabel, "1111"))
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Worker.objects.filter(tabel="5009").exists())


class RoyxatdanOtishTest(TestCase):
    """
    Ishchi oʻzi roʻyxatdan oʻtadi: tabel kadrlar bazasi bilan
    solishtiriladi → yuz (ixtiyoriy) → PIN → tizimga kiradi.
    """

    def setUp(self):
        self.depo = Depo.joriy()
        self.pos = Position.objects.create(depo=self.depo, nomi="Slesar", tartib=1)
        # Admin ommaviy import qilgan ishchi — PIN'i ham, yuzi ham yoʻq
        self.yangi = ishchi_yarat("7001", ["ishchi"], self.pos)
        # Allaqachon roʻyxatdan oʻtgan ishchi
        self.eski = ishchi_yarat("7002", ["ishchi"], self.pos, pin="1234")
        self.eski.royxatdan_otgan = timezone.now()
        self.eski.save(update_fields=["royxatdan_otgan"])

    def post(self, yol: str, tana: dict):
        return self.client.post(yol, tana, content_type="application/json")

    # --- /auth/check ---

    def test_check_royxat_kerakligini_aytadi(self):
        r = self.post("/api/v1/auth/check", {"tabel": "7001"})
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertTrue(d["bor"])
        self.assertTrue(d["royxatKerak"])
        self.assertFalse(d["faceBor"])

    def test_check_royxatdan_otganni_ajratadi(self):
        d = self.post("/api/v1/auth/check", {"tabel": "7002"}).json()
        self.assertTrue(d["bor"])
        self.assertFalse(d["royxatKerak"])

    def test_check_yoq_tabel(self):
        d = self.post("/api/v1/auth/check", {"tabel": "0000"}).json()
        self.assertFalse(d["bor"])

    def test_check_toliq_fio_bermaydi(self):
        """Tabel terib toʻliq ismlar roʻyxatini yigʻib boʻlmasligi kerak."""
        d = self.post("/api/v1/auth/check", {"tabel": "7001"}).json()
        self.assertNotIn("Ism", d["fio"])
        self.assertEqual(d["fio"], "Familiya7001 I.")

    # --- /auth/register ---

    def test_royxatdan_otadi_va_kiradi(self):
        r = self.post("/api/v1/auth/register", {"tabel": "7001", "pin": "4321", "frames": []})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("access", r.json())
        self.assertFalse(r.json()["faceSaqlandi"])

        self.yangi.refresh_from_db()
        self.assertIsNotNone(self.yangi.royxatdan_otgan)

        # Endi oddiy kirish ishlaydi
        r = self.post("/api/v1/auth/login", {"tabel": "7001", "pin": "4321"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("access", r.json())

    def test_bazada_yoq_tabel_royxatdan_ota_olmaydi(self):
        """Eng muhim qoida — roʻyxatdan yangi ishchi YARATILMAYDI."""
        r = self.post("/api/v1/auth/register", {"tabel": "9999", "pin": "4321", "frames": []})
        self.assertEqual(r.status_code, 404)
        self.assertFalse(Worker.objects.filter(tabel="9999").exists())

    def test_ikki_marta_royxatdan_otib_bolmaydi(self):
        r = self.post("/api/v1/auth/register", {"tabel": "7002", "pin": "9999", "frames": []})
        self.assertEqual(r.status_code, 409)
        # Eski PIN buzilmagan
        self.eski.refresh_from_db()
        self.assertTrue(self.eski.check_pin("1234"))

    def test_notogri_pin_formati(self):
        r = self.post("/api/v1/auth/register", {"tabel": "7001", "pin": "12", "frames": []})
        self.assertEqual(r.status_code, 400)
        self.yangi.refresh_from_db()
        self.assertIsNone(self.yangi.royxatdan_otgan)

    def test_face_servis_ochiq_bolsa_pin_bilan_otadi(self):
        """Servis sozlanmagan — roʻyxatdan oʻtish toʻxtamasligi kerak."""
        with self.settings(FACE_SERVICE_URL=""):
            r = self.post("/api/v1/auth/register",
                          {"tabel": "7001", "pin": "4321", "frames": ["data:image/jpeg;base64,AAA"]})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.json()["faceSaqlandi"])
        self.assertIn("PIN bilan", r.json()["faceXabar"])

    def test_face_servis_ishlasa_vektor_saqlanadi(self):
        from unittest.mock import patch

        soxta = [0.1] * 512
        with self.settings(FACE_SERVICE_URL="http://face:8000"), \
             patch("core.face.vektor", return_value=soxta):
            r = self.post("/api/v1/auth/register",
                          {"tabel": "7001", "pin": "4321", "frames": ["data:image/jpeg;base64,AAA"]})

        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["faceSaqlandi"])
        self.yangi.refresh_from_db()
        self.assertEqual(self.yangi.face_vector, soxta)

    def test_suratda_yuz_yoq_bolsa_toxtatadi(self):
        from unittest.mock import patch

        from core.face import FaceXato

        with self.settings(FACE_SERVICE_URL="http://face:8000"), \
             patch("core.face.vektor", side_effect=FaceXato("Suratda yuz aniqlanmadi")):
            r = self.post("/api/v1/auth/register",
                          {"tabel": "7001", "pin": "4321", "frames": ["data:image/jpeg;base64,AAA"]})

        self.assertEqual(r.status_code, 400)
        self.yangi.refresh_from_db()
        self.assertIsNone(self.yangi.royxatdan_otgan)


class FaceKirishTest(TestCase):
    """Yuz bilan kirish va PIN'ga qaytish."""

    def setUp(self):
        self.depo = Depo.joriy()
        self.w = ishchi_yarat("7010", ["ishchi"], pin="1234")
        self.w.face_vector = [0.1] * 512
        self.w.royxatdan_otgan = timezone.now()
        self.w.save(update_fields=["face_vector", "royxatdan_otgan"])

    def face(self, tabel="7010", kadr=2):
        return self.client.post(
            "/api/v1/auth/face-login",
            {"tabel": tabel, "frames": ["data:image/jpeg;base64,AAA"] * kadr},
            content_type="application/json",
        )

    def test_mos_kelsa_kiradi(self):
        from unittest.mock import patch

        with self.settings(FACE_SERVICE_URL="http://face:8000"), \
             patch("core.face.tekshir", return_value={"mos": True, "jonli": True, "score": 0.9}):
            r = self.face()
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("access", r.json())

    def test_mos_kelmasa_401(self):
        from unittest.mock import patch

        with self.settings(FACE_SERVICE_URL="http://face:8000"), \
             patch("core.face.tekshir", return_value={"mos": False, "jonli": True, "score": 0.2}):
            r = self.face()
        self.assertEqual(r.status_code, 401)

    def test_jonli_emas_401(self):
        """Ekranga tutilgan surat bilan kirib boʻlmasligi kerak."""
        from unittest.mock import patch

        with self.settings(FACE_SERVICE_URL="http://face:8000"), \
             patch("core.face.tekshir", return_value={"mos": True, "jonli": False, "score": 0.95}):
            r = self.face()
        self.assertEqual(r.status_code, 401)

    def test_servis_ochiq_bolsa_503(self):
        """Frontend 503 ni koʻrib darrov PIN'ga oʻtadi."""
        with self.settings(FACE_SERVICE_URL=""):
            r = self.face()
        self.assertEqual(r.status_code, 503)

    def test_yuzi_yoq_ishchi(self):
        ishchi_yarat("7011", ["ishchi"], pin="1234")
        with self.settings(FACE_SERVICE_URL="http://face:8000"):
            r = self.face(tabel="7011")
        self.assertEqual(r.status_code, 401)

    def test_kam_kadr_rad_etiladi(self):
        r = self.face(kadr=1)
        self.assertEqual(r.status_code, 400)

    def test_haddan_katta_kadr_tashlanadi(self):
        """Mijoz 25 MB surat yuborib serverni bogʻlab qoʻya olmasligi kerak."""
        katta = "data:image/jpeg;base64," + ("A" * 2_100_000)
        r = self.client.post("/api/v1/auth/face-login",
                             {"tabel": "7010", "frames": [katta, katta]},
                             content_type="application/json")
        # Kadrlar tashlab yuborildi → "kamida 2 kadr kerak"
        self.assertEqual(r.status_code, 400)

    def test_tashqi_manzil_qabul_qilinmaydi(self):
        """SSRF: data URL boʻlmagan qiymat servisga uzatilmasligi kerak."""
        r = self.client.post("/api/v1/auth/face-login",
                             {"tabel": "7010",
                              "frames": ["http://169.254.169.254/latest/meta-data",
                                         "file:///etc/passwd"]},
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_admin_face_id_ni_ochira_oladi(self):
        from unittest.mock import patch

        admin = ishchi_yarat("7099", ["admin"], pin="1234")
        d = self.client.post("/api/v1/auth/login", {"tabel": "7099", "pin": "1234"},
                             content_type="application/json").json()

        r = self.client.delete(f"/api/v1/workers/{self.w.id}/face-reset",
                               HTTP_AUTHORIZATION=f"Bearer {d['access']}")
        self.assertEqual(r.status_code, 200, r.content)

        self.w.refresh_from_db()
        self.assertEqual(self.w.face_vector, [])
        self.assertEqual(self.w.face_image, "")

        # Endi yuz bilan kira olmaydi, PIN esa ishlaydi
        with self.settings(FACE_SERVICE_URL="http://face:8000"), \
             patch("core.face.tekshir", return_value={"mos": True, "jonli": True}):
            self.assertEqual(self.face().status_code, 401)
        self.assertEqual(
            self.client.post("/api/v1/auth/login", {"tabel": "7010", "pin": "1234"},
                             content_type="application/json").status_code,
            200,
        )
        self.assertTrue(admin.roles)

    def test_oddiy_ishchi_face_ochira_olmaydi(self):
        oddiy = ishchi_yarat("7098", ["ishchi"], pin="1234")
        d = self.client.post("/api/v1/auth/login", {"tabel": "7098", "pin": "1234"},
                             content_type="application/json").json()
        r = self.client.delete(f"/api/v1/workers/{self.w.id}/face-reset",
                               HTTP_AUTHORIZATION=f"Bearer {d['access']}")
        self.assertEqual(r.status_code, 403)
        self.w.refresh_from_db()
        self.assertEqual(len(self.w.face_vector), 512)
        self.assertTrue(oddiy.faol)

    def test_pin_yoli_har_doim_ishlaydi(self):
        """Yuz ishlamasa ham PIN bilan kirish buzilmasligi kerak."""
        r = self.client.post("/api/v1/auth/login", {"tabel": "7010", "pin": "1234"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("access", r.json())

    def test_face_vector_hech_qachon_chiqmaydi(self):
        """Vektor mijozga yuborilmasligi kerak — faqat bayroq."""
        d = self.client.post("/api/v1/auth/login", {"tabel": "7010", "pin": "1234"},
                             content_type="application/json").json()
        xom = str(d)
        self.assertNotIn("face_vector", xom)
        self.assertNotIn("0.1, 0.1", xom)


class LogicTest(TestCase):
    def test_add_months_oy_oxiri(self):
        import datetime
        # 31-yanvar + 1 oy → 28/29-fevral (oshib ketmasligi kerak)
        self.assertEqual(add_months(datetime.date(2026, 1, 31), 1),
                         datetime.date(2026, 2, 28))
        self.assertEqual(add_months(datetime.date(2026, 12, 15), 1),
                         datetime.date(2027, 1, 15))
        self.assertEqual(add_months(datetime.date(2026, 6, 10), -3),
                         datetime.date(2026, 3, 10))

    def test_resolve_access_ustuvorlik(self):
        from core.permissions import resolve_access

        # Admin doim hamma narsaga ega
        self.assertTrue(resolve_access("admin.users", ["admin"], "u1", {}, False))

        # Ishchi standart holda ombor yoza olmaydi
        self.assertFalse(resolve_access("stock.write", ["ishchi"], "u1", {}, False))

        # Shaxsiy override rol standartidan ustun
        access = {"userOverrides": {"u1": {"stock.write": True}}}
        self.assertTrue(resolve_access("stock.write", ["ishchi"], "u1", access, False))

        # Rol override
        access = {"roleOverrides": {"ishchi": {"stock.write": True}}}
        self.assertTrue(resolve_access("stock.write", ["ishchi"], "u1", access, False))


class XodisaTest(TestCase):
    """Avariya/baxtsiz xodisa xabarini tahrirlash va oʻchirish.

    Qoida: xabarni muallifning oʻzi oʻzgartira oladi, administrator —
    istalganini, boshqalar — hech qaysisini.
    """

    def setUp(self):
        self.yoriqchi = ishchi_yarat("3101", ["yoriqchi"], pin="1111")
        self.yoriqchi2 = ishchi_yarat("3102", ["yoriqchi"], pin="2222")
        self.admin = ishchi_yarat("3103", ["admin"], pin="3333")
        self.ishchi = ishchi_yarat("3104", ["ishchi"], pin="4444")

    def kir(self, tabel: str, pin: str) -> dict:
        d = self.client.post("/api/v1/auth/login", {"tabel": tabel, "pin": pin},
                             content_type="application/json").json()
        return {"HTTP_AUTHORIZATION": f"Bearer {d['access']}"}

    def xodisa_yoz(self, tabel="3101", pin="1111", matn="Avariya matni"):
        r = self.client.post("/api/v1/incidents", {"turi": "avariya", "matn": matn},
                             content_type="application/json", **self.kir(tabel, pin))
        self.assertEqual(r.status_code, 200, r.content)
        from core.models import Incident
        return Incident.objects.latest("sana")

    def test_muallif_tahrirlaydi(self):
        x = self.xodisa_yoz()
        r = self.client.patch(f"/api/v1/incidents/{x.id}", {"matn": "Yangilangan matn"},
                              content_type="application/json", **self.kir("3101", "1111"))
        self.assertEqual(r.status_code, 200, r.content)
        x.refresh_from_db()
        self.assertEqual(x.matn, "Yangilangan matn")

    def test_muallif_ochiradi(self):
        from core.models import Incident
        x = self.xodisa_yoz()
        r = self.client.delete(f"/api/v1/incidents/{x.id}", **self.kir("3101", "1111"))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(Incident.objects.filter(id=x.id).exists())

    def test_begona_yoriqchi_tegolmaydi(self):
        x = self.xodisa_yoz()
        r = self.client.patch(f"/api/v1/incidents/{x.id}", {"matn": "Boshqa odam"},
                              content_type="application/json", **self.kir("3102", "2222"))
        self.assertEqual(r.status_code, 403, r.content)
        x.refresh_from_db()
        self.assertEqual(x.matn, "Avariya matni")

    def test_admin_istalganini_ochiradi(self):
        from core.models import Incident
        x = self.xodisa_yoz()
        r = self.client.delete(f"/api/v1/incidents/{x.id}", **self.kir("3103", "3333"))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(Incident.objects.filter(id=x.id).exists())

    def test_ruxsatsiz_ishchi_tegolmaydi(self):
        x = self.xodisa_yoz()
        r = self.client.delete(f"/api/v1/incidents/{x.id}", **self.kir("3104", "4444"))
        self.assertEqual(r.status_code, 403, r.content)

    def test_bosh_matn_qabul_qilinmaydi(self):
        x = self.xodisa_yoz()
        r = self.client.patch(f"/api/v1/incidents/{x.id}", {"matn": "   "},
                              content_type="application/json", **self.kir("3101", "1111"))
        self.assertEqual(r.status_code, 400, r.content)

    def test_yoq_xodisa_404(self):
        import uuid as _uuid
        r = self.client.delete(f"/api/v1/incidents/{_uuid.uuid4()}", **self.kir("3103", "3333"))
        self.assertEqual(r.status_code, 404, r.content)


class KipYozishTest(TestCase):
    """KIP yozuvi: liniya erkin matn, hamma maydon bazaga tushadi."""

    def setUp(self):
        self.pos = Position.objects.create(
            depo=Depo.joriy(), nomi="Teplovoz mashinisti", tartib=1
        )
        self.mashinist = ishchi_yarat("3201", ["ishchi"], self.pos)
        self.yoriqchi = ishchi_yarat("3202", ["yoriqchi"], pin="1111")

    def kir(self) -> dict:
        d = self.client.post("/api/v1/auth/login", {"tabel": "3202", "pin": "1111"},
                             content_type="application/json").json()
        return {"HTTP_AUTHORIZATION": f"Bearer {d['access']}"}

    def yoz(self, **qoshimcha):
        body = {
            "workerId": str(self.mashinist.id),
            "liniya": "Buxoro — Marokand",
            "sana": today().isoformat(),
            "muddatOy": 6,
        }
        body.update(qoshimcha)
        return self.client.post("/api/v1/kips", body,
                                content_type="application/json", **self.kir())

    def test_hamma_maydon_saqlanadi(self):
        from core.models import Kip

        r = self.yoz()
        self.assertEqual(r.status_code, 200, r.content)

        kip = Kip.objects.get()
        self.assertEqual(kip.liniya, "Buxoro — Marokand")
        self.assertEqual(kip.muddat_oy, 6)
        self.assertEqual(kip.sana, today())
        self.assertEqual(kip.tugash, add_months(today(), 6))
        self.assertEqual(kip.yoriqchi_id, self.yoriqchi.id)
        self.assertTrue(kip.imzo_id, "QR imzo yozilishi kerak")

    def test_yangi_liniya_royxatga_qoshiladi(self):
        from core.models import Line

        self.assertFalse(Line.objects.filter(nomi="Buxoro — Marokand").exists())
        self.assertEqual(self.yoz().status_code, 200)
        self.assertTrue(Line.objects.filter(nomi="Buxoro — Marokand").exists())

        # Ikkinchi marta ayni liniya bilan yozilsa — nusxa koʻpaymaydi
        self.assertEqual(self.yoz().status_code, 200)
        self.assertEqual(Line.objects.filter(nomi="Buxoro — Marokand").count(), 1)

    def test_bosh_liniya_qabul_qilinmaydi(self):
        from core.models import Kip

        r = self.yoz(liniya="   ")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(Kip.objects.count(), 0)

    def test_kip_holatda_qaytadi(self):
        r = self.yoz()
        kips = r.json()["state"]["kips"]
        self.assertEqual(len(kips), 1)
        self.assertEqual(kips[0]["liniya"], "Buxoro — Marokand")
        self.assertEqual(kips[0]["muddatOy"], 6)


class KipTahrirTest(TestCase):
    """KIP yozuvini tahrirlash va oʻchirish."""

    def setUp(self):
        self.pos = Position.objects.create(
            depo=Depo.joriy(), nomi="Elektrovoz mashinisti", tartib=1
        )
        self.mashinist = ishchi_yarat("3301", ["ishchi"], self.pos)
        self.yoriqchi = ishchi_yarat("3302", ["yoriqchi"], pin="1111")
        self.yoriqchi2 = ishchi_yarat("3303", ["yoriqchi"], pin="2222")
        self.admin = ishchi_yarat("3304", ["admin"], pin="3333")

    def kir(self, tabel: str, pin: str) -> dict:
        d = self.client.post("/api/v1/auth/login", {"tabel": tabel, "pin": pin},
                             content_type="application/json").json()
        return {"HTTP_AUTHORIZATION": f"Bearer {d['access']}"}

    def kip_yoz(self):
        from core.models import Kip
        self.client.post("/api/v1/kips", {
            "workerId": str(self.mashinist.id),
            "liniya": "Buxoro — Olot",
            "sana": today().isoformat(),
            "muddatOy": 1,
        }, content_type="application/json", **self.kir("3302", "1111"))
        return Kip.objects.get()

    def test_muallif_tahrirlaydi(self):
        kip = self.kip_yoz()
        eski_imzo = kip.imzo_id

        r = self.client.patch(f"/api/v1/kips/{kip.id}",
                              {"liniya": "Qiziltepa — Buxoro", "muddatOy": 6},
                              content_type="application/json", **self.kir("3302", "1111"))
        self.assertEqual(r.status_code, 200, r.content)

        kip.refresh_from_db()
        self.assertEqual(kip.liniya, "Qiziltepa — Buxoro")
        self.assertEqual(kip.muddat_oy, 6)
        self.assertEqual(kip.tugash, add_months(today(), 6), "tugash qayta hisoblanadi")
        self.assertNotEqual(kip.imzo_id, eski_imzo, "yangi imzo qoʻyiladi")

        from core.models import Signature
        self.assertTrue(Signature.objects.get(id=eski_imzo).bekor, "eski imzo bekor")

    def test_ochirilganda_imzo_bekor_qilinadi(self):
        from core.models import Kip, Signature

        kip = self.kip_yoz()
        imzo_id = kip.imzo_id
        r = self.client.delete(f"/api/v1/kips/{kip.id}", **self.kir("3302", "1111"))
        self.assertEqual(r.status_code, 200, r.content)

        self.assertFalse(Kip.objects.filter(id=kip.id).exists())
        self.assertTrue(Signature.objects.get(id=imzo_id).bekor)

    def test_begona_yoriqchi_tegolmaydi(self):
        kip = self.kip_yoz()
        r = self.client.patch(f"/api/v1/kips/{kip.id}", {"liniya": "Boshqa"},
                              content_type="application/json", **self.kir("3303", "2222"))
        self.assertEqual(r.status_code, 403, r.content)
        kip.refresh_from_db()
        self.assertEqual(kip.liniya, "Buxoro — Olot")

    def test_admin_istalganini_ochiradi(self):
        from core.models import Kip
        kip = self.kip_yoz()
        r = self.client.delete(f"/api/v1/kips/{kip.id}", **self.kir("3304", "3333"))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(Kip.objects.filter(id=kip.id).exists())

    def test_bosh_liniya_qabul_qilinmaydi(self):
        kip = self.kip_yoz()
        r = self.client.patch(f"/api/v1/kips/{kip.id}", {"liniya": "  "},
                              content_type="application/json", **self.kir("3302", "1111"))
        self.assertEqual(r.status_code, 400, r.content)

    def test_tahrirlanganda_yangi_liniya_saqlanadi(self):
        from core.models import Line
        kip = self.kip_yoz()
        self.client.patch(f"/api/v1/kips/{kip.id}", {"liniya": "Marokand — Kogon"},
                          content_type="application/json", **self.kir("3302", "1111"))
        self.assertTrue(Line.objects.filter(nomi="Marokand — Kogon").exists())


# =====================================================================
# Yagona imzo tizimi (core/imzo.py) — karta + hujjat imzosi
# =====================================================================

class ImzoTizimiTest(TestCase):
    def setUp(self):
        from core.models import Depo
        self.depo = Depo.joriy()

    def test_tabel4_normalizatsiya(self):
        from core import imzo
        self.assertEqual(imzo.tabel4("BLD0002051"), "2051")
        self.assertEqual(imzo.tabel4("BLD0000458"), "0458")
        # kolliziya: ikkalasi ham 0003 ga tushadi
        self.assertEqual(imzo.tabel4("BLD0000003"), "0003")
        self.assertEqual(imzo.tabel4("Т6ЦЗ-00003"), "0003")

    def test_parse_card_qr(self):
        from core import imzo
        text = ("Buxoro lokomotiv deposida FIO ning elektron imzosi.\n"
                "Lavozimi: Depo boshlig'i\nID: BLD0005016\nIMZO: 0DE519A3D9FF807F")
        p = imzo.parse_card_qr(text)
        self.assertEqual(p["tabel"], "BLD0005016")
        self.assertEqual(p["imzo"], "0DE519A3D9FF807F")

    def test_card_hmac_barqaror_va_16hex(self):
        from core import imzo
        a = imzo.card_hmac("Depo", "AYUB", "Mashinist", "5016")
        b = imzo.card_hmac("Depo", "AYUB", "Mashinist", "5016")
        self.assertEqual(a, b)              # barqaror
        self.assertEqual(len(a), 16)        # 16 belgi
        self.assertEqual(a, a.upper())      # katta harf
        # boshqa kirish — boshqa imzo
        self.assertNotEqual(a, imzo.card_hmac("Depo", "AYUB", "Mashinist", "5017"))

    def test_verify_card_endpoint(self):
        from core.models import Signature, Worker
        w = ishchi_yarat("5016", ["ishchi"])
        sig = Signature.objects.create(
            doc_type="card_id", doc_id=str(w.id), field="id", user=w,
            hash="0DE519A3D9FF807F", payload={"fio": w.fio, "lavozim": "Depo boshligʻi"},
        )
        w.imzo_id = str(sig.id)
        w.save(update_fields=["imzo_id"])

        # to'g'ri imzo
        r = self.client.get("/api/v1/verify/card?tabel=5016&imzo=0DE519A3D9FF807F")
        self.assertTrue(r.json()["ok"])
        # noto'g'ri imzo
        r = self.client.get("/api/v1/verify/card?tabel=5016&imzo=DEADBEEFDEADBEEF")
        self.assertFalse(r.json()["ok"])
        # to'liq karta ID (BLD…) — oxirgi-4 ga keltiriladi
        r = self.client.get("/api/v1/verify/card?tabel=BLD0005016&imzo=0DE519A3D9FF807F")
        self.assertTrue(r.json()["ok"])

    def test_hujjat_imzo_butunligi(self):
        """doc_hmac bilan yasalgan imzo doc_ok dan o'tadi; buzilsa — o'tmaydi."""
        from core import imzo
        from core.models import Signature
        w = ishchi_yarat("7001", ["tb_xodim"])
        sana = timezone.now().isoformat()
        s = Signature.objects.create(
            doc_type="journal", doc_id="abc", field="07", user=w,
            hash=imzo.doc_hmac("journal", "abc", "07", w.id, sana),
            payload={"sana": sana, "fio": w.fio, "lavozim": ""},
        )
        self.assertTrue(imzo.doc_ok(s))
        # payload ga aralashsak — butunlik buziladi
        s.payload["sana"] = timezone.now().isoformat()
        self.assertFalse(imzo.doc_ok(s))


# =====================================================================
# Kolonnalar — yaratish / biriktirish / ruxsat
# =====================================================================

class KolonnaTest(TestCase):
    def setUp(self):
        Depo.joriy()
        self.admin = ishchi_yarat("10001", ["admin"], pin="1234")
        self.oddiy = ishchi_yarat("2002", ["ishchi"], pin="1111")

    def kir(self, tabel, pin):
        d = self.client.post("/api/v1/auth/login", {"tabel": tabel, "pin": pin},
                             content_type="application/json").json()
        return {"HTTP_AUTHORIZATION": f"Bearer {d['access']}"}

    def test_kolonna_yaratish_va_biriktirish(self):
        from core.models import Kolonna, Worker
        h = self.kir("10001", "1234")
        instr = ishchi_yarat("3101", ["yoriqchi"], pin="1111")

        r = self.client.post("/api/v1/kolonnalar",
            {"nomi": "17-Manyovr", "turi": "manyovr", "instruktorId": str(instr.id)},
            content_type="application/json", **h)
        self.assertEqual(r.status_code, 200)
        kid = r.json()["id"]
        self.assertTrue(Kolonna.objects.filter(id=kid, turi="manyovr").exists())

        # ishchini biriktirish
        r = self.client.post("/api/v1/kolonnalar/assign",
            {"workerId": str(self.oddiy.id), "kolonnaId": kid},
            content_type="application/json", **h)
        self.assertEqual(r.status_code, 200)
        self.oddiy.refresh_from_db()
        self.assertEqual(str(self.oddiy.kolonna_ref_id), kid)

        # koʻchirish (boshqa kolonnaga)
        r2 = self.client.post("/api/v1/kolonnalar",
            {"nomi": "18-Elektrovoz", "turi": "elektrovoz"},
            content_type="application/json", **h)
        kid2 = r2.json()["id"]
        self.client.post("/api/v1/kolonnalar/assign",
            {"workerId": str(self.oddiy.id), "kolonnaId": kid2},
            content_type="application/json", **h)
        self.oddiy.refresh_from_db()
        self.assertEqual(str(self.oddiy.kolonna_ref_id), kid2)

    def test_oddiy_ishchi_kolonna_yarata_olmaydi(self):
        h = self.kir("2002", "1111")
        r = self.client.post("/api/v1/kolonnalar", {"nomi": "X"},
                             content_type="application/json", **h)
        self.assertEqual(r.status_code, 403)

    def test_state_da_kolonnalar_bor(self):
        from core.models import Kolonna
        Kolonna.objects.create(nomi="Test", turi="teplovoz")
        h = self.kir("10001", "1234")
        st = self.client.get("/api/v1/state", **h).json()["data"]
        self.assertIn("kolonnalar", st)
        self.assertTrue(any(k["nomi"] == "Test" for k in st["kolonnalar"]))


# =====================================================================
# Yoʻriqnoma — TNU-19 (depo navbatchisi) oqimi
# =====================================================================

class YoriqnomaTest(TestCase):
    def setUp(self):
        from core.models import Signature
        Depo.joriy()
        self.navbatchi = ishchi_yarat("7001", ["depo_navbatchisi"], pin="1111")
        self.ishchi = ishchi_yarat("5016", ["ishchi"])
        # ishchiga card_id imzosi (skan tekshiruvi uchun)
        sig = Signature.objects.create(
            doc_type="card_id", doc_id=str(self.ishchi.id), field="id", user=self.ishchi,
            hash="0DE519A3D9FF807F", payload={"fio": self.ishchi.fio},
        )
        self.ishchi.imzo_id = str(sig.id)
        self.ishchi.save(update_fields=["imzo_id"])

    def kir(self, tabel, pin):
        dd = self.client.post("/api/v1/auth/login", {"tabel": tabel, "pin": pin},
                              content_type="application/json").json()
        return {"HTTP_AUTHORIZATION": f"Bearer {dd['access']}"}

    def test_skan_smensiz_bloklanadi(self):
        h = self.kir("7001", "1111")
        r = self.client.post("/api/v1/yoriqnoma/skan",
            {"tabel": "5016", "imzo": "0DE519A3D9FF807F"},
            content_type="application/json", **h)
        self.assertEqual(r.status_code, 409)  # smena yoʻq

    def test_toliq_oqim(self):
        from core.models import YoriqnomaYozuv
        h = self.kir("7001", "1111")
        # smena boshlash
        r = self.client.post("/api/v1/yoriqnoma/smena",
            {"tur": "kunduzgi", "mazmun": "Xavfsizlik yoʻriqnomasi", "xulosa": "Oʻtdi"},
            content_type="application/json", **h)
        self.assertEqual(r.status_code, 200)
        # skan — toʻgʻri imzo
        r = self.client.post("/api/v1/yoriqnoma/skan",
            {"tabel": "5016", "imzo": "0DE519A3D9FF807F"},
            content_type="application/json", **h)
        self.assertEqual(r.status_code, 200, r.content)
        yid = r.json()["id"]
        y = YoriqnomaYozuv.objects.get(id=yid)
        self.assertEqual(y.mazmun, "Xavfsizlik yoʻriqnomasi")
        self.assertTrue(y.oluvchi_imzo_id, "ishchi QR imzosi darhol qoʻyilishi kerak")
        self.assertFalse(y.tasdiqlangan)
        # tasdiqlash
        r = self.client.post(f"/api/v1/yoriqnoma/tasdiqla/{yid}", {},
                             content_type="application/json", **h)
        self.assertEqual(r.status_code, 200)
        y.refresh_from_db()
        self.assertTrue(y.tasdiqlangan)
        self.assertTrue(y.beruvchi_imzo_id, "navbatchi QR imzosi qoʻyilishi kerak")

    def test_notogri_imzo_rad(self):
        h = self.kir("7001", "1111")
        self.client.post("/api/v1/yoriqnoma/smena",
            {"tur": "kunduzgi", "mazmun": "m", "xulosa": "x"},
            content_type="application/json", **h)
        r = self.client.post("/api/v1/yoriqnoma/skan",
            {"tabel": "5016", "imzo": "DEADBEEFDEADBEEF"},
            content_type="application/json", **h)
        self.assertEqual(r.status_code, 400)  # karta yaroqsiz

    def test_instruktor_tnu19_ga_yozolmaydi(self):
        # navbatchi bo'lmagan rol (instruktor) TNU-19 ga yozolmaydi
        instr = ishchi_yarat("3101", ["yoriqchi"], pin="2222")
        h2 = self.kir("3101", "2222")
        self.client.post("/api/v1/yoriqnoma/smena",
            {"tur": "kunduzgi"}, content_type="application/json", **h2)
        r = self.client.post("/api/v1/yoriqnoma/skan",
            {"tabel": "5016", "imzo": "0DE519A3D9FF807F"},
            content_type="application/json", **h2)
        self.assertEqual(r.status_code, 403)  # instruktor TNU-19 ga yozolmaydi


# =====================================================================
# Yoʻriqnoma — Yo D-26B (instruktor) oqimi
# =====================================================================

class InstruktorYoriqnomaTest(TestCase):
    def setUp(self):
        from core.models import Signature, Kolonna
        Depo.joriy()
        self.instr = ishchi_yarat("3101", ["yoriqchi"], pin="1111")
        self.kol = Kolonna.objects.create(nomi="17-Manyovr", turi="manyovr", instruktor=self.instr)
        # ishchi shu kolonnada
        self.ishchi = ishchi_yarat("5016", ["ishchi"])
        self.ishchi.kolonna_ref = self.kol
        self.ishchi.save(update_fields=["kolonna_ref"])
        sig = Signature.objects.create(
            doc_type="card_id", doc_id=str(self.ishchi.id), field="id", user=self.ishchi,
            hash="0DE519A3D9FF807F", payload={"fio": self.ishchi.fio},
        )
        self.ishchi.imzo_id = str(sig.id)
        self.ishchi.save(update_fields=["imzo_id"])
        # boshqa kolonna ishchisi
        self.begona = ishchi_yarat("9999", ["ishchi"])
        sig2 = Signature.objects.create(
            doc_type="card_id", doc_id=str(self.begona.id), field="id", user=self.begona,
            hash="AABBCCDDAABBCCDD", payload={},
        )
        self.begona.imzo_id = str(sig2.id)
        self.begona.save(update_fields=["imzo_id"])

    def kir(self, tabel, pin):
        dd = self.client.post("/api/v1/auth/login", {"tabel": tabel, "pin": pin},
                              content_type="application/json").json()
        return {"HTTP_AUTHORIZATION": f"Bearer {dd['access']}"}

    def test_instruktor_toliq_oqim(self):
        from core.models import YoriqnomaYozuv, YoriqnomaVaraq, Kitob
        h = self.kir("3101", "1111")
        # skan — o'z kolonnasi ishchisi
        r = self.client.post("/api/v1/yoriqnoma/skan",
            {"tabel": "5016", "imzo": "0DE519A3D9FF807F", "yoriqTuri": "birlamchi", "mazmun": "Kirish yoʻriqnomasi"},
            content_type="application/json", **h)
        self.assertEqual(r.status_code, 200, r.content)
        yid = r.json()["id"]
        y = YoriqnomaYozuv.objects.get(id=yid)
        self.assertEqual(y.kitob.turi, "instruktor")
        self.assertEqual(y.kitob.kolonna_id, self.kol.id)
        self.assertIsNotNone(y.varaq_id, "ishchi varagʻi ochilishi kerak")
        self.assertTrue(y.oluvchi_imzo_id)
        # tasdiqlash — tur/mazmun bilan
        r = self.client.post(f"/api/v1/yoriqnoma/tasdiqla/{yid}",
            {"yoriqTuri": "davriy", "mazmun": "Yangilangan matn"},
            content_type="application/json", **h)
        self.assertEqual(r.status_code, 200)
        y.refresh_from_db()
        self.assertTrue(y.tasdiqlangan)
        self.assertTrue(y.beruvchi_imzo_id)
        self.assertEqual(y.yoriq_turi, "davriy")
        self.assertEqual(y.mazmun, "Yangilangan matn")

    def test_boshqa_kolonna_bloklanadi(self):
        h = self.kir("3101", "1111")
        r = self.client.post("/api/v1/yoriqnoma/skan",
            {"tabel": "9999", "imzo": "AABBCCDDAABBCCDD"},
            content_type="application/json", **h)
        self.assertEqual(r.status_code, 403)  # boshqa kolonna

    def test_kolonnasiz_instruktor(self):
        from core.models import Kolonna
        Kolonna.objects.filter(instruktor=self.instr).update(faol=False)
        h = self.kir("3101", "1111")
        r = self.client.post("/api/v1/yoriqnoma/skan",
            {"tabel": "5016", "imzo": "0DE519A3D9FF807F"},
            content_type="application/json", **h)
        self.assertIn(r.status_code, (403, 409))


class KitoblarRoyxatiTest(TestCase):
    def setUp(self):
        Depo.joriy()
        self.admin = ishchi_yarat("10001", ["admin"], pin="1234")

    def test_kitoblar_endpoint(self):
        from core.models import Kitob
        Kitob.objects.create(turi="tnu19", raqam=1)
        d = self.client.post("/api/v1/auth/login", {"tabel": "10001", "pin": "1234"},
                             content_type="application/json").json()
        h = {"HTTP_AUTHORIZATION": f"Bearer {d['access']}"}
        r = self.client.get("/api/v1/yoriqnoma/kitoblar", **h)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any(k["turi"] == "tnu19" for k in r.json()["kitoblar"]))


# =====================================================================
# Ishonchli qurilma — telefonda PIN qayta soʻralmasligi
# =====================================================================

# Haqiqiy brauzerlar yuboradigan satrlar.
UA_TELEFON = ("Mozilla/5.0 (Linux; Android 13; SM-A536B) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")
UA_KOMPYUTER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
UA_IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
             "Mobile/15E148 Safari/604.1")


def telefon_sarlavha(qid="qurilma-tel-1", ua=UA_TELEFON, sec="?1"):
    h = {
        "HTTP_USER_AGENT": ua,
        "HTTP_X_QURILMA_ID": qid,
        "HTTP_X_QURILMA_TUR": "mobil",
        "HTTP_X_QURILMA_NOM": "Samsung Chrome",
    }
    if sec:
        h["HTTP_SEC_CH_UA_MOBILE"] = sec
    return h


def kompyuter_sarlavha(qid="qurilma-komp-1"):
    return {
        "HTTP_USER_AGENT": UA_KOMPYUTER,
        "HTTP_X_QURILMA_ID": qid,
        "HTTP_X_QURILMA_TUR": "kompyuter",
        "HTTP_SEC_CH_UA_MOBILE": "?0",
    }


class QurilmaTanishTest(TestCase):
    """Telefon va kompyuter toʻgʻri ajratilishi kerak."""

    def setUp(self):
        Depo.joriy()
        self.w = ishchi_yarat("20001", ["ishchi"], pin="1234")

    def kir(self, **sarlavha):
        return self.client.post("/api/v1/auth/login",
                                {"tabel": "20001", "pin": "1234"},
                                content_type="application/json", **sarlavha)

    def test_telefondan_kirsa_ishonchli(self):
        d = self.kir(**telefon_sarlavha()).json()
        self.assertTrue(d["qurilma"]["mobil"])
        self.assertTrue(d["qurilma"]["ishonchli"])

    def test_iphone_sec_ch_yubormasa_ham_tanildi(self):
        """Safari `Sec-CH-UA-Mobile` yubormaydi — User-Agent yetarli."""
        d = self.kir(**telefon_sarlavha(ua=UA_IPHONE, sec="")).json()
        self.assertTrue(d["qurilma"]["ishonchli"])

    def test_kompyuterdan_kirsa_ishonchsiz(self):
        d = self.kir(**kompyuter_sarlavha()).json()
        self.assertFalse(d["qurilma"]["mobil"])
        self.assertFalse(d["qurilma"]["ishonchli"])

    def test_mijoz_yolgon_aytsa_ishonilmaydi(self):
        """
        Eng muhim tekshiruv: umumiy kompyuter oʻzini «telefonman» deb
        koʻrsatsa ham ishonchli boʻlmasligi kerak — aks holda keyingi
        ishchi oldingisining kabinetiga tushib qolardi.
        """
        h = kompyuter_sarlavha()
        h["HTTP_X_QURILMA_TUR"] = "mobil"
        d = self.kir(**h).json()
        self.assertFalse(d["qurilma"]["ishonchli"])

    def test_eslab_qolma_tanlansa_ishonchsiz(self):
        r = self.client.post("/api/v1/auth/login",
                             {"tabel": "20001", "pin": "1234", "eslabQol": False},
                             content_type="application/json", **telefon_sarlavha())
        self.assertFalse(r.json()["qurilma"]["ishonchli"])

    def test_qurilma_id_yubormagan_eski_mijoz(self):
        """Flutter ilovasi va eski brauzerlar eskicha ishlashda davom etadi."""
        r = self.client.post("/api/v1/auth/login",
                             {"tabel": "20001", "pin": "1234"},
                             content_type="application/json",
                             HTTP_USER_AGENT=UA_TELEFON)
        self.assertEqual(r.status_code, 200)
        self.assertIn("refresh", r.json())
        self.assertEqual(Qurilma.objects.count(), 0)

    def test_telefonga_uzoq_muddat(self):
        """Ishonchli telefon 90 kun, kompyuter esa 30 kun."""
        self.kir(**telefon_sarlavha())
        tel = RefreshToken.objects.order_by("-created_at").first()
        self.kir(**kompyuter_sarlavha())
        komp = RefreshToken.objects.order_by("-created_at").first()

        self.assertGreater((tel.expires_at - timezone.now()).days, 85)
        self.assertLess((komp.expires_at - timezone.now()).days, 35)


class QurilmaRotatsiyaTest(TestCase):
    """Token har yangilanishda almashadi va muddat qaytadan sanaladi."""

    def setUp(self):
        Depo.joriy()
        self.w = ishchi_yarat("20002", ["ishchi"], pin="1234")
        self.d = self.client.post("/api/v1/auth/login",
                                  {"tabel": "20002", "pin": "1234"},
                                  content_type="application/json",
                                  **telefon_sarlavha()).json()

    def yangila(self, refresh, **sarlavha):
        return self.client.post("/api/v1/auth/refresh", {"refresh": refresh},
                                content_type="application/json",
                                **(sarlavha or telefon_sarlavha()))

    def test_yangi_refresh_qaytadi(self):
        r = self.yangila(self.d["refresh"])
        self.assertEqual(r.status_code, 200)
        y = r.json()
        self.assertIn("access", y)
        self.assertIn("refresh", y)
        self.assertNotEqual(y["refresh"], self.d["refresh"])
        # Boot uchun: mijoz alohida /me soʻrovisiz ham foydalanuvchini biladi
        self.assertEqual(y["user"]["tabel"], "20002")

    def test_telefon_qaytganda_pin_soralmaydi(self):
        """
        ENG MUHIM OQIM. Telefon ertasi kuni ochildi: access token allaqachon
        eskirgan, qoʻlda faqat refresh token bor. Ishchi PIN kiritmasdan
        kabinetiga kirishi kerak.
        """
        # 1. Access tokensiz /me — 401. Mijoz aynan shu javobdan keyin
        #    tokenni jimgina yangilaydi (lib/api.ts, so() ichida).
        self.assertEqual(self.client.get("/api/v1/me").status_code, 401)

        # 2. Refresh bilan yangi access olinadi — PIN soʻralmadi
        y = self.yangila(self.d["refresh"]).json()

        # 3. Yangi access bilan kabinet ochiladi
        r = self.client.get("/api/v1/me", HTTP_AUTHORIZATION="Bearer " + y["access"])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["tabel"], "20002")

    def test_eskirgan_access_401_qaytaradi(self):
        """
        Eskirgan token 403 emas, 401 qaytarishi SHART: mijoz faqat 401 da
        yangilashga urinadi. 403 boʻlsa foydalanuvchi chiqib ketardi.
        """
        r = self.client.get("/api/v1/me", HTTP_AUTHORIZATION="Bearer eskirgan.token.xxx")
        self.assertEqual(r.status_code, 401)

    def test_yangi_token_ishlaydi(self):
        y = self.yangila(self.d["refresh"]).json()
        self.assertEqual(self.yangila(y["refresh"]).status_code, 200)

    def test_muddat_qaytadan_sanaladi(self):
        """Har kirishda 90 kun qaytadan boshlanadi — sliding window."""
        eski = RefreshToken.objects.first()
        eski.expires_at = timezone.now() + timedelta(days=3)
        eski.save(update_fields=["expires_at"])

        y = self.yangila(self.d["refresh"]).json()
        yangi = RefreshToken.objects.exclude(pk=eski.pk).order_by("-created_at").first()
        self.assertGreater((yangi.expires_at - timezone.now()).days, 85)
        self.assertTrue(y["qurilma"]["ishonchli"])

    def test_takroriy_sorov_chiqarib_yubormaydi(self):
        """
        Ikki oyna bir vaqtda yangilasa eski token ikki marta keladi.
        Bu hujum emas — foydalanuvchi chiqib ketmasligi kerak.
        """
        self.yangila(self.d["refresh"])
        r = self.yangila(self.d["refresh"])
        self.assertEqual(r.status_code, 200)

    def test_ancha_oldingi_token_qurilmani_yopadi(self):
        """Oʻgʻirlangan nusxa ishlatilsa — qurilma butunlay bekor qilinadi."""
        y = self.yangila(self.d["refresh"]).json()

        RefreshToken.objects.filter(revoked=True).update(
            oxirgi_ishlatilgan=timezone.now() - timedelta(minutes=5)
        )

        r = self.yangila(self.d["refresh"])
        self.assertEqual(r.status_code, 401)

        # Qurilma yopildi — halol egasining yangi tokeni ham endi ishlamaydi
        self.assertEqual(self.yangila(y["refresh"]).status_code, 401)
        self.assertTrue(Qurilma.objects.get().revoked)


class QurilmalarRoyxatTest(TestCase):
    """«Qurilmalarim» — koʻrish va oʻchirish."""

    def setUp(self):
        Depo.joriy()
        self.w = ishchi_yarat("20003", ["ishchi"], pin="1234")
        self.tel = self.client.post("/api/v1/auth/login",
                                    {"tabel": "20003", "pin": "1234"},
                                    content_type="application/json",
                                    **telefon_sarlavha("tel-A")).json()
        self.client.post("/api/v1/auth/login",
                         {"tabel": "20003", "pin": "1234"},
                         content_type="application/json",
                         **telefon_sarlavha("tel-B"))

    def auth(self, d, qid="tel-A"):
        h = telefon_sarlavha(qid)
        h["HTTP_AUTHORIZATION"] = "Bearer " + d["access"]
        return h

    def test_royxat_va_joriy_belgisi(self):
        r = self.client.get("/api/v1/auth/qurilmalar", **self.auth(self.tel))
        self.assertEqual(r.status_code, 200)
        ro = r.json()["qurilmalar"]
        self.assertEqual(len(ro), 2)
        self.assertEqual(sum(1 for q in ro if q["joriy"]), 1)

    def test_ochirilgan_qurilma_chiqib_ketadi(self):
        ro = self.client.get("/api/v1/auth/qurilmalar",
                             **self.auth(self.tel)).json()["qurilmalar"]
        boshqa = next(q for q in ro if not q["joriy"])

        r = self.client.delete("/api/v1/auth/qurilmalar/" + boshqa["id"],
                               **self.auth(self.tel))
        self.assertEqual(r.status_code, 200)

        qoldi = self.client.get("/api/v1/auth/qurilmalar",
                                **self.auth(self.tel)).json()["qurilmalar"]
        self.assertEqual(len(qoldi), 1)

    def test_ozganikini_ochira_olmaydi(self):
        ishchi_yarat("20004", ["ishchi"], pin="1234")
        b = self.client.post("/api/v1/auth/login",
                             {"tabel": "20004", "pin": "1234"},
                             content_type="application/json",
                             **telefon_sarlavha("tel-C")).json()
        meniki = Qurilma.objects.filter(worker=self.w).first()

        r = self.client.delete("/api/v1/auth/qurilmalar/" + str(meniki.id),
                               **self.auth(b, "tel-C"))
        self.assertEqual(r.status_code, 404)
        meniki.refresh_from_db()
        self.assertFalse(meniki.revoked)

    def test_chiqish_qurilmani_ishonchsiz_qiladi(self):
        self.client.post("/api/v1/auth/logout", {"refresh": self.tel["refresh"]},
                         content_type="application/json")
        q = Qurilma.objects.get(worker=self.w, qurilma_id="tel-A")
        self.assertFalse(q.ishonchli)
        self.assertEqual(
            self.client.post("/api/v1/auth/refresh", {"refresh": self.tel["refresh"]},
                             content_type="application/json").status_code, 401)


# =====================================================================
# kip.read.all — nazoratchi hamma KIP'ni koʻradi, lekin tegolmaydi
# =====================================================================

class KipHammaKorishTest(TestCase):
    """
    Admin ruxsatlar jadvalidan bitta shaxsga «Hamma KIP maʼlumotlarini
    koʻrish» ruxsatini beradi. Oʻsha odam barcha kolonnalarni koʻradi,
    ammo hech narsani tahrirlay yoki oʻchira olmaydi.
    """

    def setUp(self):
        depo = Depo.joriy()
        self.pos = Position.objects.create(depo=depo, nomi="Teplovoz mashinisti", tartib=1)

        # Ikkita instruktor, ikkita kolonna, har birida bitta mashinist
        self.yoriqchi_a = ishchi_yarat("3301", ["yoriqchi"], pin="1111")
        self.yoriqchi_b = ishchi_yarat("3302", ["yoriqchi"], pin="2222")

        self.kol_a = Kolonna.objects.create(
            nomi="1-kolonna", turi="teplovoz", instruktor=self.yoriqchi_a, faol=True
        )
        self.kol_b = Kolonna.objects.create(
            nomi="2-kolonna", turi="teplovoz", instruktor=self.yoriqchi_b, faol=True
        )

        self.mash_a = ishchi_yarat("3311", ["ishchi"], self.pos)
        self.mash_a.kolonna_ref = self.kol_a
        self.mash_a.save(update_fields=["kolonna_ref"])

        self.mash_b = ishchi_yarat("3312", ["ishchi"], self.pos)
        self.mash_b.kolonna_ref = self.kol_b
        self.mash_b.save(update_fields=["kolonna_ref"])

        bugun = today()
        self.kip_a = Kip.objects.create(
            worker=self.mash_a, yoriqchi=self.yoriqchi_a,
            liniya="Buxoro — Marokand", sana=bugun,
            muddat_oy=6, tugash=add_months(bugun, 6),
        )
        self.kip_b = Kip.objects.create(
            worker=self.mash_b, yoriqchi=self.yoriqchi_b,
            liniya="Buxoro — Navoiy", sana=bugun,
            muddat_oy=6, tugash=add_months(bugun, 6),
        )

    def kir(self, tabel: str, pin: str) -> dict:
        d = self.client.post("/api/v1/auth/login", {"tabel": tabel, "pin": pin},
                             content_type="application/json").json()
        return {"HTTP_AUTHORIZATION": "Bearer " + d["access"]}

    def kiplar(self, h: dict) -> set:
        r = self.client.get("/api/v1/state", **h)
        self.assertEqual(r.status_code, 200, r.content)
        return {k["id"] for k in r.json()["data"]["kips"]}

    def ruxsat_ber(self, worker, kalit: str, qiymat: bool = True):
        AccessOverride.objects.create(
            scope="user", scope_id=str(worker.id), key=kalit, value=qiymat
        )

    # ---------------- standart holat oʻzgarmagan ----------------

    def test_ruxsatsiz_yoriqchi_faqat_oz_kolonnasini_koradi(self):
        """Standart xatti-harakat buzilmasligi kerak."""
        koradi = self.kiplar(self.kir("3301", "1111"))
        self.assertIn(str(self.kip_a.id), koradi)
        self.assertNotIn(str(self.kip_b.id), koradi)

    # ---------------- yangi ruxsat ----------------

    def test_ruxsat_berilsa_hammasini_koradi(self):
        self.ruxsat_ber(self.yoriqchi_a, "kip.read.all")
        koradi = self.kiplar(self.kir("3301", "1111"))
        self.assertIn(str(self.kip_a.id), koradi)
        self.assertIn(str(self.kip_b.id), koradi)

    def test_ruxsat_faqat_oshanga_tegishli(self):
        """Bir shaxsga berilgan ruxsat boshqa yoʻriqchiga oʻtmaydi."""
        self.ruxsat_ber(self.yoriqchi_a, "kip.read.all")
        koradi = self.kiplar(self.kir("3302", "2222"))
        self.assertNotIn(str(self.kip_a.id), koradi)
        self.assertIn(str(self.kip_b.id), koradi)

    # ---------------- faqat oʻqish ----------------

    def test_ozganikini_tahrirlay_olmaydi(self):
        """ENG MUHIM: koʻrish ruxsati yozish huquqini BERMAYDI."""
        self.ruxsat_ber(self.yoriqchi_a, "kip.read.all")
        h = self.kir("3301", "1111")

        r = self.client.patch("/api/v1/kips/" + str(self.kip_b.id),
                              {"liniya": "oʻzgartirdim"},
                              content_type="application/json", **h)
        self.assertEqual(r.status_code, 403)

        self.kip_b.refresh_from_db()
        self.assertEqual(self.kip_b.liniya, "Buxoro — Navoiy")

    def test_ozganikini_ochira_olmaydi(self):
        self.ruxsat_ber(self.yoriqchi_a, "kip.read.all")
        r = self.client.delete("/api/v1/kips/" + str(self.kip_b.id),
                               **self.kir("3301", "1111"))
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Kip.objects.filter(id=self.kip_b.id).exists())

    def test_yozish_ruxsati_ochirilsa_ozinikiga_ham_tegolmaydi(self):
        """Sof nazoratchi: `kip.write` yopilgan boʻlsa hech narsa qila olmaydi."""
        self.ruxsat_ber(self.yoriqchi_a, "kip.read.all")
        self.ruxsat_ber(self.yoriqchi_a, "kip.write", False)
        r = self.client.delete("/api/v1/kips/" + str(self.kip_a.id),
                               **self.kir("3301", "1111"))
        self.assertEqual(r.status_code, 403)

    # ---------------- olib keladigan ruxsatlar ----------------

    def test_bolim_va_qoshimcha_ruxsatlar_ozi_ochiladi(self):
        """
        Bitta belgi kifoya: KIP boʻlimi menyuda paydo boʻladi va avariya
        tasmasi koʻrinadi. Yozish ruxsatlari esa OCHILMAYDI.
        """
        from core.permissions import worker_can

        self.ruxsat_ber(self.yoriqchi_b, "kip.read.all")
        w = Worker.objects.get(id=self.yoriqchi_b.id)

        self.assertTrue(worker_can(w, "nav.kip", is_feature=True))
        self.assertTrue(worker_can(w, "kip.read"))
        self.assertTrue(worker_can(w, "incident.avariya.read"))

        # Yozish ruxsatlari olib kelinmaydi
        self.ruxsat_ber(self.yoriqchi_b, "kip.write", False)
        self.ruxsat_ber(self.yoriqchi_b, "incident.avariya.write", False)
        w = Worker.objects.get(id=self.yoriqchi_b.id)
        self.assertFalse(worker_can(w, "kip.write"))
        self.assertFalse(worker_can(w, "incident.avariya.write"))

    def test_oddiy_ishchiga_berilsa_ham_ishlaydi(self):
        """Ruxsat yoʻriqchi boʻlmagan odamga ham berilishi mumkin."""
        from core.permissions import worker_can

        nazoratchi = ishchi_yarat("3399", ["ishchi"], pin="3333")
        self.ruxsat_ber(nazoratchi, "kip.read.all")

        koradi = self.kiplar(self.kir("3399", "3333"))
        self.assertIn(str(self.kip_a.id), koradi)
        self.assertIn(str(self.kip_b.id), koradi)

        w = Worker.objects.get(id=nazoratchi.id)
        self.assertTrue(worker_can(w, "nav.kip", is_feature=True))
