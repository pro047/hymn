/**
 * Decision logic for the signup form's automatic email availability lookup
 * (GET /auth/check-email).
 *
 * The page keeps the effects — the debounce timer, the AbortController, the
 * fetch, the cache Map. Everything that decides *whether to ask* and *whether to
 * believe an answer* lives here, so it can be tested without a DOM.
 *
 * The lookup is a convenience, never a gate: the schema in
 * validation/auth-schema.ts decides what may be submitted, and the server's 409
 * is the last word on duplicates.
 */
import { z } from "zod";

/**
 * Idle time after the last keystroke before a lookup is worth spending. The
 * endpoint allows 10/minute per IP, so firing per keystroke would 429 a user
 * halfway through typing one address.
 */
export const EMAIL_CHECK_DEBOUNCE_MS = 500;

export const EMAIL_TAKEN_MESSAGE = "이미 사용 중인 이메일입니다.";
export const EMAIL_AVAILABLE_MESSAGE = "사용할 수 있는 이메일입니다.";

/** `unknown` covers both "not asked yet" and "asked, no usable answer". */
export type EmailCheckStatus = "unknown" | "checking" | "available" | "taken";

export type EmailCheckPlan =
  | { action: "skip"; status: "unknown" }
  | { action: "reuse"; status: "available" | "taken"; key: string }
  | { action: "query"; status: "checking"; key: string };

export type EmailCheckResolution =
  { apply: false } | { apply: true; status: "unknown" | "available" | "taken" };

/**
 * The rule signup used to be gated on, demoted to a trigger. It is narrower than
 * the server's EmailStr, which as a gate made valid addresses unregisterable; as
 * a trigger the same strictness only skips a lookup, leaving the form exactly as
 * it behaved before this feature existed.
 */
const emailShape = z.email();

/** Matches what signupSchema sends and what the server normalizes to, so one
 *  address cannot occupy two cache entries or two rate-limit slots. */
const normalize = (raw: string) => raw.trim().toLowerCase();

/** Whether a value is well-formed enough to spend a rate-limited lookup on. */
export function looksLikeEmail(raw: string): boolean {
  return emailShape.safeParse(normalize(raw)).success;
}

/**
 * Decides what the current input value warrants: nothing, a cached answer, or a
 * request. `cache` maps a normalized address to its availability; only answers
 * the server actually gave belong in it.
 */
export function planEmailCheck(raw: string, cache: ReadonlyMap<string, boolean>): EmailCheckPlan {
  const key = normalize(raw);
  if (!looksLikeEmail(key)) return { action: "skip", status: "unknown" };

  const cached = cache.get(key);
  if (cached !== undefined) {
    return { action: "reuse", status: cached ? "available" : "taken", key };
  }
  return { action: "query", status: "checking", key };
}

/**
 * Decides whether an answer that has come back may be shown.
 *
 * `key` is the address that was asked about and `currentValue` is what is in the
 * field now: a reply that outlived its input is dropped, so a slow answer for an
 * old address cannot overwrite the verdict on a newer one. Aborting the request
 * is not enough on its own — an already-resolved promise still runs its
 * continuation.
 *
 * `available === null` means the server gave no usable answer (429, a 422 for an
 * address EmailStr rejects but {@link looksLikeEmail} accepts, a dropped
 * connection). That is reported as unknown rather than as an error — and must
 * not be cached, since the next attempt may well answer.
 */
export function resolveEmailCheck(
  key: string,
  currentValue: string,
  available: boolean | null
): EmailCheckResolution {
  if (key !== normalize(currentValue)) return { apply: false };
  if (available === null) return { apply: true, status: "unknown" };
  return { apply: true, status: available ? "available" : "taken" };
}
