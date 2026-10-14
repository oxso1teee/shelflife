<?php
/*
  ShelfLife calendar arithmetic (includes/shelflife/dates.php).

  A monthly payment due on the 31st has to land on the last day of shorter
  months and come back to the 31st afterwards; a yearly one on 29 February has
  to fall on the 28th outside leap years and return to the 29th in them.
  DateTime::modify('+1 month') turns 31 January into 3 March, which is what the
  Wallos cron job and renew endpoint did before.
*/

require_once WALLOS_ROOT . '/includes/shelflife/dates.php';

wallos_test('a month after the 31st is the last day of a shorter month', function () {
    assert_same('2025-02-28', shelflife_add_period('2025-01-31', SHELFLIFE_CYCLE_MONTHS, 1), 'January 31 + 1 month in a common year');
    assert_same('2024-02-29', shelflife_add_period('2024-01-31', SHELFLIFE_CYCLE_MONTHS, 1), 'January 31 + 1 month in a leap year');
    assert_same('2025-04-30', shelflife_add_period('2025-03-31', SHELFLIFE_CYCLE_MONTHS, 1), 'March 31 + 1 month');
    assert_same('2025-02-28', shelflife_add_period('2025-01-30', SHELFLIFE_CYCLE_MONTHS, 1), 'January 30 + 1 month');
});

wallos_test('the anchor brings a clamped date back to its original day', function () {
    assert_same('2025-03-31', shelflife_add_period('2025-02-28', SHELFLIFE_CYCLE_MONTHS, 1, 31), 'anchor 31 after February');
    assert_same('2025-03-30', shelflife_add_period('2025-02-28', SHELFLIFE_CYCLE_MONTHS, 1, 30), 'anchor 30 after February');
    assert_same('2025-03-28', shelflife_add_period('2025-02-28', SHELFLIFE_CYCLE_MONTHS, 1), 'without an anchor the day stays 28');

    $date = '2025-01-31';
    $walk = [];
    for ($i = 0; $i < 4; $i++) {
        $date = shelflife_add_period($date, SHELFLIFE_CYCLE_MONTHS, 1, 31);
        $walk[] = $date;
    }
    assert_same(['2025-02-28', '2025-03-31', '2025-04-30', '2025-05-31'], $walk, 'a 31st payment never drifts');
});

wallos_test('yearly records keep 29 February in leap years only', function () {
    assert_same('2025-02-28', shelflife_add_period('2024-02-29', SHELFLIFE_CYCLE_YEARS, 1, 29), 'common year');
    assert_same('2028-02-29', shelflife_add_period('2027-02-28', SHELFLIFE_CYCLE_YEARS, 1, 29), 'back to the 29th in a leap year');
    assert_same('2028-02-29', shelflife_add_period('2024-02-29', SHELFLIFE_CYCLE_YEARS, 4, 29), 'every four years');
});

wallos_test('frequency multiplies the period and months roll into the next year', function () {
    assert_same('2026-02-28', shelflife_add_period('2025-11-30', SHELFLIFE_CYCLE_MONTHS, 3), 'quarterly from November 30');
    assert_same('2026-01-15', shelflife_add_period('2025-12-15', SHELFLIFE_CYCLE_MONTHS, 1), 'December to January');
    assert_same('2027-06-10', shelflife_add_period('2025-06-10', SHELFLIFE_CYCLE_YEARS, 2), 'every two years');
});

wallos_test('days and weeks step by whole days across month and year ends', function () {
    assert_same('2025-03-01', shelflife_add_period('2025-02-28', SHELFLIFE_CYCLE_DAYS, 1), 'last day of February + 1 day');
    assert_same('2024-02-29', shelflife_add_period('2024-02-28', SHELFLIFE_CYCLE_DAYS, 1), 'leap day');
    assert_same('2026-01-05', shelflife_add_period('2025-12-29', SHELFLIFE_CYCLE_WEEKS, 1), 'a week across the new year');
    assert_same('2025-01-29', shelflife_add_period('2025-01-01', SHELFLIFE_CYCLE_WEEKS, 4), 'four weeks');
});

wallos_test('invalid input is refused instead of guessed', function () {
    $refused = function ($callback) {
        try {
            $callback();
        } catch (InvalidArgumentException $e) {
            return true;
        }
        return false;
    };

    assert_true($refused(fn() => shelflife_add_period('2025-01-31', SHELFLIFE_CYCLE_ONE_TIME, 1)), 'one-time records have no period');
    assert_true($refused(fn() => shelflife_add_period('2025-01-31', SHELFLIFE_CYCLE_MONTHS, 0)), 'frequency 0');
    assert_true($refused(fn() => shelflife_add_period('2025-02-30', SHELFLIFE_CYCLE_MONTHS, 1)), 'a date that does not exist');
    assert_true($refused(fn() => shelflife_add_period('2025-01-31', SHELFLIFE_CYCLE_MONTHS, 1, 32)), 'anchor out of range');

    assert_same(null, shelflife_parse_date('2025-2-3'), 'dates must be zero-padded');
    assert_same(null, shelflife_parse_date('2025-02-29'), 'no 29 February in 2025');
    assert_same(null, shelflife_parse_date(20250101), 'numbers are not dates');
});

wallos_test('advancing stops on the first due date not in the past', function () {
    assert_same('2025-04-30', shelflife_advance_until('2025-01-31', SHELFLIFE_CYCLE_MONTHS, 1, 31, '2025-04-10'), 'overdue for months');
    assert_same('2025-04-10', shelflife_advance_until('2025-03-10', SHELFLIFE_CYCLE_MONTHS, 1, 10, '2025-04-10'), 'a due date of today is kept');
    assert_same('2025-05-20', shelflife_advance_until('2025-05-20', SHELFLIFE_CYCLE_MONTHS, 1, 20, '2025-04-10'), 'a future date is left alone');
    assert_same('2025-06-20', shelflife_advance_until('2025-05-20', SHELFLIFE_CYCLE_MONTHS, 1, 20, '2025-04-10', true), 'confirming moves at least one period');
    assert_same('2025-04-10', shelflife_advance_until('2025-04-08', SHELFLIFE_CYCLE_DAYS, 1, null, '2025-04-10'), 'daily records do not skip today');
});

wallos_test('day differences are signed whole days', function () {
    assert_same(1, shelflife_days_between('2025-02-28', '2025-03-01'), 'across February');
    assert_same(-1, shelflife_days_between('2025-03-01', '2025-02-28'), 'backwards');
    assert_same(0, shelflife_days_between('2025-03-01', '2025-03-01'), 'same day');
    assert_same(366, shelflife_days_between('2024-01-01', '2025-01-01'), 'a leap year');
});

wallos_test('the anchor only exists for monthly and yearly cycles', function () {
    assert_same(31, shelflife_anchor_day(SHELFLIFE_CYCLE_MONTHS, '2025-01-31'), 'monthly');
    assert_same(29, shelflife_anchor_day(SHELFLIFE_CYCLE_YEARS, '2024-02-29'), 'yearly');
    assert_same(null, shelflife_anchor_day(SHELFLIFE_CYCLE_WEEKS, '2025-01-31'), 'weekly');
    assert_same(null, shelflife_anchor_day(SHELFLIFE_CYCLE_ONE_TIME, '2025-01-31'), 'one-time');
});
