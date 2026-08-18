# Backend'ni DigitalOcean Droplet'ga qoʻyish

Frontend Vercel'da qoladi. Droplet'da faqat backend koʻtariladi:

```
Brauzer  →  Vercel (Next.js sahifalar)
                │  /api/v1/*  rewrite
                ▼
         Droplet: Caddy (HTTPS) → Django (gunicorn) → PostgreSQL
```

Kerakli fayllar repo ichida: `Dockerfile`, `docker-compose.yml`, `Caddyfile`,
`docker-entrypoint.sh` (migratsiya + seed avtomatik), `backup.sh`.

---

## Tez yoʻl — bitta buyruq

Droplet yaratilgach (1-bosqich), uning **Web Console** oynasida ikkita
buyruq yozilsa kifoya. Qolgan hamma narsani `dropletga-qoy.sh` bajaradi:
swap, Docker, firewall, kod, kalitlar, HTTPS.

```bash
git clone https://github.com/Xurshid-2004/BacendDepoTb-.git
bash BacendDepoTb-/dropletga-qoy.sh
```

Soʻng 10-bosqichga (Vercel) oʻting. Quyidagi batafsil bosqichlar — nima
sodir boʻlayotganini tushunish va xato chiqqanda tuzatish uchun.

> **Web Console'da nusxa koʻchirmang.** Konsol nusxalashda koʻrinmas
> belgilar qoʻshadi va buyruq `^[[200~curl ...` koʻrinishida buziladi.
> Buyruqlarni qoʻlda yozing, yoki avval `bind 'set enable-bracketed-paste off'`
> deb yozing.

---

## 0. Fayllarni GitHub'ga yuborish (lokal kompyuterda)

Droplet repo'ni GitHub'dan klon qiladi, shuning uchun avval yangi fayllar
yuborilishi kerak:

```powershell
cd "C:\Users\1\Desktop\Tb Main\Bacend"
git add docker-compose.yml Caddyfile .env.production.example backup.sh DEPLOY-DIGITALOCEAN.md .gitignore
git commit -m "DigitalOcean Droplet uchun compose va HTTPS sozlamalari"
git push
```

---

## 1. Droplet yaratish

DigitalOcean panelida: **Create → Droplets**

| Sozlama | Qiymat |
|---|---|
| Image | **Ubuntu 24.04 (LTS) x64** |
| Region | **Frankfurt (FRA1)** — Oʻzbekistonga eng yaqin |
| Type | Basic → Regular SSD |
| Hajm | **1 vCPU / 1 GB RAM / 25 GB** ($6/oy) — swap bilan yetadi |
| Authentication | **SSH Key** (paroldan xavfsizroq) |
| Volumes Block Storage | **Belgilanmasin** — 25 GB yetadi (~10 GB ishlatiladi) |
| Monitoring | **Belgilansin** — bepul, RAM/disk grafiklari va ogohlantirishlar |
| Backups | **Belgilansin** — haftalik, +20% (~$1.20/oy). Butun serverning surati |
| Hostname | `tb-api` |

> **512 MB ($4) variantini tanlamang** — Postgres bilan Django birga
> koʻtarilmaydi, swap ham qutqarmaydi.
>
> 1 GB'da ishlashning sharti ikkita: **3-bosqichdagi swap** va
> `.env.production` da **`WEB_CONCURRENCY=1`**. Ikkalasi ham quyida.
> Ortiqcha bosh ogʻriqsiz yoʻl — $12 (2 GB), unda swap kerak emas.
>
> Keyinchalik FaceID yoqilsa **8 GB** kerak boʻladi (panelda Resize qilinadi,
> maʼlumot yoʻqolmaydi).

Droplet yaratilgach IP manzilini yozib oling, masalan `157.245.10.20`.

---

## 2. Serverga kirish

```powershell
ssh root@157.245.10.20
```

Birinchi kirishda `yes` deb tasdiqlaysiz.

---

## 3. Swap, tizim yangilanishi va Docker

### 3a. Swap — 1 GB droplet uchun MAJBURIY

Serverga kirgach **birinchi** shu bajariladi. Swap boʻlmasa `docker build`
paytida `pip install` RAM'ni toʻldiradi va yadro jarayonni oʻldiradi
(«Killed» yozuvi bilan build yarim yoʻlda toʻxtaydi).

```bash
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

# RAM'dan swap'ga oʻtishni kamaytiramiz — swap faqat zaxira sifatida ishlasin
sysctl vm.swappiness=10
echo 'vm.swappiness=10' >> /etc/sysctl.conf

free -m          # Swap qatorida ~2048 koʻrinishi kerak
```

`/etc/fstab` qatori — server qayta yuklansa swap oʻzi qayta yoqilishi uchun.

> 2 GB (yoki undan katta) droplet olgan boʻlsangiz bu bandni oʻtkazib
> yuborsangiz ham boʻladi. Lekin zarar qilmaydi.

### 3b. Tizim va Docker

```bash
apt update && apt upgrade -y

# Docker rasmiy skripti
curl -fsSL https://get.docker.com | sh

# Tekshirish
docker --version
docker compose version
```

---

## 4. Firewall

Faqat SSH, HTTP va HTTPS ochiq qoladi. Postgres tashqariga umuman
chiqmaydi (compose'da port ochilmagan):

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status
```

---

## 5. Domen (yoki domensiz variant)

**Variant A — domeningiz bor** (masalan `api.tb-depo.uz`):

Domen provayderida **A-yozuv** qoʻshing:

```
api.tb-depo.uz.   A   157.245.10.20
```

Yozuv tarqalishini kuting (5–30 daqiqa), tekshirish:

```bash
dig +short api.tb-depo.uz
```

**Variant B — domen yoʻq:** `sslip.io` xizmati IP'ni domenga aylantiradi va
Let's Encrypt unga sertifikat beradi. Hech narsa sozlash shart emas:

```
157.245.10.20.sslip.io
```

---

## 6. Repo'ni klon qilish

```bash
cd /root
git clone https://github.com/Xurshid-2004/BacendDepoTb-.git
cd BacendDepoTb-
```

---

## 7. Maxfiy qiymatlarni sozlash

Kalitlarni serverning oʻzida yarating (nusxalab yurmaslik uchun):

```bash
python3 -c "import secrets; print('DJANGO_SECRET_KEY=' + secrets.token_urlsafe(64))"
python3 -c "import secrets; print('JWT_SECRET=' + secrets.token_urlsafe(64))"
openssl rand -base64 32          # POSTGRES_PASSWORD
```

Namunadan nusxa olib toʻldiring:

```bash
cp .env.production.example .env.production
nano .env.production
```

Toʻldirilishi shart boʻlgan qatorlar (domen oʻrniga oʻzingiznikini yozing):

```ini
TB_API_DOMAIN=api.tb-depo.uz
DJANGO_SECRET_KEY=<yuqorida yaratilgan>
JWT_SECRET=<yuqorida yaratilgan>
POSTGRES_PASSWORD=<yuqorida yaratilgan>
DJANGO_ALLOWED_HOSTS=api.tb-depo.uz,127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=https://api.tb-depo.uz
CORS_ALLOWED_ORIGINS=https://fronted-depo-tb.vercel.app

# 1 GB droplet uchun — bitta worker (2 boʻlsa ~120 MB ortiqcha ketadi)
WEB_CONCURRENCY=1
```

`nano`da saqlash: `Ctrl+O` → `Enter` → `Ctrl+X`.

> `DJANGO_ALLOWED_HOSTS` ichida `127.0.0.1` **qolishi shart** — konteyner
> healthcheck'i serverni shu manzil orqali tekshiradi.

---

## 8. Ishga tushirish

```bash
docker compose --env-file .env.production up -d --build
```

Birinchi build ~3–5 daqiqa. Keyin loglarni kuzating:

```bash
docker compose logs -f api
```

Koʻrinishi kerak:

```
[tb] Baza tayyor (1-urinish)
[tb] Migratsiyalar...
[tb] Statik fayllar...
[tb] Ishga tushmoqda...
[tb] Boshlangʻich maʼlumot tekshirilmoqda...
[tb] Kadrlar roʻyxati yuklanmoqda...       ← 296 xodim, bir necha daqiqa
[tb] Administrator hisobi tekshirilmoqda (0212)...
[tb] Fon vazifalari tugadi.
```

`Ctrl+C` — loglardan chiqish (server ishlab turaveradi).

---

## 9. Tekshirish

```bash
curl -i https://api.tb-depo.uz/api/v1/health
```

`200 OK` qaytsa backend tayyor. Brauzerdan admin panelni ham oching:
`https://api.tb-depo.uz/admin/`

> Sertifikat 1–2 daqiqada olinadi. Xato boʻlsa: `docker compose logs caddy`
> — koʻpincha sabab DNS hali tarqalmagani yoki 80-port yopiqligi.

---

## 10. Vercel'ni yangi backend'ga ulash

Vercel panelida: **Project → Settings → Environment Variables → Add**

| Nomi | Qiymati | Muhit | Nima uchun |
|---|---|---|---|
| `BACKEND_URL` | `https://api.tb-depo.uz` | Production, Preview, Development | Sahifalardagi `/api/v1/*` soʻrovlari shu manzilga uzatiladi (`next.config.mjs` → `rewrites()`) |
| `DJANGO_URL` | `https://api.tb-depo.uz` | Production, Preview, Development | PDF/DOCX generatori maʼlumotni Django'dan server tomonidan oladi (`app/api/documents/[turi]/[id]/route.ts`) |

**Eski `NEXT_PUBLIC_API_BASE` oʻzgaruvchisi panelda qolgan boʻlsa — oʻchiring.**
U oʻlik Railway manziliga sozlangan va hujjat generatori uni zaxira qiymat
sifatida oʻqiydi.

Soʻng **Deployments → eng yuqoridagisi → ⋯ → Redeploy**.

> Rewrite build vaqtida oʻqiladi — oʻzgaruvchini qoʻshgandan keyin qayta
> deploy qilish **shart**, aks holda soʻrovlar eski Railway manziliga ketaveradi.

Qayta deploy tugagach saytga kiring va tabel raqami bilan login qilib koʻring.
Brauzer *Network* panelida `/api/v1/kirish` soʻrovi `200` qaytishi kerak.

---

## 11. Zaxira nusxa (kundalik)

```bash
cd /root/BacendDepoTb-
chmod +x backup.sh
./backup.sh                       # qoʻlda sinab koʻrish

crontab -e
# fayl oxiriga:
0 3 * * * cd /root/BacendDepoTb- && ./backup.sh >> /var/log/tb-backup.log 2>&1
```

Nusxalar `/root/tb-backup/` da, 14 kun saqlanadi. Serverdan tashqariga
olish (lokal kompyuterda):

```powershell
scp root@157.245.10.20:/root/tb-backup/tb-2026-08-17.sql.gz .
```

Tiklash:

```bash
gunzip -c /root/tb-backup/tb-2026-08-17.sql.gz | \
  docker compose --env-file .env.production exec -T db psql -U tb -d tb
```

---

## Avtomatik yangilanish (push → server oʻzi koʻtaradi)

Vercel frontendni push qilinishi bilan qayta yigʻadi. Droplet'da bunday
narsa yoʻq — lekin bir marta quyidagini bajarsangiz, server ham xuddi
shunday ishlaydi: har 2 daqiqada GitHub tekshiriladi va yangi commit
boʻlsa kod tortib olinib, konteyner qayta yigʻiladi.

```bash
cd /root/BacendDepoTb- && git pull && bash avto-yangila.sh ornat
```

Bu bitta buyruq uch ishni bajaradi: kodni GitHub'dagi oxirgi holatga
keltiradi, konteynerni **shu zahoti** qayta yigʻadi va taymerni yoqadi.
Shundan keyin har push'dan ~2 daqiqa ichida server oʻzi yangilanadi;
migratsiya, kadrlar roʻyxati va admin hisobi entrypoint ichida oʻzi
bajariladi.

| Vazifa | Buyruq |
|---|---|
| Ishlayaptimi | `systemctl status tb-yangila.timer` |
| Soʻnggi loglar | `journalctl -u tb-yangila.service -n 50` |
| Hoziroq tekshirish | `bash /root/BacendDepoTb-/avto-yangila.sh` |
| Majburan qayta yigʻish | `bash /root/BacendDepoTb-/avto-yangila.sh majbur` |
| Vaqtincha toʻxtatish | `systemctl stop tb-yangila.timer` |
| Qayta yoqish | `systemctl start tb-yangila.timer` |

> Skript `git reset --hard origin/main` bajaradi — serverda **qoʻlda
> oʻzgartirilgan kod saqlanmaydi**. `.env.production`, baza volume'i va
> zaxira nusxalar tegilmaydi.

---

## Kundalik buyruqlar

| Vazifa | Buyruq |
|---|---|
| Kodni qoʻlda yangilash | `git pull && docker compose --env-file .env.production up -d --build` |
| Loglar | `docker compose logs -f api` |
| Holat | `docker compose ps` |
| Qayta ishga tushirish | `docker compose --env-file .env.production restart api` |
| Toʻxtatish | `docker compose down` (maʼlumot volume'da qoladi) |
| Django buyrugʻi | `docker compose exec api python manage.py <buyruq>` |
| Baza konsoli | `docker compose exec db psql -U tb -d tb` |
| Disk/xotira | `df -h` va `free -m` |

> `docker compose down -v` — **volume'larni ham oʻchiradi**, yaʼni butun
> baza yoʻqoladi. Faqat toza boshlashni ataylab xohlaganda ishlating.

---

## Disk toʻlib qolmasligi uchun

Yagona real xavf — **eski Docker image'lari**. Har `--build` da yangi image
yaratiladi, eskisi esa nomsiz («dangling») holda diskda qolaveradi. Bir
necha oy eʼtiborsiz qoldirilsa 25 GB toʻlib, server yozishni toʻxtatadi.

Har yangilanishdan keyin bitta buyruq:

```bash
docker system prune -af
```

Ishlatilmayotgan image, konteyner va keshni tozalaydi. **Volume'larga
tegmaydi** — baza xavfsiz (`-a` bor, `--volumes` yoʻq).

Diskni tekshirish:

```bash
df -h /              # umumiy band joy
docker system df     # Docker nimaga qancha sarflagani
```

Buni odat qilish uchun yangilash buyrugʻini shunday yozing:

```bash
git pull && docker compose --env-file .env.production up -d --build && docker system prune -af
```

Kelajakda haqiqatan joy yetmasa — Volume qoʻshish droplet'ni oʻchirmasdan,
istalgan vaqtda mumkin. Shuning uchun uni oldindan olishning hojati yoʻq.

---

## Tez-tez uchraydigan xatolar

| Belgi | Sabab va yechim |
|---|---|
| `DisallowedHost` / 400 | `DJANGO_ALLOWED_HOSTS` ichida domen yoʻq. Qoʻshib `restart api`. |
| Caddy sertifikat ololmayapti | DNS hali tarqalmagan yoki `ufw` 80-portni yopgan. `dig +short <domen>` bilan tekshiring. |
| `unhealthy` konteyner | `DJANGO_ALLOWED_HOSTS` da `127.0.0.1` yoʻq. |
| Build «Killed» deb toʻxtaydi | Swap yoqilmagan (3a-bosqich). `free -m` bilan tekshiring. |
| Server sekin / konteynerlar oʻchib qoladi | `WEB_CONCURRENCY=1` qilinmagan, yoki droplet'ni 2 GB ga Resize qilish vaqti keldi. |
| Vercel'da login ishlamayapti | `BACKEND_URL` qoʻshilgan, lekin Redeploy qilinmagan. |
| PDF/DOCX yuklanmayapti | Vercel'da `DJANGO_URL` yoʻq yoki eski `NEXT_PUBLIC_API_BASE` oʻchirilmagan. |
| Admin panelga kirolmayapti | `CSRF_TRUSTED_ORIGINS` ga `https://<domen>` yozilmagan. |
