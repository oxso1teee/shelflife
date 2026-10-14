<?php

// ShelfLife: reminders to send through the Telegram bot (an outbox).
//
// The planner adds one row per record, due date and reminder day; the unique
// key makes planning idempotent, so a repeated or overlapping cron run, or a
// restart, never queues the same reminder twice. The sender claims rows one at
// a time, so two senders cannot deliver the same row. See
// includes/shelflife/notifications.php.

$db->exec("CREATE TABLE IF NOT EXISTS telegram_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    subscription_id INTEGER NOT NULL,
    due_date TEXT NOT NULL,
    remind_on TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at INTEGER NOT NULL DEFAULT 0,
    locked_at INTEGER DEFAULT NULL,
    last_error TEXT DEFAULT NULL,
    telegram_message_id INTEGER DEFAULT NULL,
    created_at INTEGER NOT NULL,
    sent_at INTEGER DEFAULT NULL,
    UNIQUE (subscription_id, due_date, remind_on),
    FOREIGN KEY (user_id) REFERENCES user(id)
)");

$db->exec('CREATE INDEX IF NOT EXISTS idx_telegram_outbox_status ON telegram_outbox(status, next_attempt_at)');
