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

from django.test import TestCase
from django.utils import timezone

from core.logic import add_months, make_hash, today
from core.models import (
    Card, Depo, Item, Norm, Position, Request, Stock, Talon, Worker,
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
        "incidents", "audit", "lines", "units", "access", "seq",
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
