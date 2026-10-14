<?php

// ShelfLife: Telegram updates the bot's internal API has already acted on.
//
// Telegram delivers an update again when the bot did not confirm it (a restart
// at the wrong moment, a network error). The internal API records the update id
// in the same transaction as the change it made and answers a repeat with the
// stored response, so /add never creates a record twice. Rows older than two
// days are purged as new ones are written.

$db->exec('CREATE TABLE IF NOT EXISTS telegram_processed_updates (
    update_id INTEGER PRIMARY KEY,
    telegram_id INTEGER NOT NULL,
    response TEXT NOT NULL,
    created_at INTEGER NOT NULL
)');
