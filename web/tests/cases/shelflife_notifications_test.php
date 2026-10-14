<?php
/*
  ShelfLife Telegram reminders (includes/shelflife/notifications.php).

  Planning twice queues nothing new; a reminder day missed while the server was
  down is still sent; a reminder for a due date that changed is dropped; each
  of Telegram's failure answers leads to the right next step; messages are
  escaped and carry the three buttons the bot understands. Telegram itself is
  replaced by a recording sender.
*/

require_once WALLOS_ROOT . '/includes/shelflife/notifications.php';

function shelflife_notify_test_setup()
{
    $db = wallos_test_open_database();
    wallos_test_create_user($db, 1, 'alice');
    $db->exec('UPDATE user SET telegram_id = 555 WHERE id = 1');
    $db->exec('INSERT INTO notification_settings (days, user_id) VALUES (2, 1)');

    return $db;
}

function shelflife_notify_test_record(SQLite3 $db, array $overrides = [])
{
    $input = $overrides + [
        'name' => 'Spotify',
        'price' => '9.99',
        'currency_id' => wallos_test_currency_id(1, 1),
        'cycle' => SHELFLIFE_CYCLE_MONTHS,
        'frequency' => 1,
        'next_payment' => '2026-11-15',
        'notify' => true,
        'notify_days_before' => -1,
    ];

    return shelflife_subscription_insert($db, 1, shelflife_subscription_prepare($db, 1, $input));
}

function shelflife_notify_test_sender(array $answers = [])
{
    $sender = new class ($answers) {
        public $sent = [];
        private $answers;

        public function __construct($answers)
        {
            $this->answers = $answers;
        }

        public function __invoke($chatId, $text, $markup)
        {
            $this->sent[] = ['chat' => $chatId, 'text' => $text, 'markup' => $markup];
            return array_shift($this->answers) ?? ['ok' => true, 'result' => ['message_id' => 100 + count($this->sent)], 'error_code' => null, 'description' => null, 'retry_after' => null, 'network_error' => null];
        }
    };

    return $sender;
}

function shelflife_notify_test_error($code, $retryAfter = null)
{
    return ['ok' => false, 'result' => null, 'error_code' => $code, 'description' => 'error ' . $code, 'retry_after' => $retryAfter, 'network_error' => null];
}

function shelflife_notify_test_status(SQLite3 $db, $subscriptionId)
{
    return $db->querySingle('SELECT status FROM telegram_outbox WHERE subscription_id = ' . (int) $subscriptionId . ' ORDER BY id DESC LIMIT 1');
}

wallos_test('a reminder is queued once its day comes, and only once', function () {
    $db = shelflife_notify_test_setup();
    $id = shelflife_notify_test_record($db); // due 15 Nov, account default: 2 days before

    assert_same(0, shelflife_notify_plan($db, '2026-11-12', 1000), 'not yet on the 12th');
    assert_same(1, shelflife_notify_plan($db, '2026-11-13', 1000), 'queued on the 13th');
    assert_same(0, shelflife_notify_plan($db, '2026-11-13', 2000), 'planning again adds nothing');
    assert_same(0, shelflife_notify_plan($db, '2026-11-14', 3000), 'nor on the next day');
    assert_same('2026-11-13', $db->querySingle("SELECT remind_on FROM telegram_outbox WHERE subscription_id = $id"), 'for the 13th');

    $db->close();
});

wallos_test('a reminder day missed while the server was down is caught up', function () {
    $db = shelflife_notify_test_setup();
    shelflife_notify_test_record($db, ['notify_days_before' => 5]);

    assert_same(1, shelflife_notify_plan($db, '2026-11-14', 1000), 'the 10th was missed; it is queued on the 14th');

    $db->close();
});

wallos_test('only linked accounts, active records with reminders on, and not long overdue', function () {
    $db = shelflife_notify_test_setup();
    shelflife_notify_test_record($db, ['name' => 'Off', 'notify' => false]);
    shelflife_notify_test_record($db, ['name' => 'Inactive', 'inactive' => true]);
    shelflife_notify_test_record($db, ['name' => 'Old', 'next_payment' => '2026-11-01']);
    shelflife_notify_test_record($db, ['name' => 'Recent', 'next_payment' => '2026-11-12']);
    wallos_test_create_user($db, 2, 'bob');
    shelflife_subscription_insert($db, 2, shelflife_subscription_prepare($db, 2, [
        'name' => 'Bob', 'price' => '1', 'currency_id' => wallos_test_currency_id(2, 0), 'cycle' => 3, 'next_payment' => '2026-11-15', 'notify' => true,
    ]));

    assert_same(1, shelflife_notify_plan($db, '2026-11-14', 1000), 'only the recent overdue record of the linked account');
    assert_same('Recent', $db->querySingle('SELECT s.name FROM telegram_outbox o JOIN subscriptions s ON s.id = o.subscription_id'), 'and it is that one');

    $db->close();
});

wallos_test('a snooze queues the reminder again on the snooze day', function () {
    $db = shelflife_notify_test_setup();
    $id = shelflife_notify_test_record($db);
    shelflife_notify_run($db, shelflife_notify_test_sender(), '2026-11-13', 1000);

    shelflife_subscription_snooze($db, 1, $id, '2026-11-13', '2026-11-15', 1);
    assert_same(0, shelflife_notify_plan($db, '2026-11-13', 2000), 'nothing more today');
    assert_same(1, shelflife_notify_plan($db, '2026-11-14', 3000), 'again tomorrow');

    $db->close();
});

wallos_test('a sent reminder names the record and carries the three buttons', function () {
    $db = shelflife_notify_test_setup();
    $id = shelflife_notify_test_record($db, ['name' => 'Tom & <Jerry>']);
    $sender = shelflife_notify_test_sender();

    $counts = shelflife_notify_run($db, $sender, '2026-11-14', 1000);

    assert_same(['queued' => 1, 'sent' => 1, 'pending' => 0, 'failed' => 0, 'cancelled' => 0], $counts, 'one queued, one sent');
    $message = $sender->sent[0];
    assert_same(555, $message['chat'], 'to the linked Telegram account');
    assert_same("🔔 Оплата завтра\n\n<b>Tom &amp; &lt;Jerry&gt;</b>\nПодписка · каждый месяц\nДата: 15.11.2026\nСумма: 9,99\u{00A0}$", $message['text'], 'the text');
    $buttons = array_merge(...$message['markup']['inline_keyboard']);
    assert_same(['Продлено на месяц', 'Отменено', 'Напомнить позже'], array_column($buttons, 'text'), 'the buttons');
    assert_same(["a:$id:20261115:r", "a:$id:20261115:c", "a:$id:20261115:s"], array_column($buttons, 'callback_data'), 'callback data for the bot');
    assert_true(max(array_map('strlen', array_column($buttons, 'callback_data'))) <= 64, 'within Telegram\'s 64-byte limit');
    assert_same(101, $db->querySingle("SELECT telegram_message_id FROM telegram_outbox WHERE subscription_id = $id"), 'the message id is kept');

    assert_same(0, shelflife_notify_run($db, $sender, '2026-11-14', 2000)['sent'], 'a second run sends nothing');

    $db->close();
});

wallos_test('texts for shelf-life, maintenance and overdue records', function () {
    $record = ['id' => 1, 'name' => 'Витамины', 'next_payment' => '2026-11-15', 'kind' => 'expiry', 'cycle' => 5, 'frequency' => 1, 'price' => 0];
    $text = fn(array $overrides, $symbol, $today, $category = null) => shelflife_notify_message($overrides + $record, $symbol, $today, $category)['text'];

    assert_same("🔔 Срок годности истекает через 3 дня\n\n<b>Витамины</b>\nСрок годности\nДата: 15.11.2026", $text([], '', '2026-11-12'), 'expiry ahead: no amount, no period');
    assert_same("⚠️ Срок годности истёк 2 дня назад\n\n<b>Витамины</b>\nСрок годности\nДата: 15.11.2026", $text([], '', '2026-11-17'), 'expiry passed');
    assert_same("🔔 Обслуживание сегодня\n\n<b>Фильтр</b>\nОбслуживание · каждые 3 месяца\nДата: 15.11.2026", $text(['name' => 'Фильтр', 'kind' => 'maintenance', 'cycle' => 3, 'frequency' => 3], '', '2026-11-15'), 'maintenance today');
    assert_same("⚠️ Обслуживание просрочено на 1 день\n\n<b>Фильтр</b>\nОбслуживание · каждые 3 месяца\nДата: 15.11.2026\nСумма: 1\u{00A0}500\u{00A0}₽", $text(['name' => 'Фильтр', 'kind' => 'maintenance', 'cycle' => 3, 'frequency' => 3, 'price' => 1500], '₽', '2026-11-16'), 'maintenance overdue, with its cost');
    assert_same("🔔 Оплата через 21 день\n\n<b>Netflix</b>\nПодписка · каждый месяц · Кино &amp; ТВ\nДата: 15.11.2026\nСумма: 500\u{00A0}₽", $text(['name' => 'Netflix', 'kind' => 'subscription', 'cycle' => 3, 'frequency' => 1, 'price' => 500], '₽', '2026-10-25', 'Кино & ТВ'), 'subscription with its category, escaped');
    assert_same("⚠️ Оплата просрочена на 2 дня\n\n<b>Аренда</b>\nПодписка · каждый месяц\nДата: 15.11.2026\nСумма: 30\u{00A0}000,50\u{00A0}₽", $text(['name' => 'Аренда', 'kind' => 'subscription', 'cycle' => 3, 'frequency' => 1, 'price' => 30000.5], '₽', '2026-11-17'), 'overdue payment, thousands and kopecks');
    assert_same("🔔 Оплата завтра\n\n<b>Курс</b>\nПодписка · разово\nДата: 15.11.2026\nСумма: 990", $text(['name' => 'Курс', 'kind' => 'subscription', 'price' => 990], '', '2026-11-14'), 'a one-time purchase, a currency without a symbol');
});

wallos_test('a long name is shortened in the reminder', function () {
    $long = str_repeat('Очень длинное название ', 10);
    $text = shelflife_notify_message(['id' => 1, 'name' => $long, 'next_payment' => '2026-11-15', 'kind' => 'expiry', 'cycle' => 5, 'frequency' => 1, 'price' => 0], '', '2026-11-14')['text'];
    $name = explode('</b>', explode('<b>', $text)[1])[0];

    assert_same(80, mb_strlen($name, 'UTF-8'), 'cut to 80 characters');
    assert_true(str_ends_with($name, '…'), 'with an ellipsis');
});

wallos_test('the "renewed" button names the period it renews for', function () {
    $label = fn($cycle, $frequency) => shelflife_notify_message(['id' => 1, 'name' => 'X', 'next_payment' => '2026-11-15', 'kind' => 'subscription', 'cycle' => $cycle, 'frequency' => $frequency, 'price' => 1], '', '2026-11-14')['reply_markup']['inline_keyboard'][0][0]['text'];

    assert_same('Продлено на месяц', $label(SHELFLIFE_CYCLE_MONTHS, 1), 'monthly, as in the specification');
    assert_same('Продлено на 3 месяца', $label(SHELFLIFE_CYCLE_MONTHS, 3), 'every 3 months');
    assert_same('Продлено на год', $label(SHELFLIFE_CYCLE_YEARS, 1), 'yearly');
    assert_same('Продлено на 5 лет', $label(SHELFLIFE_CYCLE_YEARS, 5), 'every 5 years');
    assert_same('Продлено на неделю', $label(SHELFLIFE_CYCLE_WEEKS, 1), 'weekly');
    assert_same('Продлено на 2 дня', $label(SHELFLIFE_CYCLE_DAYS, 2), 'every 2 days');
    assert_same('Продлено на месяц', $label(SHELFLIFE_CYCLE_ONE_TIME, 1), 'a one-time record moves by a month');
});

wallos_test('a reminder shows the record\'s category, but not "no category"', function () {
    $db = shelflife_notify_test_setup();
    $db->exec("UPDATE user SET language = 'ru' WHERE id = 1");
    $category = fn($name) => ($db->exec("INSERT INTO categories (name, \"order\", user_id) VALUES ('" . SQLite3::escapeString($name) . "', 9, 1)") ? $db->lastInsertRowID() : null);
    $music = shelflife_notify_test_record($db, ['name' => 'Spotify', 'category_id' => $category('Музыка &amp; подкасты')]);
    $none = shelflife_notify_test_record($db, ['name' => 'Netflix', 'category_id' => $category(default_no_category_name('ru'))]);
    $english = shelflife_notify_test_record($db, ['name' => 'Disney', 'category_id' => $category('No category')]);
    $sender = shelflife_notify_test_sender();

    shelflife_notify_run($db, $sender, '2026-11-14', 1000);
    $texts = [];
    foreach ($sender->sent as $message) {
        $texts[explode('</b>', explode('<b>', $message['text'])[1])[0]] = explode("\n", $message['text'])[3];
    }

    assert_same('Подписка · каждый месяц · Музыка &amp; подкасты', $texts['Spotify'], 'the category, as the website shows it, escaped once');
    assert_same('Подписка · каждый месяц', $texts['Netflix'], 'the account\'s own "no category" is left out');
    assert_same('Подписка · каждый месяц', $texts['Disney'], 'and so is Wallos\'s English default');
    assert_true($music !== $none && $none !== $english, 'three records');

    $db->close();
});

wallos_test('a reminder for a due date that changed is not sent', function () {
    $db = shelflife_notify_test_setup();
    $id = shelflife_notify_test_record($db);
    shelflife_notify_plan($db, '2026-11-14', 1000);
    shelflife_subscription_renew($db, 1, $id, '2026-11-14', '2026-11-15'); // renewed on the website meanwhile
    $sender = shelflife_notify_test_sender();

    $counts = shelflife_notify_run($db, $sender, '2026-11-14', 1000);

    assert_same(0, count($sender->sent), 'nothing was sent');
    assert_same(1, $counts['cancelled'], 'the old reminder was dropped');

    $db->close();
});

wallos_test('flood control waits as long as Telegram asks, without using up an attempt', function () {
    $db = shelflife_notify_test_setup();
    $id = shelflife_notify_test_record($db);

    shelflife_notify_run($db, shelflife_notify_test_sender([shelflife_notify_test_error(429, 30)]), '2026-11-14', 1000);
    assert_same(['pending', 0, 1030], [shelflife_notify_test_status($db, $id), $db->querySingle('SELECT attempts FROM telegram_outbox'), $db->querySingle('SELECT next_attempt_at FROM telegram_outbox')], 'retry in 30 s');

    assert_same(0, shelflife_notify_run($db, shelflife_notify_test_sender(), '2026-11-14', 1010)['sent'], 'not before');
    assert_same(1, shelflife_notify_run($db, shelflife_notify_test_sender(), '2026-11-14', 1031)['sent'], 'sent after');

    $db->close();
});

wallos_test('a blocked bot or a rejected message is not retried', function () {
    foreach ([403, 400] as $code) {
        $db = shelflife_notify_test_setup();
        $id = shelflife_notify_test_record($db);
        shelflife_notify_run($db, shelflife_notify_test_sender([shelflife_notify_test_error($code)]), '2026-11-14', 1000);
        assert_same('failed', shelflife_notify_test_status($db, $id), $code . ' fails the reminder');
        assert_same(0, shelflife_notify_run($db, shelflife_notify_test_sender(), '2026-11-14', 99999)['sent'], $code . ' is not retried');
        $db->close();
    }
});

wallos_test('network and server errors are retried with a growing delay, then given up', function () {
    $db = shelflife_notify_test_setup();
    $id = shelflife_notify_test_record($db);
    $network = ['ok' => false, 'result' => null, 'error_code' => null, 'description' => null, 'retry_after' => null, 'network_error' => 'timeout'];

    $now = 1000;
    $delays = [];
    for ($i = 0; $i < SHELFLIFE_NOTIFY_MAX_ATTEMPTS; $i++) {
        shelflife_notify_run($db, shelflife_notify_test_sender([$i % 2 ? $network : shelflife_notify_test_error(502)]), '2026-11-14', $now);
        $next = $db->querySingle('SELECT next_attempt_at FROM telegram_outbox');
        $delays[] = $next - $now;
        $now = $next;
    }

    assert_same([60, 120, 240, 480], array_slice($delays, 0, 4), 'the delay doubles');
    assert_same('failed', shelflife_notify_test_status($db, $id), 'given up after the last attempt');
    assert_contains('502', $db->querySingle('SELECT last_error FROM telegram_outbox'), 'the reason of the last attempt is kept');

    $db->close();
});

wallos_test('a reminder left "sending" by a crashed run is sent again, and a claimed one is not sent twice', function () {
    $db = shelflife_notify_test_setup();
    $id = shelflife_notify_test_record($db);
    shelflife_notify_plan($db, '2026-11-14', 1000);

    $claimed = shelflife_notify_claim($db, 1000);
    assert_same($id, $claimed['subscription_id'], 'claimed');
    assert_same(null, shelflife_notify_claim($db, 1001), 'a second claim gets nothing while it is being sent');

    $again = shelflife_notify_claim($db, 1000 + SHELFLIFE_NOTIFY_STALE_LOCK_SECONDS + 1);
    assert_same($id, $again['subscription_id'] ?? null, 'released after the lock expires');

    $db->close();
});

wallos_test('an unlinked account gets nothing', function () {
    $db = shelflife_notify_test_setup();
    shelflife_notify_test_record($db);
    shelflife_notify_plan($db, '2026-11-14', 1000);
    $db->exec('UPDATE user SET telegram_id = NULL WHERE id = 1');
    $sender = shelflife_notify_test_sender();

    assert_same(1, shelflife_notify_run($db, $sender, '2026-11-14', 1000)['cancelled'], 'the queued reminder is dropped');
    assert_same(0, count($sender->sent), 'nothing sent');

    $db->close();
});

wallos_test('Russian plural forms of days', function () {
    $forms = array_map('shelflife_ru_days', [1, 2, 4, 5, 11, 12, 14, 21, 22, 25, 101, 111]);
    assert_same(['1 день', '2 дня', '4 дня', '5 дней', '11 дней', '12 дней', '14 дней', '21 день', '22 дня', '25 дней', '101 день', '111 дней'], $forms, 'forms');
});
