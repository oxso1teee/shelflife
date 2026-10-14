# ShelfLife — установка и эксплуатация

Инструкция для того, кто разворачивает и обслуживает ShelfLife на сервере.

## 1. Из чего состоит

| Сервис | Что делает | Код и лицензия |
|---|---|---|
| `web` | сайт, база данных SQLite, вся логика записей, рассылка напоминаний (cron внутри контейнера), внутренний API для бота, Telegram Mini App (`/tma/`) | `web/` — производная версия Wallos, **GPL-3.0** (`web/LICENSE.md`, `web/NOTICE.md`) |
| `bot` | Telegram-бот: привязка, главная, записи с карточками, добавление, «Скоро», расходы, настройки, кнопки под напоминаниями. Своих данных не хранит, всё делает через внутренний API сайта | `bot/` — на основе telegram-reminder-bot, **MIT** (`bot/LICENSE`) |
| `caddy` | HTTPS-вход для сайта: сертификат Let's Encrypt, закрывает внутренний API снаружи | образ `caddy:2.10-alpine` |

Все данные лежат в каталоге `.data/`: база `.data/db/wallos.db` и загруженные логотипы `.data/logos/`.

## 2. Что нужно

- Сервер с Linux, Docker Engine **25 или новее** (нужен для проверки здоровья контейнера) и Docker Compose v2; от 1 ГБ памяти.
- Домен с A-записью на этот сервер; открытые порты 80 и 443.
- Telegram-бот, созданный в [@BotFather](https://t.me/BotFather):
  1. `/newbot` — получите **токен** и **имя** бота (без `@`).
  2. `/setdomain` — выберите бота и укажите домен сайта. Без этого не работает кнопка «Войти через Telegram».
  3. Меню команд и описание бота задавать в BotFather не нужно: бот устанавливает их сам при каждом запуске. Аватар, имя и Mini App настраиваются вручную — см. [branding/telegram/README.md](branding/telegram/README.md).

## 3. Установка

```bash
# каталог проекта, например /opt/shelflife (папки web/, bot/, compose.yaml, Caddyfile, scripts/)
cd /opt/shelflife
cp .env.example .env
chmod 600 .env
openssl rand -hex 32          # вставьте результат в SHELFLIFE_SERVICE_KEY
nano .env                     # TELEGRAM_BOT_TOKEN, TELEGRAM_BOT_USERNAME, SHELFLIFE_DOMAIN, TZ
docker compose --profile proxy up -d --build
docker compose logs -f web    # дождитесь строки "Updated next payment dates"
```

Строка `Updated next payment dates` в логе означает, что миграции базы закончены. Контейнер `web` сообщает Docker «здоров» немного раньше, поэтому сразу после первого запуска подождите эту строку и только потом открывайте сайт.

Переменные `.env`:

| Переменная | Значение |
|---|---|
| `TZ` | часовой пояс сайта, cron и бота, например `Europe/Moscow` |
| `TELEGRAM_BOT_TOKEN` | токен бота из BotFather |
| `TELEGRAM_BOT_USERNAME` | имя бота без `@` (для ссылки привязки и кнопки входа) |
| `SHELFLIFE_SERVICE_KEY` | общий секрет сайта и бота, не короче 32 символов |
| `SHELFLIFE_DOMAIN` | домен сайта |
| `SHELFLIFE_NOTIFY_HOUR` | с какого часа (по `TZ`) отправлять новые напоминания, по умолчанию 9 |
| `WEB_PORT` | локальный порт сайта, доступный только с самого сервера (по умолчанию 8282) |
| `SHELFLIFE_MINIAPP_URL` | необязательно: публичный адрес Mini App, `https://<домен>/tma/index.php` (раздел 13) |

## 4. Первые шаги на сайте

1. Откройте `https://<домен>`. **Первый зарегистрированный пользователь становится администратором.**
2. В настройках администратора (Admin) при необходимости закройте свободную регистрацию и настройте SMTP (нужен для сброса пароля и подтверждения email).
3. Пользователь привязывает Telegram: **Профиль → Telegram-бот → «Привязать Telegram»** → ссылка или QR-код (действует 15 минут, срабатывает один раз). После привязки работают напоминания, `/add` и кнопка «Войти через Telegram» на странице входа.

## 5. Как работают напоминания

- Каждые 5 минут задание `sendtelegram.php` в контейнере `web` ставит в очередь и отправляет напоминания.
- Срок напоминания: дата записи минус «за сколько дней» в записи; если там «по умолчанию», берётся значение из настроек уведомлений аккаунта (по умолчанию 1 день).
- Новые напоминания отправляются с `SHELFLIFE_NOTIFY_HOUR` по местному времени; повторы после сбоев — в любое время.
- Если сервер был выключен в день напоминания, оно уйдёт после запуска. Записи, просроченные больше чем на 3 дня, не напоминаются.
- Каждое напоминание отправляется один раз. При ошибке Telegram: 429 — повтор после указанной паузы; сеть и 5xx — до 5 попыток с нарастающей паузой; 403 (бот заблокирован) и 400 — без повторов.
- Журнал: `docker compose exec web tail -n 50 /var/log/cron/sendtelegram.log`.

## 6. Резервное копирование

```bash
./scripts/backup.sh                       # в ./backups: база + архив логотипов, хранит 14 последних
BACKUP_DIR=/mnt/backup KEEP=30 ./scripts/backup.sh
```

Копия базы снимается штатным механизмом SQLite при работающем сайте и проверяется на целостность. Запуск каждую ночь (`crontab -e` на сервере):

```
0 3 * * * cd /opt/shelflife && ./scripts/backup.sh >> backups/backup.log 2>&1
```

Храните копии и за пределами сервера: в облаке, на другом сервере.

В панели администратора Wallos (Admin → Backup) тоже можно скачать резервную копию.

## 7. Восстановление

```bash
./scripts/restore.sh backups/shelflife-20261014-030000.db backups/shelflife-logos-20261014-030000.tar.gz
```

Скрипт проверяет копию, останавливает сайт и бота, подменяет базу (и логотипы, если указан архив) и запускает сервисы. Если копия сделана старой версией, при запуске применяются новые миграции.

## 8. Обновление

```bash
cd /opt/shelflife
./scripts/backup.sh
git pull                               # репозиторий ShelfLife (web/, bot/ и конфигурация вместе)
docker compose --profile proxy up -d --build
docker compose logs -f web             # дождаться "Updated next payment dates"
```

Исправления безопасности Wallos и бота переносятся из исходных проектов слиянием в свой каталог (история исходных проектов в репозитории сохранена):

```bash
git fetch https://github.com/ellite/Wallos.git main
git merge -X subtree=web FETCH_HEAD    # разрешить конфликты, прогнать тесты (раздел 9)

git fetch https://github.com/AlexDreamien/telegram-reminder-bot.git main
git merge -X subtree=bot FETCH_HEAD
```

## 9. Проверка после изменений

```bash
docker run --rm -v "$PWD/web":/var/www/html:ro -w /var/www/html php:8.3-cli php tests/run.php
cd bot && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt \
  && .venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/black --check .
```

PHP-тесты считают ошибкой любое предупреждение PHP: на сервере оно попадает в ответ API и ломает JSON.

Приёмочный прогон (`scripts/acceptance.py`) и проверка Mini App в браузере (`scripts/tma_ui_check.py`, нужны Playwright и Chrome) работают с базой и **запускаются только на отдельном стенде** — копии проекта с отдельным именем Compose-проекта, портом и пустой `.data/`, с тестовым (ненастоящим) токеном бота:

```bash
mkdir /tmp/shelflife-stand
git ls-files -co --exclude-standard -z | tar --null -T - -cf - | tar -x -C /tmp/shelflife-stand
cd /tmp/shelflife-stand
cat > .env <<'ENV'
COMPOSE_PROJECT_NAME=shelflife-acceptance
WEB_PORT=8285
TZ=Europe/Moscow
TELEGRAM_BOT_USERNAME=ShelfLifeAcceptBot
TELEGRAM_BOT_TOKEN=123456:not-a-real-token
SHELFLIFE_SERVICE_KEY=<openssl rand -hex 32>
ENV
printf 'services:\n  web:\n    image: shelflife-web:acceptance\n' > compose.override.yaml
docker compose up -d --build web
WEB_PORT=8285 /path/to/shelflife/bot/.venv/bin/python scripts/acceptance.py
WEB_PORT=8285 python3 scripts/tma_ui_check.py --out /tmp/tma-shots
docker compose down                     # стенд и его .data/ потом можно удалить
```

## 10. Диагностика

| Симптом | Проверить |
|---|---|
| бот не отвечает | `docker compose logs bot`; правильный ли `TELEGRAM_BOT_TOKEN`; не запущен ли этот бот где-то ещё (Telegram отдаёт обновления только одному экземпляру) |
| бот отвечает «Сервис временно недоступен» | `docker compose logs web`; совпадает ли `SHELFLIFE_SERVICE_KEY` у сайта и бота (оба берут его из `.env`) |
| нет кнопки «Войти через Telegram» | заданы ли `TELEGRAM_BOT_USERNAME` и `TELEGRAM_BOT_TOKEN`; не включён ли режим «только SSO» |
| виджет пишет «Bot domain invalid» | в BotFather `/setdomain` для этого бота не указан домен сайта |
| напоминания не приходят | привязан ли Telegram в профиле; включены ли уведомления в записи; не раньше ли `SHELFLIFE_NOTIFY_HOUR`; журнал `sendtelegram.log` |
| в логе при первом запуске `database table is locked ... 000016.php` | известное безвредное предупреждение исходной миграции Wallos на новой базе; на работу не влияет |
| в боте нет кнопок «Открыть приложение» | задан ли `SHELFLIFE_MINIAPP_URL` и начинается ли он с `https://` (иначе в `docker compose logs bot` будет предупреждение); перезапущен ли бот |
| Mini App: «Telegram не подтвердил вход» | сайт и бот должны использовать один и тот же `TELEGRAM_BOT_TOKEN` (подпись проверяется им) |
| Mini App: «Сессия устарела» | данные запуска старше суток — закрыть и открыть приложение заново |
| Mini App: «Приложение не настроено» | у контейнера `web` не задан `TELEGRAM_BOT_TOKEN` |

## 11. Безопасность

- `.env` содержит токен бота и сервисный ключ: права `600`, в репозитории не хранить. При утечке токена выпустите новый в BotFather (`/revoke`), при утечке ключа сгенерируйте новый `SHELFLIFE_SERVICE_KEY`; затем `docker compose up -d`.
- Сайт публикуется только через Caddy; порт `web` открыт лишь на `127.0.0.1`. Внутренний API (`/api/internal/`) снаружи закрыт, в контейнере доступен только из частной сети Docker и только с сервисным ключом.
- Вход по паролю ограничен: 5 ошибок за 15 минут блокируют имя пользователя на это время. Доступна двухфакторная защита (TOTP) — она действует и при входе через Telegram.
- Журналы доступа не сохраняют параметры запросов (в них может быть API-ключ Wallos).
- Mini App (`/api/tma/app.php`) узнаёт пользователя только по `initData`, подписанным Telegram: сервер проверяет подпись токеном бота (HMAC-SHA256, как в документации Telegram), отклоняет данные старше суток и повторяющиеся поля. `initDataUnsafe` и любые id из тела запроса для входа не используются; cookie не нужны. Telegram-аккаунт без привязки получает только «не привязан». Чужие записи для Mini App не существуют (те же проверки владельца, что у сайта и бота). Каждое изменение несёт `request_id` и применяется один раз. Страница `/tma/` загружает скрипты только с сайта и `telegram.org` (Content-Security-Policy).

## 12. Лицензии

- **Сайт (`web/`) — GPL-3.0**: при передаче копии (в том числе Docker-образа) вместе с ней передаются исходный код, `LICENSE.md` и `NOTICE.md` с перечнем изменений; получатель вправе использовать, изменять и распространять код на условиях GPL-3.0. Исключительные права на сайт целиком передать нельзя: основа принадлежит авторам Wallos. Работа сайта как сервиса для пользователей распространением копии не является.
- **Бот (`bot/`) — MIT**: при копировании сохраняется уведомление об авторских правах из `bot/LICENSE`.
- Лицензии встроенных библиотек перечислены в `web/NOTICE.md`. Условия использования ApexCharts (графики на странице статистики) нужно проверить отдельно перед передачей продукта третьим лицам.
- Юридические вопросы передачи прав согласовываются с юристом.

## 13. Telegram Mini App

Mini App — тот же ShelfLife внутри Telegram: главная, записи с поиском и фильтрами, карточка записи (продлить, напомнить завтра, отменить, вернуть, изменить, удалить), добавление и редактирование, «Скоро», расходы, настройки напоминаний, отвязка. Страница — `web/tma/`, API — `web/api/tma/app.php`, операции — `web/includes/shelflife/webapp_api.php`.

1. Нужен сайт на публичном HTTPS-домене (разделы 2–3). По `http://` и локальному адресу Telegram Mini App не откроет.
2. Проверьте в браузере `https://<домен>/tma/index.php`: должна появиться страница «Откройте ShelfLife в Telegram».
3. В `.env`: `SHELFLIFE_MINIAPP_URL=https://<домен>/tma/index.php`, затем `docker compose up -d bot`.
4. Бот поставит кнопку меню «ShelfLife», а на главной, в помощи и в карточках записей появятся кнопки приложения. Без этой переменной бот работает как прежде, без кнопок приложения, а кнопку меню не меняет.

Аватар, тексты для @BotFather и проверка в настоящем Telegram описаны в [branding/telegram/README.md](branding/telegram/README.md).

