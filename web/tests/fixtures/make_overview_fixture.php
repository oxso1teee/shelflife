<?php
/*
  Writes bot/tests/fixtures/overview.json: a real overview
  (includes/shelflife/overview.php) of a sample account, the contract between
  the web app and the bot's tests. Regenerate after changing the overview:

    docker run --rm -v "$PWD":/w -w /w/web php:8.3-cli php tests/fixtures/make_overview_fixture.php > bot/tests/fixtures/overview.json
*/

require __DIR__ . '/../bootstrap.php';
require_once __DIR__ . '/../../includes/shelflife/overview.php';

$db = wallos_test_open_database();
wallos_test_create_user($db, 1, 'anna');
$db->exec("UPDATE user SET firstname = 'Анна', language = 'ru' WHERE id = 1");
$db->exec("INSERT INTO currencies (id, name, symbol, code, rate, user_id) VALUES (9100, 'Russian Ruble', '₽', 'RUB', 1, 1)");
$db->exec('UPDATE user SET main_currency = 9100 WHERE id = 1');
$db->exec("DELETE FROM categories WHERE user_id = 1");
foreach (['No category', 'Музыка', 'Дом'] as $order => $name) {
    $db->exec("INSERT INTO categories (name, \"order\", user_id) VALUES ('$name', $order, 1)");
}
$category = fn($name) => (int) $db->querySingle("SELECT id FROM categories WHERE user_id = 1 AND name = '$name'");

$records = [
    ['name' => 'Spotify', 'price' => '500', 'currency_id' => 9100, 'cycle' => 3, 'next_payment' => '2026-10-15', 'category_id' => $category('Музыка')],
    ['name' => 'Netflix', 'price' => '9.99', 'currency_id' => wallos_test_currency_id(1, 1), 'cycle' => 4, 'next_payment' => '2026-11-23'],
    ['name' => 'Аренда', 'price' => '30000', 'currency_id' => 9100, 'cycle' => 3, 'next_payment' => '2026-10-19', 'category_id' => $category('Дом')],
    ['name' => 'Витамины', 'kind' => 'expiry', 'price' => '', 'currency_id' => 9100, 'cycle' => 5, 'next_payment' => '2026-10-12', 'notify_days_before' => 3],
    ['name' => 'Молоко', 'kind' => 'expiry', 'price' => '', 'currency_id' => 9100, 'cycle' => 5, 'next_payment' => '2026-10-14'],
    ['name' => 'Фильтр для воды', 'kind' => 'maintenance', 'price' => '1500', 'currency_id' => 9100, 'cycle' => 3, 'frequency' => 3, 'next_payment' => '2026-11-03', 'category_id' => $category('Дом')],
    ['name' => 'Старая подписка', 'price' => '199', 'currency_id' => 9100, 'cycle' => 3, 'next_payment' => '2026-09-01', 'inactive' => true],
    ['name' => 'Tom & <Jerry> — очень длинное название подписки, которое не помещается в одну строку', 'price' => '99', 'currency_id' => 9100, 'cycle' => 2, 'next_payment' => '2027-01-10'],
];
foreach ($records as $input) {
    $input += ['kind' => 'subscription', 'frequency' => 1, 'notify' => true, 'notify_days_before' => -1];
    shelflife_subscription_insert($db, 1, shelflife_subscription_prepare($db, 1, $input));
}
shelflife_set_reminder_days($db, 1, 2);

echo json_encode(['status' => 'linked', 'overview' => shelflife_overview($db, 1, '2026-10-14'), 'site_url' => 'https://shelflife.example.com'],
    JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT) . "\n";
