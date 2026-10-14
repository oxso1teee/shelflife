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
    assert_same('Завтра спишется оплата за <b>Tom &amp; &lt;Jerry&gt;</b> (9,99 $) — 15.11.2026.', $message['text'], 'the text');
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

    assert_same('Срок годности <b>Витамины</b> истекает через 3 дня (15.11.2026).', shelflife_notify_message($record, '', '2026-11-12')['text'], 'expiry ahead');
    assert_same('Срок годности <b>Витамины</b> истёк 2 дня назад (15.11.2026).', shelflife_notify_message($record, '', '2026-11-17')['text'], 'expiry passed');
    assert_same('Обслуживание <b>Фильтр</b> — сегодня (15.11.2026).', shelflife_notify_message(['name' => 'Фильтр', 'kind' => 'maintenance', 'cycle' => 3, 'frequency' => 3] + $record, '', '2026-11-15')['text'], 'maintenance today');
    assert_same('Через 21 день спишется оплата за <b>Netflix</b> (500 ₽) — 15.11.2026.', shelflife_notify_message(['name' => 'Netflix', 'kind' => 'subscription', 'cycle' => 3, 'frequency' => 1, 'price' => 500] + $record, '₽', '2026-10-25')['text'], 'subscription, 21 days');
    assert_same('Продлено', shelflife_notify_message(['kind' => 'subscription', 'cycle' => 4] + $record, '', '2026-11-14')['reply_markup']['inline_keyboard'][0][0]['text'], 'a yearly record says just "renewed"');
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
