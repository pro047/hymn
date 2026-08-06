import { API_PATHS } from "./paths";

/**
 * Asks whether an address is already registered.
 *
 * Every outcome that is not a verdict collapses to `null` — a 429, a 422 for an
 * address the client-side trigger accepted and EmailStr did not, an aborted
 * request, a dropped connection, a body that is not the expected shape. The
 * caller has one "no answer" case to handle instead of five, and none of them is
 * the user's mistake to fix: signup still has the server's 409 behind it.
 */
export async function fetchEmailAvailability(
  email: string,
  signal: AbortSignal
): Promise<boolean | null> {
  try {
    const response = await fetch(API_PATHS.authCheckEmail(email), { signal });
    if (!response.ok) return null;

    const payload = (await response.json()) as { available?: unknown };
    return typeof payload.available === "boolean" ? payload.available : null;
  } catch {
    return null;
  }
}
