<?php
/*
  ShelfLife: traffic-light status of a record from its due date.

  Ported from Vorrat (backend/app/routers/stock.py, _status),
  Copyright (c) 2026 Marcel Muechler, MIT License — see NOTICE.md.

  Differences from the original: every ShelfLife record has a due date, so the
  "no date" and "does not spoil" branches are gone; and the warning window
  follows the ShelfLife specification, "less than 7 days left" (0..6 days is
  yellow, 7 is green), where Vorrat's window was inclusive.
*/

require_once __DIR__ . '/dates.php';

const SHELFLIFE_STATUS_OVERDUE = 'overdue'; // red: the date has passed
const SHELFLIFE_STATUS_SOON = 'soon';       // yellow: less than the window left
const SHELFLIFE_STATUS_OK = 'ok';           // green
const SHELFLIFE_SOON_DAYS = 7;

/**
 * Days from $today until $dueDate; negative once it has passed.
 */
function shelflife_days_left($dueDate, $today)
{
    return shelflife_days_between($today, $dueDate);
}

/**
 * @param string $dueDate  Y-m-d
 * @param string $today    Y-m-d
 * @param int    $soonDays size of the warning window in days
 * @return string one of the SHELFLIFE_STATUS_* constants
 */
function shelflife_record_status($dueDate, $today, $soonDays = SHELFLIFE_SOON_DAYS)
{
    $daysLeft = shelflife_days_left($dueDate, $today);

    if ($daysLeft < 0) {
        return SHELFLIFE_STATUS_OVERDUE;
    }

    if ($daysLeft < $soonDays) {
        return SHELFLIFE_STATUS_SOON;
    }

    return SHELFLIFE_STATUS_OK;
}

/**
 * "1 день", "2 дня", "5 дней".
 */
function shelflife_ru_days($n)
{
    $n = abs((int) $n);
    $mod10 = $n % 10;
    $mod100 = $n % 100;

    if ($mod10 === 1 && $mod100 !== 11) {
        return $n . ' день';
    }
    if ($mod10 >= 2 && $mod10 <= 4 && ($mod100 < 12 || $mod100 > 14)) {
        return $n . ' дня';
    }

    return $n . ' дней';
}

/**
 * How far away a due date is, for the web pages: "через 5 дней", "завтра",
 * "просрочено на 2 дня" in Russian, the same in English otherwise.
 *
 * @param int    $daysLeft see shelflife_days_left()
 * @param string $lang     the user's interface language
 */
function shelflife_days_left_text($daysLeft, $lang)
{
    $daysLeft = (int) $daysLeft;

    if (strpos((string) $lang, 'ru') === 0) {
        if ($daysLeft === 0) {
            return 'сегодня';
        }
        if ($daysLeft === 1) {
            return 'завтра';
        }
        return $daysLeft > 0 ? 'через ' . shelflife_ru_days($daysLeft) : 'просрочено на ' . shelflife_ru_days($daysLeft);
    }

    if ($daysLeft === 0) {
        return 'today';
    }
    if ($daysLeft === 1) {
        return 'tomorrow';
    }
    $days = abs($daysLeft) . (abs($daysLeft) === 1 ? ' day' : ' days');

    return $daysLeft > 0 ? 'in ' . $days : $days . ' overdue';
}
