# OPI Agent — راهنمای فارسی

ایجنت محافظه‌کارانه برای Orange Pi/سرورهای کوچک: سرویس systemd سخت‌گیرانه، دسترسی
کنترل‌شده به مسیرهای خارجی (مثل هارد اکسترنال)، مدیریت .env از داخل خود ایجنت،
مشاهده لاگ‌ها و تست سلامت سرویس — بدون نیاز به sudo برای کارهای روزمره.

## نصب سریع

```bash
sudo BASE_DIR=/opt/opi-agent \
     OPI_ALLOWED_PATHS="/mnt/usb1:/media/data" \
     OPI_EXTRA_GROUPS="disk,plugdev" \
     bash install_opi.sh
```

نصب‌کننده چه می‌کند:
- کاربر/گروه اختصاصی `opi-agent` می‌سازد (فقط با root).
- venv محلی در `BASE_DIR/.venv` می‌سازد و `openai` و `requests[socks]` را نصب می‌کند.
- دایرکتوری‌های `workspace/`، `run/`، `logs/` را می‌سازد.
- `.env` را (اگر وجود داشته باشد دست نمی‌زند) با کلیدهای پایه می‌سازد و `chmod 600` می‌کند.
- `OPI_EXTRA_GROUPS` اختیاری: کاربر سرویس را به گروه‌های سیستم‌فایل اضافه می‌کند
  (گفایل اضافه می‌کند
  (گروه‌ها باید از قبلدهد).
- `OPI_GRANT_ACL=true` اختیاری: فقط برای مسیرهای داخل `OPI_ALLOWED_PATHS` ACL
  خواندن می‌دهد. **هرگز** mountهای خارجی را chown/chmod نمی‌کند.
- با root یونیت systemd سخت‌گیرانه می‌نویسد، `daemon-reload` و enable می‌کند
  (start خودکار فقط اگر `OPI_API_KEY` تنظیم شده باشد).

## استفاده روزمره (بدون sudo)

```bash
python3 opi_agent.py paths list          # فهرست مسیرهای مجاز + وضعیت دسترسی
python3 opi_agent.py paths check
python3 opi_agent.py config show         # مقادیر .env (مخفی‌سازی اسرار)
python3 opi_agent.py config get OPI_BASE_URL
python3 opi_agent.py config set OPI_BASE_URL http://127.0.0.1:11434/v1
python3 opi_agent.py config set OPI_API_KEY sk-...
python3 opi_agent.py config unset OPI_MODEL
python3 opi_agent.py service health      # فعال بودن سرویس
python3 opi_agent.py service logs --lines 50
python3 opi_agent.py service status | restart | stop | start | reload
python3 opi_agent.py service unit --dry-run   # نمایش/نوشتن قالب یونیت
python3 opi_agent.py ask "سلام!"          # یک پرسش به مدل
python3 opi_agent.py repl                 # چت تعاملی
python3 opi_agent.py daemon               # حلقه سرویس (systemd همین را اجرا می‌کند)
```

نکته: اگر کاربر شما عضو گروه `systemd-journal` باشد، `service logs` و
`service status` بدون sudo کار می‌کنند:
`sudo usermod -aG systemd-journal $USER`

## exec امن

به‌صورت پیش‌فرض غیرفعال است (`OPI_SHELL_ENABLED=false`). برای فعال‌سازی:

```bash
python3 opi_agent.py config set OPI_SHELL_ENABLED true
python3 opi_agent.py config set OPI_ALLOWED_COMMANDS ls,cat,df,du,grep,find
python3 opi_agent.py exec --confirm -- df -h /mnt/usb1
```

محافظت‌ها: بدون `--confirm` اجرا نمی‌شود؛ مسیر مطلق اجرایی ممنوع؛ sudo/su/doas و
شل ممنوع؛ متاکاراکترها، ریدایرکت، پایپ و زنجیره ممنوع؛ دستور باید در
`OPI_ALLOWED_COMMANDS` باشد؛ آرگومان‌های مسیری باید داخل `OPI_ALLOWED_PATHS`
باشند؛ timeout پیش‌فرض ۳۰ ثانیه (`OPI_EXEC_TIMEOUT`).

## متغیرهای .env

| کلید | توضیح |
|---|---|
| `OPI_BASE_DIR` | ریشه پروژه |
| `OPI_ALLOWED_PATHS` | مسیرهای مجاز، جداشده با `:` |
| `OPI_ALLOWED_COMMANDS` | فهرست دستورات مجاز exec، جداشده با `,` |
| `OPI_SHELL_ENABLED` | `false` پیش‌فرض؛ فعال‌سازی exec |
| `OPI_SERVICE_NAME` | نام یونیت systemd |
| `OPI_LOG_DIR` | محل لاگ‌ها |
| `OPI_BASE_URL` / `OPI_API_KEY` / `OPI_MODEL` | تنظیمات کلاینت سازگار با OpenAI |

## امنیت یونیت systemd

`NoNewPrivileges`, `PrivateTmp`, `PrivateDevices`, `ProtectSystem=strict`,
`ProtectHome=read-only`, `RestrictSUIDSGID`, `LockPersonality`, خالی‌کردن
capabiliti‌ها، `ReadWritePaths` فقط برای دایرکتوری‌های runtime و
`ReadOnlyPaths` برای مسیرهای خارجی. قالب: `opi-agent.service.template`.
جزئیات بیشتر در `agent.md`.
