/**
 * Week helpers. Mirrors backend/src/app/schemas/score.py — change both together.
 *
 * The backend is the source of truth: it rejects a past week with 422 whatever
 * this file says. What this buys is not letting the user pick one in the first
 * place, so the rule shows up as a greyed-out calendar rather than an error
 * after the fact.
 */

/**
 * The Sunday that opens the week containing `today`.
 *
 * A week is named by its Sunday (see _normalize_week_date in routes/score.py),
 * so the floor is this week's Sunday and not today — on a Thursday the current
 * week's own Sunday is already in the past by date, and treating that as "past"
 * would block the week the user is actually working on.
 */
export function currentWeekStart(today: Date = new Date()): Date {
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  // getDay() is 0 on Sunday and 6 on Saturday, which is exactly how many days
  // back the opening Sunday is.
  start.setDate(start.getDate() - start.getDay());
  return start;
}
