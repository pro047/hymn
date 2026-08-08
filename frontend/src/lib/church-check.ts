/**
 * Decision logic for the signup form's automatic church lookup
 * (GET /auth/check-church).
 *
 * Deliberately the same shape as ./email-check.ts — the page owns the debounce
 * timer, the AbortController, the fetch and the cache Map; everything that
 * decides *whether to ask* and *whether to believe an answer* lives here so it
 * can be tested without a DOM. The two are kept apart rather than generalized
 * into one helper: they answer different questions, and the day one of them
 * grows a rule the other must not have, a shared version would have to be torn
 * back in half.
 *
 * The lookup decides which fields the form shows, not what it accepts. A wrong
 * guess costs a 403 from the server, which is the real gate.
 */

/**
 * Idle time after the last keystroke before a lookup is worth spending. Same
 * 500ms and same reason as the email lookup: /auth/check-church allows
 * 10/minute per IP, so asking per keystroke would 429 someone mid-word.
 */
export const CHURCH_CHECK_DEBOUNCE_MS = 500;

/**
 * Shortest input worth asking about. There is no format to test a church name
 * against the way an address has one, so this is the only filter — it exists to
 * skip the first keystroke or two, where the answer is near-certainly "no such
 * church" and would only be discarded. Korean church names are short, so the
 * bar has to stay low: 확인교회 is four characters.
 */
export const CHURCH_NAME_MIN_LOOKUP_LENGTH = 2;

export const CHURCH_EXISTING_MESSAGE = "이미 등록된 교회입니다. 초대 코드를 입력해 주세요.";
export const CHURCH_NEW_MESSAGE = "새로 등록되는 교회입니다. 회원님이 리더가 됩니다.";

/** `unknown` covers both "not asked yet" and "asked, no usable answer". */
export type ChurchCheckStatus = "unknown" | "checking" | "existing" | "new";

export type ChurchCheckPlan =
  | { action: "skip"; status: "unknown" }
  | { action: "reuse"; status: "existing" | "new"; key: string }
  | { action: "query"; status: "checking"; key: string };

export type ChurchCheckResolution =
  { apply: false } | { apply: true; status: "unknown" | "existing" | "new" };

/**
 * Matches what signupSchema sends and what the server stores, so one name
 * cannot occupy two cache entries or two rate-limit slots. Case is *not*
 * folded: churches.name is compared exactly, so folding here would report a
 * church as existing that the signup would then try to create.
 */
const normalize = (raw: string) => raw.trim();

/** Whether a value is worth spending a rate-limited lookup on. */
export function looksLikeChurchName(raw: string): boolean {
  return normalize(raw).length >= CHURCH_NAME_MIN_LOOKUP_LENGTH;
}

/**
 * Decides what the current input warrants: nothing, a cached answer, or a
 * request. `cache` maps a trimmed name to whether it is registered; only
 * answers the server actually gave belong in it.
 */
export function planChurchCheck(raw: string, cache: ReadonlyMap<string, boolean>): ChurchCheckPlan {
  const key = normalize(raw);
  if (!looksLikeChurchName(key)) return { action: "skip", status: "unknown" };

  const cached = cache.get(key);
  if (cached !== undefined) {
    return { action: "reuse", status: cached ? "existing" : "new", key };
  }
  return { action: "query", status: "checking", key };
}

/**
 * Decides whether an answer that has come back may be shown.
 *
 * `key` is the name that was asked about and `currentValue` is what is in the
 * field now: a reply that outlived its input is dropped, so a slow answer about
 * an old name cannot decide which fields are shown for a newer one. Aborting
 * the request is not enough on its own — an already-resolved promise still runs
 * its continuation.
 *
 * `exists === null` means the server gave no usable answer (a 429, a dropped
 * connection). Reported as unknown rather than as an error, and not cached: the
 * next attempt may well answer.
 */
export function resolveChurchCheck(
  key: string,
  currentValue: string,
  exists: boolean | null
): ChurchCheckResolution {
  if (key !== normalize(currentValue)) return { apply: false };
  if (exists === null) return { apply: true, status: "unknown" };
  return { apply: true, status: exists ? "existing" : "new" };
}
