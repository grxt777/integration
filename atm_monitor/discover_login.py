"""Локальный помощник для подбора рабочего логин-эндпоинта.

Ничего никуда не отправляет, кроме самой платформы monitoring.btech.uz —
логин и пароль берутся из .env и используются ТОЛЬКО на вашей машине.

Запуск:
    1) впишите в .env свои AUTH_USERNAME / AUTH_PASSWORD
    2) python discover_login.py

Скрипт переберёт типовые варианты пути и названий полей, найдёт рабочую
комбинацию и покажет, что прописать в .env (LOGIN_PATH, LOGIN_USERNAME_FIELD,
LOGIN_PASSWORD_FIELD, LOGIN_TOKEN_RESPONSE_FIELD).
"""

import re
import sys
import time

import requests

from atm_monitor.config import settings

_JWT_RE = re.compile(r"^[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}$")

CANDIDATE_PATHS = [
    "/api/auth/login",
    "/api/auth/signin",
    "/api/auth/sign-in",
    "/api/login",
    "/api/user/login",
    "/api/users/login",
    "/api/v1/auth/login",
    "/api/v1/login",
    "/auth/login",
    "/login",
]

# (поле логина, поле пароля)
CANDIDATE_FIELD_SETS = [
    ("email", "password"),
    ("username", "password"),
    ("login", "password"),
]


def find_jwt(node, depth=0):
    if depth > 4:
        return None, None
    if isinstance(node, str) and _JWT_RE.match(node):
        return node, "<root>"
    if isinstance(node, dict):
        for k, v in node.items():
            token, path = find_jwt(v, depth + 1)
            if token:
                return token, f"{k}.{path}" if path != "<root>" else k
    if isinstance(node, list):
        for v in node:
            token, path = find_jwt(v, depth + 1)
            if token:
                return token, path
    return None, None


def main():
    if not settings.AUTH_USERNAME or not settings.AUTH_PASSWORD:
        print("Впишите AUTH_USERNAME и AUTH_PASSWORD в .env перед запуском.")
        sys.exit(1)

    base = settings.API_BASE_URL.rstrip("/")
    found = []

    print(f"Пробуем найти рабочий логин-эндпоинт на {base} ...\n")

    for path in CANDIDATE_PATHS:
        for user_field, pass_field in CANDIDATE_FIELD_SETS:
            url = base + path
            payload = {
                user_field: settings.AUTH_USERNAME,
                pass_field: settings.AUTH_PASSWORD,
            }
            try:
                resp = requests.post(url, json=payload, timeout=10)
            except requests.RequestException as e:
                print(f"  [ERR ] {path:<25} {user_field}/{pass_field:<10} -> {e}")
                continue

            status = resp.status_code
            if status in (404, 405):
                # эндпоинта с таким путём просто нет — не шумим
                continue

            snippet = ""
            token, token_path = None, None
            try:
                data = resp.json()
                token, token_path = find_jwt(data)
                snippet = str(data)[:150]
            except ValueError:
                snippet = resp.text[:150]

            marker = "  [OK  ]" if (status == 200 and token) else "  [....]"
            print(f"{marker} {path:<25} {user_field}/{pass_field:<10} -> HTTP {status} | {snippet}")

            if status == 200 and token:
                found.append((path, user_field, pass_field, token_path))

            time.sleep(0.5)  # не долбим сервер слишком часто

    print()
    if not found:
        print(
            "Автоподбор не нашёл рабочую комбинацию по типовым вариантам.\n"
            "Откройте DevTools → Network → Fetch/XHR, нажмите Login на странице\n"
            "https://monitoring.btech.uz/#/auth/login и найдите реальный путь и\n"
            "поля запроса вручную — впишите их в .env (LOGIN_PATH, LOGIN_USERNAME_FIELD,\n"
            "LOGIN_PASSWORD_FIELD)."
        )
        sys.exit(1)

    path, user_field, pass_field, token_path = found[0]
    print("Нашли рабочую комбинацию! Впишите в .env:\n")
    print(f"LOGIN_PATH={path}")
    print(f"LOGIN_USERNAME_FIELD={user_field}")
    print(f"LOGIN_PASSWORD_FIELD={pass_field}")
    print(
        f"# токен найден в ответе по пути '{token_path}' — если это не просто "
        f"'token'/'accessToken', TokenManager всё равно найдёт его автопоиском, "
        f"можно оставить LOGIN_TOKEN_RESPONSE_FIELD как есть."
    )


if __name__ == "__main__":
    main()
