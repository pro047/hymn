/**
 * Midnight of a given day, defaulting to today.
 *
 * The calendar compares the dates it renders against this, so the time of day
 * has to go: left in, "today" is this afternoon and the calendar greys today
 * itself out.
 */
export function startOfToday(now: Date = new Date()): Date {
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}
