<?php
/*
  ShelfLife traffic-light status (includes/shelflife/status.php).

  The scenarios follow Vorrat's backend/tests/test_stock.py (MIT, Copyright
  (c) 2026 Marcel Muechler): far away is fine, inside the window is "soon",
  past is overdue, and a per-record window overrides the default. The window
  boundary follows the ShelfLife specification: less than 7 days left is yellow.
*/

require_once WALLOS_ROOT . '/includes/shelflife/status.php';

wallos_test('a date far away is green', function () {
    assert_same(SHELFLIFE_STATUS_OK, shelflife_record_status('2025-07-01', '2025-06-01'), '30 days left');
});

wallos_test('a date inside the warning window is yellow', function () {
    assert_same(SHELFLIFE_STATUS_SOON, shelflife_record_status('2025-06-02', '2025-06-01'), 'tomorrow');
    assert_same(SHELFLIFE_STATUS_SOON, shelflife_record_status('2025-06-01', '2025-06-01'), 'today is not overdue yet');
    assert_same(SHELFLIFE_STATUS_SOON, shelflife_record_status('2025-06-07', '2025-06-01'), '6 days left');
});

wallos_test('exactly 7 days left is still green', function () {
    assert_same(SHELFLIFE_STATUS_OK, shelflife_record_status('2025-06-08', '2025-06-01'), '7 days left');
});

wallos_test('a date in the past is red', function () {
    assert_same(SHELFLIFE_STATUS_OVERDUE, shelflife_record_status('2025-05-31', '2025-06-01'), 'yesterday');
    assert_same(SHELFLIFE_STATUS_OVERDUE, shelflife_record_status('2024-06-01', '2025-06-01'), 'a year ago');
});

wallos_test('a narrower window takes precedence over the default', function () {
    assert_same(SHELFLIFE_STATUS_OK, shelflife_record_status('2025-06-04', '2025-06-01', 3), '3 days left with a 3-day window');
    assert_same(SHELFLIFE_STATUS_SOON, shelflife_record_status('2025-06-03', '2025-06-01', 3), '2 days left with a 3-day window');
});

wallos_test('days left are counted across month ends', function () {
    assert_same(1, shelflife_days_left('2025-03-01', '2025-02-28'), 'February 28 to March 1');
    assert_same(-2, shelflife_days_left('2025-02-27', '2025-03-01'), 'two days overdue');
});

wallos_test('days left are worded for the pages in Russian and English', function () {
    assert_same(['просрочено на 2 дня', 'сегодня', 'завтра', 'через 5 дней', 'через 21 день'],
        array_map(fn($d) => shelflife_days_left_text($d, 'ru'), [-2, 0, 1, 5, 21]), 'Russian');
    assert_same(['1 day overdue', 'today', 'tomorrow', 'in 5 days'],
        array_map(fn($d) => shelflife_days_left_text($d, 'en'), [-1, 0, 1, 5]), 'English');
});
