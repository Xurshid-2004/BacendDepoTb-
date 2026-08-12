# Kadrlar roʻyxati (seed maʼlumot)

`xodimlar.json` — depo xodimlarining roʻyxati (296 ta), `rasmlar/` — ularning
suratlari (`<tabel>.jpg`, 320px, ~2.6 MB).

Bazaga yozish:

```bash
python manage.py import_xodimlar            # qoʻshadi + yangilaydi
python manage.py import_xodimlar --quruq    # faqat koʻrsatadi
python manage.py import_xodimlar --rasmsiz  # suratlarsiz
```

Buyruq **takror ishga tushirishga chidamli**: mavjud tabel raqami yangilanadi,
nusxa yaratilmaydi. PIN'ga va roʻyxatdan oʻtgan xodimning roliga tegilmaydi —
har bir xodim tizimga birinchi kirishda oʻzi PIN yaratadi.

Serverda `build.sh` / `docker-entrypoint.sh` uni avtomatik chaqiradi
(`TB_XODIMLAR=0` qoʻyilsa — oʻtkazib yuboriladi).

## Maydonlar

| Kalit          | Bazadagi joyi        | Misol                                                    |
|----------------|----------------------|----------------------------------------------------------|
| `tabel`        | `Worker.tabel`       | `0002`                                                    |
| `familiya/ism/otasi` | `Worker.*`     | `Umedov` / `Solijon` / `Salimovich`                       |
| `lavozim`      | `Position.nomi`      | `Bosh mexanik`                                            |
| `lavozimToliq` | `Worker.ish_joyi`    | `Bosh mexanik, 3 guruh /16-ITR/`                          |
| `sex`          | `Worker.sex`         | `16-ITR`                                                  |
| `jinsi`        | `Worker.jinsi`       | otasining ismi `-vna` yoki `qizi` boʻlsa — ayol           |
| `rasm`         | `Worker.rasm`        | `0002.jpg` → base64 data URL                              |

`Worker.rasm` — kadrlar boʻlimining rasmiy surati. U `face_image` dan alohida:
xodim Face ID qoʻyganda kameradan olingan kadr `face_image` ga yoziladi, rasmiy
surat esa joyida qoladi. `/api/v1/workers/<id>/face` avval `rasm` ni beradi.

## Manba

Maʼlumot «Xodimlar tabel raqamlari jadvali» (SPA + Taʼmirlash sexi) hujjatidan
olingan: tabel raqami — xodim kodining oxirgi 4 raqami (`BLD0002051` → `2051`).

Suratlar `SPA` va `Taʼmirlash sexi` papkalaridagi fayllardan biriktirilgan
(familiya + ism + otasining ismi boʻyicha). 296 tadan **295** tasiga surat
topilgan; `1052 Raxmatilloyeva Lola Xalimovna` uchun fayl yoʻq.

Biriktirilmagan fayllar (hujjatda ham «aniqlanmagan» deb belgilangan):
`Maxmudov Shavkat` (ikkita mos nom), `Raximov Rustam`, `Tursunova Xosiyat`
(roʻyxatda yoʻq), `Sharopov Shuxrat` (takror — SPA nusxasi olingan).

Rollar lavozim nomiga qarab qoʻyiladi (`import_xodimlar.py` → `ROL_QOIDA`):
depo boshligʻi/oʻrinbosari/bosh muhandis, bosh hisobchi, TB muhandisi,
mashinist yoʻriqchisi, omborchi, katta usta, buxgalter. Qolganlar — `ishchi`.
