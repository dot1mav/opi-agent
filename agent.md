# معماری و امنیت OPI Agent (سند فنی)

## اجزا

- `install_opi.sh` — نصب‌کننده idempotent، root-optional، با `set -Eeuo pipefail`.
- `opi_agent.py` — ورودی واحد (Python 3.11+، فقط stdlib) با زیرفرمان‌های
  `config`، `paths`، `service`، `exec`، `ask`، `repl`، `daemon`، `cli`، `telegram`، `tui`.
- `opi-agent.service.template` — یونیت systemd سخت‌گیرانه.
- `BASE_DIR/.env` — پیکربندی (chmod 600)، فقط از طریق `config set/unset` نوشته می‌شود.

## جریان داده و مجوزها

1. نصب‌کننده کاربر سیستمی بدون شل (`/usr/sbin/nologin`) به نام `opi-agent` می‌سازد.
2. مالکیت فقط روی `workspace/`، `run/`، `logs/` اعمال می‌شود؛ mountهای خارجی
   هرگز chown/chmod نمی‌شوند.
3. دسترسی نوشتن به هارد اکسترنال فقط از طریق گروه سیستم‌فایل
   (`OPI_EXTRA_GROUPS=disk,plugdev,...`) یا ACL اختیاری
   (`OPI_GRANT_ACL=true`، فقط مسیرهای لیست‌شده) داده می‌شود.
4. در یونیت systemd: `ProtectSystem=strict` کل فایل‌سیستم را فقط‌خواندنی می‌کند؛
   `ReadWritePaths` فقط سه دایرکتوری runtime و `ReadOnlyPaths` مسیرهای خارجی
   را صریح می‌کند. `NoNewPrivileges`، `PrivateTmp`، `PrivateDevices`،
   `RestrictSUIDSGID`، `LockPersonality` و `CapabilityBoundingSet=` (خالی)
   سطح privilege را حداقل می‌کنند.

## مدل تهدید exec

`exec` به‌صورت پیش‌فرض خاموش است (`OPI_SHELL_ENABLED=false`)_ENABLED=false`) و بدون `--confirm`
اجرا نمی‌شوده‌های دفاعی:
- اجرای بدون شل (`subprocess.run` با لیست، بدون `shell=True`).
- رد مسیر مطلق اجرایی؛ اجرایی باید در `PATH` و در `OPI_ALLOWED_COMMANDS` باشد.
- رد `sudo|su|doas|pkexec` و هر شل.
- رد متاکاراکترهای شل، ریدایرکت، پایپ، زنجیره (`;`, `&&`, `||`, `|`, `>`, `<`).
- رد آرگومان‌های مسیری خارج از `OPI_ALLOWED_PATHS`.
- timeout پیش‌فرض ۳۰ ثانیه (`OPI_EXEC_TIMEOUT`).

## مدیریت پیکربندی

`config set/unset` فایل `.env` را خط‌به‌خط بازنویسی می‌کند: کامنت‌ها و خطوط
نامربوط حفظ می‌شوند، نوشتن با فایل موقت + `os.replace` اتمی است و حالت ۶۰۰
تضمین می‌شود. `config show/get` مقادیر کلیدهای حاوی KEY/TOKEN/SECRET/PASSWORD
را ماسک می‌کند. environment واقعی هرگز توسط `.env` بازنویسی نمی‌شود.

## سرویس و مانیتورینگ

- `daemon` حلقه اصلی است؛ pidfile در `run/daemon.pid` با تشخیص pidfile کهنه.
- `service health` از `systemctl is-active`، `service logs` از `journalctl -u`
  (fallback به فایل لاگ محلی در `logs/agent.log`)، بقیه اکشن‌ها مستقیم
  `systemctl` بدون شل. خطاهای Permission denied راهنمای sudo نمایش می‌دهند.
- عضویت در گروه `systemd-journal` امکان مشاهده لاگ بدون sudo را می‌دهد.
- `service unit --dry-run` یونیت جاری را بر اساس env واقعی بازتولید و به‌صورت
  قالب ذخیره می‌کند (بدون هیچ نصب خودکار).

## محدودیت‌های عمدی

- بدون auto-remediation، بدون نوشتن دلخواه خارج از config و لاگ/pid.
- telegram و tui پیاده‌سازی کامل نیستند و به repl برمی‌گردند.
- کلاینت چت با urllib (سازگار با API از نوع [OI]/OpenAI) و بدون وابستگی خارجی.
