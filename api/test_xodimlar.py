"""
Kadrlar roʻyxati importi va yangi xodimning birinchi kirishi.

Tekshiriladigan zanjir:
  import_xodimlar → /auth/check (royxatKerak) → /auth/register (PIN yaratish)
  → /auth/login (tabel + PIN bilan kirish)
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from core.models import Depo, Position, Worker


class ImportTest(TestCase):
    """core/data/xodimlar.json — haqiqiy kadrlar roʻyxati."""

    @classmethod
    def setUpTestData(cls):
        Depo.joriy()
        call_command("import_xodimlar", stdout=StringIO())

    def test_xodimlar_qoshildi(self):
        self.assertGreaterEqual(Worker.objects.count(), 296)

    def test_lavozim_va_sex_toldirildi(self):
        w = Worker.objects.get(tabel="0002")
        self.assertEqual(w.familiya, "Umedov")
        self.assertEqual(w.ism, "Solijon")
        self.assertIsNotNone(w.position)
        self.assertEqual(w.position.nomi, "Bosh mexanik")
        self.assertEqual(w.sex, "16-ITR")
        self.assertIn("Bosh mexanik", w.ish_joyi)

    def test_rasm_saqlandi(self):
        w = Worker.objects.get(tabel="0002")
        self.assertTrue(w.rasm.startswith("data:image/jpeg;base64,"))
        # Face ID kadri emas — u boʻsh boʻlishi kerak
        self.assertEqual(w.face_image, "")

    def test_takror_ishga_tushirish_nusxa_yaratmaydi(self):
        oldin = Worker.objects.count()
        call_command("import_xodimlar", stdout=StringIO())
        self.assertEqual(Worker.objects.count(), oldin)

    def test_lavozimlar_yaratildi(self):
        self.assertGreaterEqual(Position.objects.count(), 60)

    def test_hech_kimda_pin_yoq(self):
        """Import PIN qoʻymaydi — har kim oʻzi yaratadi."""
        self.assertFalse(Worker.objects.exclude(pin_hash="").exists())


class BirinchiKirishTest(TestCase):
    """Tabel raqami → PIN yaratish → keyingi safar tabel + PIN."""

    @classmethod
    def setUpTestData(cls):
        Depo.joriy()
        call_command("import_xodimlar", "--rasmsiz", stdout=StringIO())

    def post(self, yol, **body):
        return self.client.post(f"/api/v1/{yol}", body, content_type="application/json")

    def test_toliq_oqim(self):
        # 1) tabel raqami tekshiriladi — roʻyxatdan oʻtish kerak
        r = self.post("auth/check", tabel="0002")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d["bor"])
        self.assertTrue(d["royxatKerak"])

        # 2) PIN yaratiladi (kamera shart emas — frames boʻsh)
        r = self.post("auth/register", tabel="0002", pin="4271", frames=[])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("access", r.json())

        # 3) endi royxatKerak yoʻq
        self.assertFalse(self.post("auth/check", tabel="0002").json()["royxatKerak"])

        # 4) tabel + PIN bilan kirish
        r = self.post("auth/login", tabel="0002", pin="4271")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["user"]["tabel"], "0002")

        # 5) notoʻgʻri PIN oʻtmaydi
        self.assertNotEqual(self.post("auth/login", tabel="0002", pin="0000").status_code, 200)

    def test_ikki_marta_royxatdan_otib_bolmaydi(self):
        self.post("auth/register", tabel="0003", pin="1111", frames=[])
        r = self.post("auth/register", tabel="0003", pin="2222", frames=[])
        self.assertEqual(r.status_code, 409)

    def test_royxatda_yoq_tabel(self):
        self.assertFalse(self.post("auth/check", tabel="9999").json()["bor"])


class DemoJurnalTest(TestCase):
    """`demo_jurnal` — koʻrsatish uchun namunaviy yozuvlar."""

    @classmethod
    def setUpTestData(cls):
        Depo.joriy()
        call_command("import_xodimlar", "--rasmsiz", stdout=StringIO())
        call_command("demo_jurnal", stdout=StringIO())

    def test_tortta_yozuv(self):
        from core.models import JournalEntry
        self.assertEqual(JournalEntry.objects.filter(bosqich=1).count(), 4)

    def test_komissiya_va_javobgar_toldirilgan(self):
        from core.models import JournalEntry
        for j in JournalEntry.objects.all():
            self.assertGreaterEqual(len(j.komissiya), 1)   # ish beruvchi
            self.assertTrue(j.masul)                        # ish oluvchi
            self.assertTrue(j.masul_lavozim)

    def test_ikkitasi_qr_imzo_bilan_tasdiqlangan(self):
        from core.models import JournalEntry
        imzoli = JournalEntry.objects.filter(bajarildi=True).exclude(imzo=None)
        self.assertEqual(imzoli.count(), 2)
        for j in imzoli:
            self.assertTrue(j.imzo.hash)
            self.assertTrue(j.imzo.payload.get("fio"))

    def test_takror_ishga_tushirish_nusxa_yaratmaydi(self):
        from core.models import JournalEntry
        call_command("demo_jurnal", stdout=StringIO())
        self.assertEqual(JournalEntry.objects.count(), 4)

    def test_tozalash(self):
        from core.models import JournalEntry
        call_command("demo_jurnal", "--tozala", stdout=StringIO())
        self.assertEqual(JournalEntry.objects.count(), 0)
