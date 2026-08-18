/**
 * One-shot copy handed from an auth screen to the one it navigates to.
 *
 * The account page ends its own session when the password changes, so it cannot
 * show the confirmation itself — the user is on /login before they could read
 * it. Router state carries the fact across; the login page owns the wording.
 */
import type { Location } from "react-router-dom";

export const PASSWORD_CHANGED_NOTICE = "비밀번호를 변경했습니다. 새 비밀번호로 로그인해 주세요.";
/** Worded apart from the one above: a reset ends sessions the user may not have
 *  known about, which is the point of the recovery path and worth saying. */
export const PASSWORD_RESET_NOTICE =
  "비밀번호를 재설정했습니다. 모든 기기에서 로그아웃되었으니 새 비밀번호로 로그인해 주세요.";

/** What the account and reset pages put in `navigate(..., { state })`. */
export type AuthNoticeState = { passwordChanged?: boolean; passwordReset?: boolean };

/**
 * Whether the login page should show the password-changed notice.
 *
 * A boolean travels rather than the sentence itself, so the only thing that can
 * ever be rendered is the constant above. History state is same-origin-writable
 * and passing a string would make it a place to put words on our login screen.
 */
export function wasPasswordChanged(location: Pick<Location, "state">): boolean {
  const state = location.state as AuthNoticeState | null;
  return state?.passwordChanged === true;
}

/** Whether the login page should show the password-reset notice. Same booleans-
 *  only rule as above, for the same reason. */
export function wasPasswordReset(location: Pick<Location, "state">): boolean {
  const state = location.state as AuthNoticeState | null;
  return state?.passwordReset === true;
}
