import { addDays, format, startOfWeek } from "date-fns";

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

/**
 * The Sunday that closes the week `now` falls in, as "yyyy-MM-dd".
 *
 * Weeks start on Monday, so on a Sunday this is today, and it only moves at
 * Monday 00:00 -- the one moment anything showing it has to refresh.
 */
export function upcomingSundayOf(now: Date = new Date()): string {
  return format(addDays(startOfWeek(now, { weekStartsOn: 1 }), 6), "yyyy-MM-dd");
}

/** Milliseconds from `now` until the next Monday 00:00. */
export function msUntilNextWeek(now: Date = new Date()): number {
  const nextMonday = addDays(startOfWeek(now, { weekStartsOn: 1 }), 7);
  return nextMonday.getTime() - now.getTime();
}
