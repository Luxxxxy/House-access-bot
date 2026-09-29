# Безопасный проход

MVP цифровой системы пропусков для жилого комплекса: MAX Mini App для жильцов, охраны и администратора, FastAPI backend, PostgreSQL и фоновые уведомления через MAX Bot API.

## Назначение

«Безопасный проход» предназначен для оформления и обработки пропусков посетителей в жилом комплексе.

Житель создаёт заявку на посетителя, указывает квартиру, КПП и данные посетителя. Охранник получает заявку в очереди своего действующего КПП, проверяет документы посетителя и разрешает или отклоняет проход. Администратор управляет охранниками, КПП, сменами и реестром жителей.

Основной пользовательский сценарий доступен через MAX Bot и подключённое MAX Mini App.

## Возможности

- Житель связывает MAX-профиль с записью реестра и оформляет заявку на текущую дату для конкретной квартиры и КПП.
- Поддерживаются посетители следующих типов: курьер, гость, рабочий и другой посетитель.
- ФИО посетителя является обязательным полем.
- Номер автомобиля, контакт жителя, предполагаемое время прибытия и комментарий являются дополнительными полями.
- Охранник регистрируется по одноразовому приглашению.
- Администратор проверяет зарегистрированного охранника и назначает ему КПП.
- Очередь заявок доступна охраннику только при наличии действующей смены.
- Поддерживаются повторяющиеся, разовые, ночные и замещающие смены.
- Допускается одновременная работа нескольких охранников на одном КПП во время перекрытия смен.
- Заявки автоматически поступают в очередь после создания.
- Охранник может искать заявки по данным посетителя и автомобиля.
- Охранник не может редактировать заявку.
- Охранник может разрешить проход или отклонить заявку.
- При отклонении можно указать причину.
- Заявку можно закрепить для обработки после смены или перехода через границу даты.
- Обработанные заявки сохраняются в истории в пределах срока хранения.
- Отменённые заявки не участвуют в истории обработки.
- Житель получает уведомление о результате решения охраны.
- Администратор видит пользователей, охранников, жителей, КПП, смены, историю и аудит.
- Реестр жителей импортируется из XLSX с предварительным просмотром изменений.
- Перед применением импорта отображаются результаты проверки файла и количество изменений.
- Демо-режим содержит синтетические профили администратора, охранников и жителей.

## Архитектура

```text
                         MAX
                    ┌─────┴─────┐
                    │           │
                 MAX Bot     Mini App
                    │           │
                    │           ▼
                    │     React + TypeScript
                    │        + Vite + MAX UI
                    │           │
                    └───────────┤
                                ▼
                             FastAPI
                         ┌──────┼──────┐
                         │      │      │
                         ▼      ▼      ▼
                    PostgreSQL Worker  API
                                      │
                                      ▼
                                 MAX Bot API
````

### Компоненты

* `frontend` — интерфейс MAX Mini App.
* `api` — FastAPI backend и бизнес-логика.
* `db` — PostgreSQL.
* `worker` — фоновые задачи, уведомления и очистка данных.
* `bot` — MAX Bot и получение обновлений при использовании Long Polling.

## Структура проекта

```text
app/                    backend и интеграции
frontend/               MAX Mini App
migrations/             миграции базы данных
tests/                  автоматические тесты
docs/                   архитектура и документация API
Dockerfile              Docker-образ приложения
compose.yaml            Docker Compose
.env.example            пример переменных окружения
.dockerignore           исключения для Docker-сборки
.gitignore              исключения Git
README.md               документация проекта
requirements.txt        production-зависимости Python
requirements-dev.txt    зависимости для разработки и тестов
pyproject.toml          конфигурация Python-проекта
alembic.ini             конфигурация Alembic
```

## Локальный запуск через Docker

Требуются Docker и Docker Compose.

Создайте локальный файл окружения:

```powershell
Copy-Item .env.example .env
```

Для запуска всех необходимых локальных компонентов:

```powershell
docker compose --profile max-long-polling up --build -d
```

Проверка состояния:

```powershell
docker compose ps
```

Основные компоненты:

* PostgreSQL;
* FastAPI API;
* worker;
* frontend;
* MAX Bot.

Для демонстрации через MAX необходимо дополнительно настроить токен бота и публичный HTTPS-адрес Mini App.

## Локальные адреса

Frontend:

```text
http://localhost:8080
```

FastAPI:

```text
http://localhost:8000
```

Swagger UI:

```text
http://localhost:8000/api/docs
```

OpenAPI:

```text
http://localhost:8000/api/v1/openapi.json
```

Health:

```text
http://localhost:8000/healthz
```

Readiness:

```text
http://localhost:8000/readyz
```

## Переменные окружения

Основные переменные окружения:

```text
MAX_BOT_TOKEN
MAX_WEBHOOK_SECRET
MAX_UPDATE_MODE
MAX_BOT_NAME

ADMIN_MAX_USER_ID

INITIAL_COMPLEX_NAME
INITIAL_COMPLEX_CITY
TIMEZONE

APP_BASE_URL
MINIAPP_URL

DATABASE_URL
MAX_API_BASE_URL

ENVIRONMENT
DEMO_MODE
DEMO_SEED

CORS_ORIGINS
LOG_LEVEL
```

Пример конфигурации находится в:

```text
.env.example
```

Рабочие токены, пароли, API-ключи и другие секреты в репозитории не хранятся.

## Порты

| Компонент  | Порт | Назначение                     |
| ---------- | ---: | ------------------------------ |
| Frontend   | 8080 | MAX Mini App                   |
| FastAPI    | 8000 | Backend API                    |
| PostgreSQL | 5432 | База данных внутри Docker-сети |

Порт PostgreSQL не требуется публиковать наружу.

## Подключение MAX

Приложение работает как чат-бот с подключённым Mini App.

Для подключения необходимо:

1. Создать чат-бота в MAX.
2. Настроить Mini App.
3. Указать `MAX_BOT_TOKEN`.
4. Указать `MAX_BOT_NAME`.
5. Настроить публичный HTTPS-адрес.
6. Указать `MINIAPP_URL`.
7. Указать `CORS_ORIGINS`.

Mini App внутри MAX должен работать по HTTPS.

## MAX Long Polling

В режиме разработки и демонстрации можно использовать Long Polling.

Пример конфигурации:

```dotenv
ENVIRONMENT=development
MAX_UPDATE_MODE=long_polling
MAX_BOT_TOKEN=<токен тестового бота>
MAX_API_BASE_URL=https://platform-api2.max.ru
```

Если бот ранее был подписан на webhook, отключите существующую подписку:

```powershell
docker compose run --rm api python -m app.integrations.unsubscribe_webhook
```

Запустите полный стек:

```powershell
docker compose --profile max-long-polling up --build -d
```

Просмотр журналов бота:

```powershell
docker compose logs -f bot
```

При использовании Long Polling отдельный входящий webhook для получения обновлений бота не требуется.

Публичный HTTPS для Mini App по-прежнему необходим.

### Остановка Long Polling

```powershell
docker compose stop bot
```

### Переход на webhook

Установите:

```dotenv
MAX_UPDATE_MODE=webhook
```

Пересоздайте API:

```powershell
docker compose up -d --no-deps --force-recreate api
```

Подпишите webhook:

```powershell
docker compose run --rm --no-deps api python -m app.integrations.subscribe_webhook
```

Webhook:

```text
https://<ваш-домен>/api/v1/max/webhook
```

Для отключения webhook:

```powershell
docker compose run --rm api python -m app.integrations.unsubscribe_webhook
```

## Публичный HTTPS для Mini App

MAX Mini App должен быть доступен по публичному HTTPS-адресу.

Публичный адрес указывается в:

```dotenv
MINIAPP_URL=https://<публичный-адрес>
```

Публичный HTTPS может предоставляться reverse proxy, туннелем или другой внешней инфраструктурой.

## MAX API TLS и сертификаты

Для взаимодействия с `platform-api2.max.ru` проект содержит Russian Trusted CA bundle.

Сертификаты находятся в:

```text
app/integrations/max/certs/
```

В проекте используются:

* Russian Trusted Root CA;
* Russian Trusted Sub CA;
* объединённый PEM bundle.

Для запросов к MAX API используется отдельный TLS context с проверкой сертификата сервера и hostname.

Проверка TLS без токена:

```powershell
docker compose --profile max-long-polling run --rm --no-deps bot python -m app.integrations.check_max_tls
```

Команда проверяет установление TLS-соединения с MAX API.

## Основной пользовательский сценарий

### Житель

1. Открывает MAX-бота.
2. Открывает Mini App.
3. Регистрируется как житель.
4. Выбирает квартиру.
5. Выбирает КПП.
6. Выбирает тип посетителя.
7. Указывает ФИО посетителя.
8. При необходимости указывает номер автомобиля.
9. При необходимости указывает контакт, время прибытия и комментарий.
10. Создаёт заявку.

### Охранник

1. Регистрируется по одноразовому приглашению.
2. Администратор проверяет регистрацию.
3. Администратор назначает КПП.
4. При наличии действующей смены охранник получает доступ к очереди.
5. Новая заявка появляется в очереди соответствующего КПП.
6. Охранник открывает заявку.
7. Проверяет данные посетителя и документы.
8. Разрешает проход или отклоняет заявку.
9. При отказе указывает причину.
10. При необходимости закрепляет заявку.

### Администратор

1. Просматривает пользователей.
2. Управляет охранниками.
3. Проверяет заявки на регистрацию охранников.
4. Управляет КПП.
5. Настраивает смены.
6. Просматривает жителей.
7. Импортирует реестр жителей.
8. Просматривает историю.
9. Просматривает аудит.

### Результат

После решения охранника:

1. Заявка получает итоговый статус.
2. Результат доступен жителю.
3. Житель получает уведомление.
4. При отказе жителю передаётся причина отказа.

## Ожидаемое поведение

После создания заявки она должна появиться у действующего охранника соответствующего КПП.

Охранник должен иметь возможность:

* открыть заявку;
* просмотреть её данные;
* проверить посетителя;
* разрешить проход;
* отклонить заявку;
* указать причину отказа;
* закрепить заявку.

Охранник без действующей смены не должен получать новые заявки.

Заявки должны обрабатываться независимо для каждого КПП.

При перекрытии смен заявка должна быть доступна действующим охранникам соответствующего КПП.

После решения охранника житель должен получить результат.

## Тестовые данные

В режиме разработки используется синтетический набор demo-данных.

Список тестовых пользователей:

[docs/test-accounts.md](docs/test-accounts.md)

Тестовые данные предназначены для воспроизводимой проверки MVP и не являются реальными данными жителей.

## Работа с данными

Основное хранилище приложения — PostgreSQL.

Используются данные:

* пользователи;
* роли;
* жилые комплексы;
* квартиры;
* КПП;
* смены;
* заявки посетителей;
* уведомления;
* история обработки;
* аудит действий администратора.

Все временные значения в базе данных хранятся в UTC. Для отображения MVP используется часовой пояс `Europe/Moscow`.

### XLSX-реестр

Импорт реестра жителей выполняется через XLSX.

Основные заголовки:

```text
ФИО
Квартира
Корпус
```

Также распознаются варианты:

```text
ФИО жильца
Номер квартиры
Кв
Строение
```

Ограничения:

* размер файла — до 10 МБ;
* до 20 000 строк.

Перед применением изменений выполняется предварительная проверка файла.

Результат предварительной проверки содержит сведения об изменениях и ошибках.

Неподтверждённый предварительный импорт удаляется через 24 часа.

Отсутствующие строки реестра не отключаются автоматически.

## Retention данных

Обычные необработанные заявки ограничены сроком хранения.

Закреплённые заявки могут сохраняться для продолжения обработки после перехода через границу даты.

Максимальный срок хранения заявки — 14 дней.

Обработанные данные и история хранятся в пределах установленного срока хранения.

Отменённые заявки не сохраняются как элементы истории обработки.

## API

Основные маршруты API используют префикс:

```text
/api/v1
```

### Документация

Swagger UI:

```text
/api/docs
```

OpenAPI:

[docs/openapi.json](docs/openapi.json)

DATA-API:

[docs/DATA-API.yaml](docs/DATA-API.yaml)

Архитектура:

[docs/architecture.md](docs/architecture.md)

Тестовые аккаунты:

[docs/test-accounts.md](docs/test-accounts.md)

### Системные endpoints

```text
GET /healthz
GET /readyz
```

### Аутентификация

```text
GET  /api/v1/auth/me
POST /api/v1/auth/resident/register
POST /api/v1/auth/guard/register
```

### API жителя

```text
GET  /api/v1/resident/apartments
GET  /api/v1/resident/checkpoints

POST /api/v1/visit-requests
GET  /api/v1/visit-requests
GET  /api/v1/visit-requests/{request_id}
POST /api/v1/visit-requests/{request_id}/cancel

GET /api/v1/notifications
```

### API охранника

```text
GET  /api/v1/guards/me
GET  /api/v1/guards/queue
GET  /api/v1/guards/history
GET  /api/v1/guards/{request_id}
POST /api/v1/guards/{request_id}/decision
PUT  /api/v1/guards/{request_id}/pin
```

### API администратора

```text
GET    /api/v1/admin/dashboard

GET    /api/v1/admin/checkpoints
POST   /api/v1/admin/checkpoints

GET    /api/v1/admin/guards
POST   /api/v1/admin/guard-invites
POST   /api/v1/admin/guards/{user_id}/review
PATCH  /api/v1/admin/guards/{user_id}/active

GET    /api/v1/admin/residents
PATCH  /api/v1/admin/residents/{user_id}/active

GET    /api/v1/admin/shifts
POST   /api/v1/admin/shifts
PATCH  /api/v1/admin/shifts/{shift_id}
DELETE /api/v1/admin/shifts/{shift_id}

GET    /api/v1/admin/history
GET    /api/v1/admin/audit

POST   /api/v1/admin/registry/preview
POST   /api/v1/admin/registry/{import_id}/confirm
GET    /api/v1/admin/registry
```

## Пошаговая проверка

### 1. Запуск

```powershell
Copy-Item .env.example .env
docker compose --profile max-long-polling up --build -d
```

Проверить состояние:

```powershell
docker compose ps
```

### 2. Проверка frontend

Открыть:

```text
http://localhost:8080
```

### 3. Проверка API

Открыть:

```text
http://localhost:8000/api/docs
```

### 4. Проверка жителя

Использовать demo-профиль жителя из:

[docs/test-accounts.md](docs/test-accounts.md)

Получить квартиру.

Выбрать КПП.

Создать заявку на посетителя.

### 5. Проверка охранника

Использовать demo-профиль охранника.

Проверить:

* появление заявки в очереди;
* открытие заявки;
* данные посетителя;
* поиск заявки;
* разрешение прохода;
* отклонение заявки с причиной;
* закрепление заявки.

### 6. Проверка результата

Вернуться к профилю жителя.

Проверить:

* изменение статуса заявки;
* получение результата;
* наличие уведомления;
* отображение причины при отказе.

### 7. Проверка администратора

Проверить:

* список охранников;
* проверку регистрации охранника;
* управление КПП;
* управление сменами;
* список жителей;
* историю;
* аудит;
* предварительный просмотр XLSX;
* подтверждение импорта XLSX.

## Проверка собственного API

Основной сценарий API:

```text
RESIDENT
  ↓
GET /api/v1/resident/apartments
  ↓
GET /api/v1/resident/checkpoints
  ↓
POST /api/v1/visit-requests
  ↓
GUARD
  ↓
GET /api/v1/guards/queue
  ↓
GET /api/v1/guards/{request_id}
  ↓
POST /api/v1/guards/{request_id}/decision
  ↓
RESIDENT
  ↓
GET /api/v1/notifications
```

Полная спецификация API:

[docs/openapi.json](docs/openapi.json)

Описание проверок API:

[docs/DATA-API.yaml](docs/DATA-API.yaml)

## Проверка автоматических тестов

После установки зависимостей разработки:

```powershell
python -m pytest
```

Проверка frontend:

```powershell
corepack pnpm --dir frontend install --frozen-lockfile
corepack pnpm --dir frontend build
```

## Разработка без Docker

Требуются:

* Python 3.12+;
* Node.js 22+;
* PostgreSQL либо SQLite.

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
pip install -r requirements.txt -r requirements-dev.txt
```

После настройки `DATABASE_URL` запустите backend:

```powershell
python -m app.web.start
```

Для frontend:

```powershell
cd frontend
corepack pnpm install
corepack pnpm dev
```

Worker:

```powershell
python -m app.jobs.worker
```

## Остановка и повторный запуск

### Остановка полного Docker-стека

```powershell
docker compose --profile max-long-polling down
```

### Повторный запуск

```powershell
docker compose --profile max-long-polling up --build -d
```

### Проверка состояния

```powershell
docker compose ps
```

### Логи API

```powershell
docker compose logs -f api
```

### Логи worker

```powershell
docker compose logs -f worker
```

### Логи MAX Bot

```powershell
docker compose logs -f bot
```

### Логи frontend

```powershell
docker compose logs -f frontend
```

## Известные ограничения

* MVP рассчитан на один демонстрационный жилой комплекс.
* Для демонстрации используются синтетические данные.
* Реестр жителей загружается через XLSX.
* Реальная интеграция с внешней информационной системой реестра жителей не используется.
* Локальная база данных работает в Docker Compose.
* Для работы Mini App внутри MAX требуется публичный HTTPS-адрес.
* В демонстрационном сценарии MAX Bot может работать через Long Polling.
* Production-развёртывание требует отдельной конфигурации безопасности, HTTPS и отдельных учётных данных PostgreSQL.
* Для production необходимо использовать отдельное окружение без demo seed и тестовых пользователей.

## Внешние сервисы и интеграции

Проект использует:

* MAX Bot API;
* MAX Mini App;
* MAX UI;
* MAX Bridge;
* PostgreSQL.

Для работы реального MAX-бота необходим доступ к MAX Bot API.

Для открытия Mini App непосредственно внутри MAX необходим публичный HTTPS-адрес.

## Безопасность

Рабочие:

* токены;
* пароли;
* API-ключи;
* секреты webhook

не должны помещаться в Git-репозиторий.

Для локального окружения используется:

```text
.env
```

Для репозитория используется:

```text
.env.example
```

Рабочий `.env` исключён через `.gitignore`.

Порт PostgreSQL не требуется публиковать наружу.

## Файлы документации

```text
docs/
├── architecture.md
├── openapi.json
├── DATA-API.yaml
└── test-accounts.md
```

## Требования к воспроизводимости

Проект содержит:

```text
Dockerfile
compose.yaml
.dockerignore
.env.example
requirements.txt
requirements-dev.txt
pyproject.toml
frontend/package.json
frontend/pnpm-lock.yaml
migrations/
tests/
docs/
```

Проект должен запускаться по приведённой инструкции без добавления рабочих секретов в исходный код.

Docker-конфигурация предназначена для воспроизводимого локального запуска необходимых компонентов.

## Фиксация версии

Перед сдачей необходимо:

1. Проверить исходный код.
2. Проверить документацию.
3. Проверить Docker-запуск.
4. Проверить основной сценарий в MAX.
5. Создать финальный Git commit.
6. Сохранить полный commit hash.

Получить полный hash:

```powershell
git rev-parse HEAD
```

Git-репозиторий и соответствующий commit hash используются для фиксации переданной версии исходного кода.

## Демонстрационная версия

Основной сценарий:

```text
MAX
↓
открытие Mini App
↓
регистрация или выбор demo-профиля
↓
получение квартиры
↓
выбор КПП
↓
создание заявки на посетителя
↓
получение заявки охранником
↓
проверка заявки
↓
решение охранника
↓
результат и уведомление жителю
```
