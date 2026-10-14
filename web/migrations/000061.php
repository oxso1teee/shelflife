<?php

// ShelfLife: failed password attempts, read by includes/shelflife/login_throttle.php
// to stop password guessing on the login form. Rows older than a day are purged
// as new failures are recorded.

$db->exec('CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    attempted_at INTEGER NOT NULL
)');

$db->exec('CREATE INDEX IF NOT EXISTS idx_login_attempts_username ON login_attempts(username, attempted_at)');
