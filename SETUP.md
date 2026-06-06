# 🛠️ คู่มือติดตั้ง — TFEX Cashflow Ladder (สำหรับผู้ติดตั้ง)

เอกสารนี้สำหรับ "คนที่ช่วยติดตั้ง" ทำตามทีละขั้น ไม่ต้องเข้าใจโค้ดก็ตั้งได้
แอปนี้เป็น **web app เทรด grid บน TFEX ผ่าน Settrade API** — ล็อกอินด้วย Google,
ผูกหลายบัญชี Settrade ได้ (เก็บแบบเข้ารหัส) แล้วสลับบัญชีได้

> มี 2 วิธี: **วิธี A = Docker (แนะนำ ง่ายสุด)** กับ **วิธี B = รันมือ (สำหรับ dev)**
> เลือกทำอย่างใดอย่างหนึ่งพอ

---

## 0) สิ่งที่ต้องเตรียม

- เครื่อง Linux / Mac / Windows (WSL2) หรือ VPS
- **วิธี A:** ติดตั้ง Docker + Docker Compose
- **วิธี B:** Python 3.10+ และ Node.js 18+
- ค่าที่เจ้าของแอปต้องส่งมาให้ (ดูหัวข้อ 1)

---

## 1) ค่า/ความลับที่ต้องมีก่อนเริ่ม

| ตัวแปร | คืออะไร | ใครเป็นคนหา |
|--------|---------|-------------|
| `SECRET_KEY` | กุญแจเซ็น session (สุ่มยาว ๆ) | ผมแนบให้ด้านล่าง หรือ gen ใหม่ก็ได้ |
| `APP_ENCRYPTION_KEY` | กุญแจเข้ารหัส credential Settrade | ผมแนบให้ด้านล่าง **ห้ามเปลี่ยนหลังเริ่มใช้** |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | สำหรับปุ่ม "Sign in with Google" | สร้างใน Google Cloud Console (หัวข้อ 2) |

> ถ้ายังไม่อยากตั้ง Google ตอนนี้ ก็ข้ามได้ — ตั้ง `ALLOW_DEV_LOGIN=true` ไว้
> จะมีปุ่ม "Continue (dev)" ให้ล็อกอินทดสอบก่อน แล้วค่อยเปิด Google ทีหลัง

ส่วน **credential ของ Settrade (App ID / Secret / Code / Account No / PIN)**
**ไม่ต้องใส่ตอนติดตั้ง** — เจ้าของแอปจะกรอกเองในหน้าเว็บ "Accounts" หลังเปิดใช้งาน

---

## 2) ตั้งค่า Google Sign-In (ข้ามได้ถ้ายังไม่พร้อม)

1. เข้า https://console.cloud.google.com/apis/credentials
2. สร้าง **OAuth client ID** → ชนิด **Web application**
3. ใส่ **Authorised redirect URI** ให้ตรงกับที่จะรัน:
   - Docker (วิธี A): `http://localhost:8080/api/auth/google/callback`
   - รันมือ (วิธี B): `http://localhost:8000/api/auth/google/callback`
   - ถ้าขึ้น VPS/โดเมนจริง: `https://<โดเมน>/api/auth/google/callback`
4. ก๊อป **Client ID** กับ **Client Secret** มาใส่ในไฟล์ `.env` (ขั้นถัดไป)

---

## 3) โหลดโค้ด

```bash
git clone <repo-url> cashflow-bot
cd cashflow-bot
git checkout claude/tfex-grid-trading-bot-GnIIS
```

---

## วิธี A — Docker (แนะนำ) 🐳

### A1. สร้างไฟล์ `.env` ที่ root ของโปรเจกต์

สร้างไฟล์ชื่อ `.env` (อยู่ระดับเดียวกับ `docker-compose.yml`) เนื้อหา:

```ini
SECRET_KEY=<ใส่ค่าที่ได้รับ>
APP_ENCRYPTION_KEY=<ใส่ค่าที่ได้รับ>

# ใส่ถ้าตั้ง Google แล้ว (ไม่ใส่ก็ได้ ถ้าจะใช้ dev login ก่อน)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

OAUTH_REDIRECT_URI=http://localhost:8080/api/auth/google/callback
FRONTEND_URL=http://localhost:8080
ALLOW_DEV_LOGIN=true
```

### A2. รัน

```bash
docker compose up -d --build
```

### A3. เปิดใช้งาน

เปิดเบราว์เซอร์ที่ **http://localhost:8080**

- ดู log: `docker compose logs -f`
- หยุด: `docker compose down`  (ข้อมูลบัญชีอยู่ใน volume `backend-data` ไม่หาย)

---

## วิธี B — รันมือ (สำหรับนักพัฒนา) 💻

### B1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# แก้ไฟล์ backend/.env ใส่ SECRET_KEY, APP_ENCRYPTION_KEY และ Google (ถ้ามี)

uvicorn app.main:app --reload       # backend ขึ้นที่ http://localhost:8000
```

### B2. Frontend (เปิดอีก terminal)

```bash
cd frontend
npm install
npm run dev                         # เปิดที่ http://localhost:5173
```

เปิดเบราว์เซอร์ที่ **http://localhost:5173**
(dev server จะ proxy `/api` ไป backend ให้เอง)

---

## 4) เช็คว่าติดตั้งสำเร็จ

1. เปิดหน้าเว็บแล้วเห็นหน้า **Login** ✅
2. ถ้าตั้ง Google แล้ว → กด "Sign in with Google" เข้าได้
   ถ้ายัง → กด "Continue (dev)" เข้าได้
3. เข้าได้แล้วไปเมนู **Accounts** เห็นฟอร์มผูกบัญชี Settrade ✅
4. เช็ค backend ตรง ๆ: เปิด `http://localhost:8000/api/health`
   (Docker ใช้ `http://localhost:8080/api/health`) ต้องได้ `{"status":"ok",...}`

ติดตั้งเสร็จแค่นี้ — ที่เหลือเจ้าของแอปกรอก credential Settrade เองในหน้า Accounts

---

## 5) ขึ้น production / VPS (ถ้าต้องการ)

- เปิด HTTPS (เช่น Caddy / Nginx ครอบ) แล้วตั้งใน `.env`:
  - `COOKIE_SECURE=true`
  - `OAUTH_REDIRECT_URI=https://<โดเมน>/api/auth/google/callback`
  - `FRONTEND_URL=https://<โดเมน>`
  - `ALLOW_DEV_LOGIN=false`  ← ปิด dev login เมื่อ Google พร้อม
- เพิ่ม redirect URI ของโดเมนจริงใน Google Console ด้วย
- อยากให้ทนกว่า SQLite → ตั้ง `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db`
  (ต้อง `pip install psycopg[binary]` เพิ่มใน backend)

---

## 6) แก้ปัญหาที่เจอบ่อย

| อาการ | สาเหตุ / วิธีแก้ |
|-------|------------------|
| ปุ่ม Google ไม่ขึ้น | ยังไม่ใส่ `GOOGLE_CLIENT_ID/SECRET` — ใช้ dev login ไปก่อน |
| Google เด้ง error `redirect_uri_mismatch` | URI ใน Google Console ไม่ตรงกับ `OAUTH_REDIRECT_URI` เป๊ะ ๆ (รวม http/https และ port) |
| กด Test connect แล้วขึ้น `settrade-v2 not installed` | ปกติ image มีให้แล้ว; ถ้ารันมือให้ `pip install settrade-v2` |
| ผูกบัญชีไว้แล้วจู่ ๆ เชื่อมไม่ได้ | **`APP_ENCRYPTION_KEY` ถูกเปลี่ยน** → ของเก่าถอดรหัสไม่ได้ ต้องผูกบัญชีใหม่ |
| ล็อกอินแล้วเด้งออก / cookie ไม่ติด | ขึ้น HTTPS แต่ลืมตั้ง `COOKIE_SECURE=true` หรือเข้าคนละ origin กับที่ตั้งใน `FRONTEND_URL` |

---

## หมายเหตุความปลอดภัย

- **ห้าม commit ไฟล์ `.env`** ขึ้น git (มี `.gitignore` กันไว้ให้แล้ว)
- `APP_ENCRYPTION_KEY` เก็บให้ดีและสำรองไว้ — หายแล้ว credential ที่ผูกไว้จะใช้ไม่ได้
- App Secret / PIN ของ Settrade ถูกเข้ารหัสก่อนเก็บลง DB และไม่เคยถูกส่งกลับออก API
