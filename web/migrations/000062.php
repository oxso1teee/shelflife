<?php

// ShelfLife: linking a Wallos account to a Telegram account.
//
// - user.telegram_id: the linked Telegram user id; one Telegram account can be
//   linked to one Wallos account only (partial unique index).
// - telegram_link_tokens: one-time tokens the profile page hands out for the
//   bot's /start command. Only a SHA-256 hash of each token is stored.

$userColumns = [];
$columnsResult = $db->query("SELECT name FROM pragma_table_info('user')");
while ($column = $columnsResult->fetchArray(SQLITE3_ASSOC)) {
    $userColumns[] = $column['name'];
}

if (!in_array('telegram_id', $userColumns, true)) {
    $db->exec('ALTER TABLE user ADD COLUMN telegram_id INTEGER DEFAULT NULL');
}

if (!in_array('telegram_username', $userColumns, true)) {
    $db->exec("ALTER TABLE user ADD COLUMN telegram_username TEXT DEFAULT NULL");
}

$db->exec('CREATE UNIQUE INDEX IF NOT EXISTS idx_user_telegram_id ON user(telegram_id) WHERE telegram_id IS NOT NULL');

$db->exec('CREATE TABLE IF NOT EXISTS telegram_link_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    used_at INTEGER DEFAULT NULL,
    FOREIGN KEY (user_id) REFERENCES user(id)
)');
