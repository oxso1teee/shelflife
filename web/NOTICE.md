# ShelfLife (web) — notices

ShelfLife web is a modified version of **Wallos** (https://github.com/ellite/Wallos),
copyright © Miguel Ribeiro and the Wallos contributors.

Wallos and this modified version are licensed under the **GNU General Public
License, version 3** — see `LICENSE.md`. This modified version is likewise
released under GPL-3.0; the complete corresponding source code is provided
together with every copy of the program, including Docker images.

## Modifications (GPL-3.0 §5a)

Base revision: Wallos `cc9677a` (release 5.8.3, 2026-10-01).

| Date | Change |
|---|---|
| 2026-10-13 | Ship `LICENSE.md` and `NOTICE.md` inside the Docker image (`.dockerignore`). |
| 2026-10-13 | Record kinds (subscription, shelf-life, maintenance), anchor day and snooze date on records (`migrations/000060.php`). |
| 2026-10-13 | One shared module for validating and writing records and for date arithmetic (`includes/shelflife/`); the web form (`endpoints/subscription/add.php`), the API (`api/subscriptions/set_subscriptions.php`), manual renewal (`endpoints/subscription/renew.php`) and the nightly job (`endpoints/cronjobs/updatenextpayment.php`) use it. The API accepts one-time records and the `kind` field. |
| 2026-10-13 | Password guessing limit on the login form: 5 failures per username in 15 minutes (`login.php`, `includes/shelflife/login_throttle.php`, `migrations/000061.php`). |
| 2026-10-13 | Linking an account to the ShelfLife Telegram bot: one-time link tokens on the profile page with a t.me link and QR code (`profile.php`, `scripts/telegram_link.js`, `endpoints/telegram/`), the bot's internal API with a shared service key (`api/internal/telegram/`, `includes/shelflife/internal_api.php`, `includes/shelflife/telegram_link.php`, `nginx.default.conf`), `migrations/000062.php`; account deletion also removes link tokens (`endpoints/settings/deleteaccount.php`, `endpoints/admin/deleteuser.php`). |
| 2026-10-13 | Bot actions on records through the internal API: create from `/add`, renew, cancel and snooze, each applied once per Telegram update (`api/internal/telegram/item_add.php`, `item_action.php`, `includes/shelflife/bot_actions.php`, cancel/snooze in `includes/shelflife/subscription_service.php`, `migrations/000063.php`). |
| 2026-10-13 | Telegram reminders through the ShelfLife bot, one message per record with "renewed", "cancelled" and "remind me later" buttons, from an outbox that is planned idempotently, catches up after downtime and retries by Telegram's answer (`endpoints/cronjobs/sendtelegram.php`, `cronjobs`, `includes/shelflife/notifications.php`, `includes/shelflife/telegram_api.php`, `migrations/000064.php`). Wallos's per-user Telegram channel is skipped for accounts linked to the ShelfLife bot (`endpoints/cronjobs/sendnotifications.php`); account deletion also removes queued reminders. |
| 2026-10-14 | Three record kinds in the web interface: a kind selector in the form with kind-specific date labels, reminders kept for one-time shelf-life dates (`subscriptions.php`, `scripts/subscriptions.js`); green / yellow / red status and days left in the list and an "active records" list on the dashboard (`includes/list_subscriptions.php`, `endpoints/subscriptions/get.php`, `index.php`, `styles/styles.css`); spending statistics and the monthly total count paid subscriptions only (`includes/stats_calculations.php`); the edit form receives the kind (`endpoints/subscription/get.php`); translations (`includes/i18n/en.php`, `ru.php`). |
| 2026-10-14 | Sign in with the Telegram Login Widget for accounts linked to Telegram (`telegram_login.php`, `includes/shelflife/telegram_auth.php`, widget and error messages in `login.php`, `styles/login.css`); the steps after a correct password moved unchanged into `includes/shelflife/session.php`, used by both sign-in paths. |
| 2026-10-13 | The nginx access log no longer records query strings, which can carry the API key (`nginx.conf`). |
| 2026-10-13 | Monthly and yearly dates keep their day of month instead of overflowing (31 January + 1 month is 28/29 February, not 3 March) in `calendar.php`, `includes/stats_extra_calculations.php` and `scripts/subscriptions.js`. |
| 2026-10-14 | ShelfLife branding of the user interface: new logo (`images/siteicons/svg/logo.php`, `images/siteicons/shelflife.png`, `shelflifewhite.png`), favicon and app icons (`images/icon/`), page titles, sign-in pages and header (`login.php`, `registration.php`, `passwordreset.php`, `totp.php`, `verifyemail.php`, `includes/header.php`, `styles/styles.css`, `styles/login.css`), PWA manifest and service worker (`manifest.php`, `service-worker.php`), e-mail and notification texts (`endpoints/cronjobs/send*.php`, `endpoints/notifications/test*.php`), 2FA issuer, backup and calendar names (`endpoints/user/enable_totp.php`, `endpoints/db/backup.php`, `scripts/admin.js`, `scripts/profile.js`, `api/subscriptions/get_ical_feed.php`), translations where Wallos named the running product (`includes/i18n/`), and an About page that names ShelfLife and credits Wallos (`about.php`). Technical identifiers (`wallos_*` functions, `wallos.db`, calendar event UIDs, the PWA id) and the update check against Wallos releases are unchanged. |
| 2026-10-14 | Static files are versioned by their contents, not by the Wallos version alone: `$assetVersion` (`includes/shelflife/asset_version.php`, `includes/version.php`, hash written at build time by the `Dockerfile`) is the cache-buster of every stylesheet and script and the name of the service worker's static cache (`service-worker.php`); a page newer than the installed worker gets its files from the network. |
| 2026-10-14 | Subscription list on phones: rows no longer overflow the screen (two lines below 560px, the name shortened with an ellipsis), the days left sit under the date, and the toolbar above the list fits 320px screens (`styles/styles.css`). |
| 2026-10-14 | A Telegram update id the bot's internal API has already processed is answered again only to the Telegram account it was processed for; the same id from another account is refused without the stored response, which names the record (`includes/shelflife/bot_actions.php`, documented in `api/internal/telegram/item_add.php` and `item_action.php`). |
| 2026-10-14 | Telegram reminders are written as a card in the bot's style: what is due and when, the record's name, kind, period and category ("no category" left out), date and amount; long names are shortened, amounts use no-break spaces, and the "renewed" button names the period it renews for (`includes/shelflife/notifications.php`). |

The list is extended with every change made for ShelfLife.

The ShelfLife name and logo identify this modified version only; the program remains a
derivative of Wallos under GPL-3.0. The logo's lettering is Barlow Bold (SIL OFL 1.1,
https://fonts.google.com/specimen/Barlow) converted to outlines.

## Third-party code ported into this version

| Component | Source | License |
|---|---|---|
| Expiry status rules and their test scenarios (`includes/shelflife/status.php`, `tests/cases/shelflife_status_test.php`) | Vorrat, https://github.com/MarcelMuechler/Vorrat — Copyright (c) 2026 Marcel Muechler | MIT (text below) |

## Bundled libraries inherited from Wallos

Wallos bundles these libraries. The files marked "not shipped in the repository" carry no
license text in the Wallos source tree; the licenses listed for them are taken from their
upstream projects and must be verified before distribution.

| Library | Path | License |
|---|---|---|
| PHPMailer | `libs/PHPMailer` | LGPL-2.1 (header in files) |
| Parsedown | `libs/Parsedown.php` | MIT (`libs/Parsedown-LICENSE.txt`) |
| constant_time_encoding | `libs/constant_time_encoding` | MIT (header in files) |
| OTPHP | `libs/OTPHP` | MIT — not shipped in the repository, verify upstream |
| PSR Clock | `libs/Psr` | MIT — not shipped in the repository, verify upstream |
| Sortable | `scripts/libs/sortable.min.js` | MIT (header in file) |
| QRCode.js | `scripts/libs/qrcode.min.js` | MIT — not shipped in the repository, verify upstream |
| ApexCharts 5.15.2 | `scripts/libs/apexcharts.min.js` | dual community/commercial license, see https://apexcharts.com/license/ — review before distribution |
| Font Awesome Free 6.5.2 | `styles/*.css`, `webfonts/` | Icons CC BY 4.0, fonts SIL OFL 1.1, code MIT |
| Barlow font | `styles/barlow.css` | SIL OFL 1.1 — not shipped in the repository, verify upstream |

## MIT License (Vorrat)

Copyright (c) 2026 Marcel Muechler

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
