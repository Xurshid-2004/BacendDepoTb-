"""Administrator hisobini tayyorlash — `admin_yarat` buyrugʻi."""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from core.models import Depo, Worker


class AdminYaratTest(TestCase):
    def setUp(self):
        Depo.joriy()

    def buyruq(self, *args):
        out = StringIO()
        call_command("admin_yarat", *args, stdout=out)
        return out.getvalue()

    def test_yangi_hisob_pinsiz(self):
        self.buyruq("--tabel", "0212")
        w = Worker.objects.get(tabel="0212")
        self.assertIn("admin", w.roles)
        self.assertTrue(w.is_staff)
        self.assertEqual(w.pin_hash, "")          # birinchi kirishda oʻzi qoʻyadi

    def test_yangi_hisob_pin_bilan(self):
        self.buyruq("--tabel", "0212", "--pin", "1234")
        w = Worker.objects.get(tabel="0212")
        self.assertTrue(w.pin_hash)
        r = self.client.post(
            "/api/v1/auth/login",
            {"tabel": "0212", "pin": "1234"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200, r.content)

    def test_takror_ishga_tushirish_pinni_qaytarmaydi(self):
        """Eng muhimi: deploy administrator PIN'ini eski holga qaytarmasin."""
        self.buyruq("--tabel", "0212", "--pin", "1111")
        w = Worker.objects.get(tabel="0212")
        w.set_pin("9999")                          # admin PIN'ini oʻzgartirdi
        w.save()

        self.buyruq("--tabel", "0212", "--pin", "1111")   # keyingi deploy

        r = self.client.post(
            "/api/v1/auth/login",
            {"tabel": "0212", "pin": "9999"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200, "yangi PIN saqlanib qolishi kerak")
        self.assertEqual(Worker.objects.filter(tabel="0212").count(), 1)

    def test_mavjud_ishchiga_admin_roli_qoshiladi(self):
        Worker.objects.create(
            depo=Depo.joriy(), tabel="0300", familiya="Test", ism="Ism", roles=["ishchi"]
        )
        self.buyruq("--tabel", "0300")
        w = Worker.objects.get(tabel="0300")
        self.assertIn("admin", w.roles)
        self.assertIn("ishchi", w.roles)           # eski roli yoʻqolmaydi

    def test_tabelsiz_hech_narsa_qilmaydi(self):
        chiqish = self.buyruq()
        self.assertIn("oʻtkazib yuborildi", chiqish)
        self.assertEqual(Worker.objects.count(), 0)

    def test_muhit_ozgaruvchisidan_oqiydi(self):
        import os
        os.environ["TB_ADMIN_TABEL"] = "0777"
        try:
            self.buyruq()
            self.assertTrue(Worker.objects.filter(tabel="0777").exists())
        finally:
            os.environ.pop("TB_ADMIN_TABEL", None)
