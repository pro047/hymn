import { API_PATHS } from "./paths";

/**
 * Asks whether a church name is already registered.
 *
 * Every outcome that is not a verdict collapses to `null` — a 429, a 422 for a
 * name the client-side trigger accepted, an aborted request, a dropped
 * connection, a body that is not the expected shape. The caller has one "no
 * answer" case instead of five, and none of them is the user's mistake to fix:
 * the server still decides the signup, and answers 403 if the code is missing.
 */
export async function fetchChurchExists(
  name: string,
  signal: AbortSignal
): Promise<boolean | null> {
  try {
    const response = await fetch(API_PATHS.authCheckChurch(name), { signal });
    if (!response.ok) return null;

    const payload = (await response.json()) as { exists?: unknown };
    return typeof payload.exists === "boolean" ? payload.exists : null;
  } catch {
    return null;
  }
}
