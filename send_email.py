"""
send_email.py — отправка final_sunburst.html на email через Gmail SMTP.

Использование:
    python send_email.py

Потребует ввести:
    - адрес отправителя (Gmail)
    - пароль приложения (App Password, НЕ обычный пароль)

Как получить App Password:
    1. Войдите в Google-аккаунт
    2. Перейдите: myaccount.google.com/apppasswords
    3. Создайте пароль для приложения "Почта"
    4. Скопируйте 16-символьный код и введите ниже
"""

import smtplib
import getpass
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path

RECIPIENT = "dymkous@gmail.com"
SUBJECT   = "Генеалогическое древо рода Дымковых — Sunburst диаграмма"
BODY      = """\
Добрый день!

Во вложении — интерактивная Sunburst-диаграмма генеалогического древа
рода Дымковых по мужской линии (47 персон, 5 поколений).

Файл открывается в любом браузере (Chrome, Firefox).
Корень: Тимофеев (1800) → Дымков Терентий → ...

--
Сгенерировано автоматически из фотографий семейного архива.
"""

ATTACHMENT = Path(__file__).parent / "output" / "final_sunburst.html"


def main() -> None:
    print("=" * 50)
    print(f"  Отправка письма на: {RECIPIENT}")
    print("=" * 50)

    if not ATTACHMENT.exists():
        print(f"[ОШИБКА] Файл не найден: {ATTACHMENT}")
        print("Сначала запустите: python build_sunburst.py")
        return

    size_mb = ATTACHMENT.stat().st_size / 1_048_576
    print(f"  Вложение: {ATTACHMENT.name} ({size_mb:.1f} MB)\n")

    sender = input("Gmail-адрес отправителя: ").strip()
    if not sender.endswith("@gmail.com"):
        print("[ОШИБКА] Введите адрес @gmail.com")
        return

    password = getpass.getpass("App Password (16 символов, видно не будет): ")
    if not password:
        print("[ОШИБКА] Пароль не введён")
        return

    # Собираем письмо
    msg = MIMEMultipart()
    msg["From"]    = sender
    msg["To"]      = RECIPIENT
    msg["Subject"] = SUBJECT
    msg.attach(MIMEText(BODY, "plain", "utf-8"))

    with open(ATTACHMENT, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        f'attachment; filename="{ATTACHMENT.name}"',
    )
    msg.attach(part)

    # Отправка через Gmail SMTP
    print(f"\n  Подключаюсь к smtp.gmail.com:587 ...")
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, RECIPIENT, msg.as_string())
        print(f"\n[OK] Письмо отправлено на {RECIPIENT}")
    except smtplib.SMTPAuthenticationError:
        print("\n[ОШИБКА] Неверный адрес или пароль приложения.")
        print("  Убедитесь, что используете App Password, не обычный пароль.")
        print("  Создать: myaccount.google.com/apppasswords")
    except smtplib.SMTPException as e:
        print(f"\n[ОШИБКА] Проблема с SMTP: {e}")
    except OSError as e:
        print(f"\n[ОШИБКА] Сеть недоступна: {e}")


if __name__ == "__main__":
    main()
