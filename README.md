# OPI Agent

A secure, Git-based agent for Orange Pi devices.

`opi-agent` is a lightweight command-line agent designed for Orange Pi systems with a focus on:

- secure installation
- isolated Python virtual environments
- systemd hardening
- controlled command execution
- service and configuration management
- safe Git-based updates

---

## ویژگی‌ها

- نصب داخل `.venv` به‌جای نصب سراسری
- سرویس systemd با hardening امنیتی
- اجرای محدود و کنترل‌شده‌ی دستورات
- مدیریت نسخه با `git describe`
- به‌روزرسانی امن با `git pull --ff-only`
- بررسی وضعیت مخزن قبل از update
- اعتبارسنجی syntax پایتون و bash
- دستورات داخلی برای:
  - `version`
  - `update`
  - `service`
  - `config`
  - `paths check`

---

## پیش‌نیازها

روی Orange Pi یا سیستم Debian-based به موارد زیر نیاز دارید:

- `git`
- `python3`
- `python3-venv`
- `python3-pip`
- `systemd`

نمونه نصب:
```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip

---

## نصب

### 1) کلون کردن پروژه

bash
sudo git clone https://github.com/dot1mav/opi-agent.git /opt/opi
cd /opt/opi

### 2) اجرای installer

bash
sudo chmod +x install_opi.sh
sudo ./install_opi.sh

Installer یک محیط مجازی اختصاصی می‌سازد و سرویس systemd را با تنظیمات امن آماده می‌کند.

---

## تنظیمات

فایل تنظیمات در مسیر زیر قرار دارد:

bash
/opt/opi/.env

نمونه ساخت فایل:

bash
sudo cp /opt/opi/.env.example /opt/opi/.env
sudo nano /opt/opi/.env
sudo chmod 600 /opt/opi/.env

### نمونه متغیرها

بسته به نسخه پروژه، ممکن است این متغیرها استفاده شوند:

env
OPENAI_API_KEY=your_api_key_here
BOT_TOKEN=your_telegram_bot_token_here
ALLOW_EXEC=0
EXEC_CONFIRM_REQUIRED=1

> توجه: اجرای shell command باید فقط در صورت نیاز و با راهنماید صریح فعال شود.

---

## استفاده

### نمایش راهنما

bash
python3 opi_agent.py --help

### مشاهده نسخه

bash
python3 opi_agent.py version

### مدیریت update

#### بررسی وضعیت update

bash
python3 opi_agent.py update status

#### بررسی update بدون اعمال

bash
python3 opi_agent.py update check

#### اعمال update

bash
python3 opi_agent.py update apply --confirm

> `--confirm` برای جلوگیری از اعمال ناخواسته‌ی تغییرات ضروری است.

---

## مدیریت سرویس

### وضعیت سرویس

bash
sudo systemctl status opi-agent

### start

bash
sudo systemctl start opi-agent

### stop

bash
sudo systemctl stop opi-agent

### restart

bash
sudo systemctl restart opi-agent

### مشاهده لاگ‌ها

bash
sudo journalctl -u opi-agent -f

---

## دستورات داخلی CLI

### `version`
نسخه فعلی پروژه را نمایش می‌دهد.

### `update`
مدیریت امن به‌روزرسانی پروژه:
- `check`
- `status`
- `apply --confirm`

### `service`
مدیریت سرویس:
- `status`
- `start`
- `stop`
- `restart`

### `config`
مدیریت تنظیمات:
- `show`
- `get`
- `set`
- `unset`

### `paths check`
بررسی وضعیت مسیرها، permissionها و mountهای مورد نیاز.

---

## امنیت

این پروژه با هدف کاهش ریسک‌های عملیاتی طراحی شده است:

- استفاده از `.venv` برای ایزوله‌سازی وابستگی‌ها
- اجرای سرویس با user غیر root
- hardening در systemd
- محدودسازی دسترسی به filesystem
- جلوگیری از اجرای shell command مگر با فعال‌سازی صریح
- اعتبارسنجی قبل از update
- استفاده از `git pull --ff-only` برای جلوگیری از merge ناخواسته

### توصیه مهم
اگر قابلیت اجرای command فعال می‌شود، حتماً:
- فقط روی سیستم‌های مورد اعتماد استفاده شود
- دسترسی فایل `.env` محدود باشد
- از اجرای دستورات حساس بدون بررسی انسانی جلوگیری شود

---

## ساختار پروژه

text
opi-agent/
├── README.md
├──i-agent.service.template
├── .env.example├── opi_agent.py
├── opi-agent.service.template
├── .env.example
└── .gitignore

---

## راه‌اندازی از سورس

اگر می‌خواهید از سورس و بدون installer استفاده کنید:

bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
python3 -m py_compile opi_agent.py
bash install_opi.sh

---

## CI/CD

این مخزن می‌تواند با GitHub Actions برای موارد زیر بررسی شود:

- syntax check برای Python
- syntax check برای Bash
- smoke test CLI
- sandbox repo test
- release artifact creation

---

## Release

برای ساخت release:

bash
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin main
git push origin v1.0.0

---

## Troubleshooting

### سرویس بالا نمی‌آید
- لاگ‌ها را با `journalctl` بررسی کنید
- مطمئن شوید `.env` درست ساخته شده است
- دسترسی فایل‌ها و مسیرها را چک کنید

### update fail می‌شود
- وضعیت local changes را بررسی کنید
- مطمئن شوید repo clean است
- اینترنت و remote origin را بررسی کنید

### command execution کار نمی‌کند
- متغیرهای مربوط به exec در `.env` را بررسی کنید
- `--confirm` را فر مربوط به exec در `.env` را بررسی کنید
- `--confirm` را فر Author

dot1mav / OPI Agent project


---

اگر بخواهی، من در قدم بعدی می‌توانم یکی از این دو کار را هم انجام بدهم:

1. **همین README را فارسی‌تر و رسمی‌تر کنم**
2. **نسخه‌ی دو زبانه (FA/EN) برای GitHub بسازم**

اگر خواستی، من نسخه‌ی **نهایی و خیلی شیک‌تر** هم برات می‌نویسم که برای ریپوی عمومی آماده باشد.