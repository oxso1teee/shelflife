<?php

// ShelfLife: a record is a paid subscription, a shelf-life date or a
// maintenance date, all kept in the subscriptions table so the existing
// listing, notifications and statistics keep working on them.
//
// - kind: 'subscription' | 'expiry' | 'maintenance'
// - anchor_day: the day of month a monthly or yearly record returns to, so
//   one due on the 31st is clamped to shorter months and comes back to the
//   31st afterwards (see includes/shelflife/dates.php)
// - snoozed_until: the "remind me later" date for the current due date
//
// Every step checks before it changes, so the migration can run twice.

$subscriptionColumns = [];
$columnsResult = $db->query("SELECT name FROM pragma_table_info('subscriptions')");
while ($column = $columnsResult->fetchArray(SQLITE3_ASSOC)) {
    $subscriptionColumns[] = $column['name'];
}

if (!in_array('kind', $subscriptionColumns, true)) {
    $db->exec("ALTER TABLE subscriptions ADD COLUMN kind TEXT NOT NULL DEFAULT 'subscription'");
}

if (!in_array('anchor_day', $subscriptionColumns, true)) {
    $db->exec('ALTER TABLE subscriptions ADD COLUMN anchor_day INTEGER DEFAULT NULL');
}

if (!in_array('snoozed_until', $subscriptionColumns, true)) {
    $db->exec('ALTER TABLE subscriptions ADD COLUMN snoozed_until TEXT DEFAULT NULL');
}

// Existing monthly and yearly records anchor on the day they are due next.
$db->exec("UPDATE subscriptions
           SET anchor_day = CAST(strftime('%d', next_payment) AS INTEGER)
           WHERE anchor_day IS NULL
             AND cycle IN (3, 4)
             AND date(next_payment) = next_payment");

$db->exec('CREATE INDEX IF NOT EXISTS idx_subscriptions_user_kind ON subscriptions(user_id, kind)');
