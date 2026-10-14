<?php
/*
  ShelfLife: calendar arithmetic for recurring records.

  Due dates have no time of day, so every value here is a plain Y-m-d string
  and the arithmetic runs in UTC, where no day is skipped or repeated.

  Months and years are added to the year/month pair and the day is then clamped
  to the length of the target month. The day the record was originally set to
  is kept as its anchor (subscriptions.anchor_day), so a payment due on the 31st
  falls on the last day of every shorter month and goes back to the 31st after
  it. DateTime::modify('+1 month') instead overflows: 31 January + 1 month is
  3 March.
*/

const SHELFLIFE_CYCLE_DAYS = 1;
const SHELFLIFE_CYCLE_WEEKS = 2;
const SHELFLIFE_CYCLE_MONTHS = 3;
const SHELFLIFE_CYCLE_YEARS = 4;
const SHELFLIFE_CYCLE_ONE_TIME = 5;

/**
 * @param mixed $value
 * @return DateTimeImmutable|null Midnight UTC of a strictly formatted Y-m-d date.
 */
function shelflife_parse_date($value)
{
    if (!is_string($value) || !preg_match('/^\d{4}-\d{2}-\d{2}$/', $value)) {
        return null;
    }

    $date = DateTimeImmutable::createFromFormat('!Y-m-d', $value, new DateTimeZone('UTC'));
    if ($date === false || $date->format('Y-m-d') !== $value) {
        return null;
    }

    return $date;
}

function shelflife_is_valid_date($value)
{
    return shelflife_parse_date($value) !== null;
}

function shelflife_is_recurring_cycle($cycle)
{
    return in_array((int) $cycle, [SHELFLIFE_CYCLE_DAYS, SHELFLIFE_CYCLE_WEEKS, SHELFLIFE_CYCLE_MONTHS, SHELFLIFE_CYCLE_YEARS], true);
}

function shelflife_days_in_month($year, $month)
{
    return (int) (new DateTimeImmutable(sprintf('%04d-%02d-01', $year, $month), new DateTimeZone('UTC')))->format('t');
}

/**
 * The day of month a monthly or yearly record keeps returning to; null for
 * the other cycles, which step by a fixed number of days.
 *
 * @return int|null
 */
function shelflife_anchor_day($cycle, $date)
{
    $cycle = (int) $cycle;
    if ($cycle !== SHELFLIFE_CYCLE_MONTHS && $cycle !== SHELFLIFE_CYCLE_YEARS) {
        return null;
    }

    $parsed = shelflife_parse_date($date);

    return $parsed === null ? null : (int) $parsed->format('j');
}

/**
 * One period after $date.
 *
 * @param string   $date      Y-m-d
 * @param int      $cycle     1 days, 2 weeks, 3 months, 4 years
 * @param int      $frequency number of cycle units per period, at least 1
 * @param int|null $anchorDay day of month to aim for (months and years only)
 * @return string Y-m-d
 */
function shelflife_add_period($date, $cycle, $frequency, $anchorDay = null)
{
    $start = shelflife_parse_date($date);
    if ($start === null) {
        throw new InvalidArgumentException('Invalid date: ' . var_export($date, true));
    }

    $frequency = (int) $frequency;
    if ($frequency < 1) {
        throw new InvalidArgumentException('Frequency must be at least 1');
    }

    switch ((int) $cycle) {
        case SHELFLIFE_CYCLE_DAYS:
            return $start->modify('+' . $frequency . ' days')->format('Y-m-d');
        case SHELFLIFE_CYCLE_WEEKS:
            return $start->modify('+' . (7 * $frequency) . ' days')->format('Y-m-d');
        case SHELFLIFE_CYCLE_MONTHS:
            $months = $frequency;
            break;
        case SHELFLIFE_CYCLE_YEARS:
            $months = 12 * $frequency;
            break;
        default:
            throw new InvalidArgumentException('Cycle ' . var_export($cycle, true) . ' does not repeat');
    }

    $day = $anchorDay === null ? (int) $start->format('j') : (int) $anchorDay;
    if ($day < 1 || $day > 31) {
        throw new InvalidArgumentException('Anchor day must be between 1 and 31');
    }

    $monthIndex = (int) $start->format('Y') * 12 + (int) $start->format('n') - 1 + $months;
    $year = intdiv($monthIndex, 12);
    $month = $monthIndex % 12 + 1;

    return sprintf('%04d-%02d-%02d', $year, $month, min($day, shelflife_days_in_month($year, $month)));
}

/**
 * Moves $date forward by whole periods until it is on or after $minDate.
 * With $atLeastOnce it always moves at least one period, which is what
 * confirming a payment that is not overdue yet means.
 *
 * @return string Y-m-d
 */
function shelflife_advance_until($date, $cycle, $frequency, $anchorDay, $minDate, $atLeastOnce = false)
{
    if (!shelflife_is_valid_date($minDate)) {
        throw new InvalidArgumentException('Invalid date: ' . var_export($minDate, true));
    }

    $current = $date;
    $steps = 0;

    // Y-m-d strings order the same way the dates do.
    while (($atLeastOnce && $steps === 0) || $current < $minDate) {
        $current = shelflife_add_period($current, $cycle, $frequency, $anchorDay);
        $steps++;

        if ($steps > 100000) {
            throw new RuntimeException('Too many periods between ' . $date . ' and ' . $minDate);
        }
    }

    return $current;
}

/**
 * Whole days from $from to $to; negative when $to is earlier.
 */
function shelflife_days_between($from, $to)
{
    $start = shelflife_parse_date($from);
    $end = shelflife_parse_date($to);
    if ($start === null || $end === null) {
        throw new InvalidArgumentException('Invalid date');
    }

    return (int) $start->diff($end)->format('%r%a');
}

/**
 * The application's time zone: the TZ the container runs in (as the cron jobs
 * already read it in endpoints/cronjobs/settimezone.php), else PHP's default.
 *
 * @return DateTimeZone
 */
function shelflife_timezone()
{
    $name = getenv('TZ');
    if ($name === false || $name === '') {
        $name = date_default_timezone_get();
    }

    try {
        return new DateTimeZone($name);
    } catch (Exception $e) {
        return new DateTimeZone('UTC');
    }
}

/**
 * Today's date in the application's time zone.
 *
 * @return string Y-m-d
 */
function shelflife_today()
{
    return (new DateTimeImmutable('now', shelflife_timezone()))->format('Y-m-d');
}
