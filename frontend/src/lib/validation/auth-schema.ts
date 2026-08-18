/**
 * SOURCE OF TRUTH: backend/src/app/schemas/auth.py
 *
 * This is a deliberate copy, not a derivation — the server re-validates everything
 * and its answer wins. The copy exists so a user learns what is wrong without a
 * round trip. Loosening a rule here therefore only produces a 422; tightening one
 * locks out input the server would have accepted. Change both files together.
 *
 * Parity cases are pinned in ./auth-schema.test.ts and mirrored by
 * backend/tests/test_auth_signup.py.
 */
import { z } from "zod";

import type { ApiError } from "../api-error";
import { normalizeChurchName } from "../church-check";

// Mirrors the module-level constants in backend/src/app/schemas/auth.py.
const PASSWORD_MIN_LENGTH = 8;
const PASSWORD_MAX_LENGTH = 16;
const LOGIN_PASSWORD_MAX_LENGTH = 128;
const NAME_MAX_LENGTH = 255;
const PHONE_MIN_LENGTH = 8;
const PHONE_MAX_LENGTH = 32;
const JOIN_CODE_MAX_LENGTH = 16;

// Worded to match what api-error.ts renders for the equivalent server rejection,
// so the same mistake reads the same whether it was caught here or at the server.
const REQUIRED_MESSAGE = "필수 입력 항목입니다.";
const PASSWORD_CASE_MESSAGE = "영문 대문자와 소문자를 모두 포함해야 합니다.";
const AGREED_TERMS_MESSAGE = "약관 동의가 필요합니다.";
const PASSWORD_MISMATCH_MESSAGE = "비밀번호가 일치하지 않습니다.";
// Mirrors PASSWORD_UNCHANGED_MESSAGE in schemas/auth.py. The server files this
// one against the model rather than a field, because it is cross-field there
// too; checking it here is what puts it under the input the user has to change.
const PASSWORD_UNCHANGED_MESSAGE = "새 비밀번호가 현재 비밀번호와 같습니다.";
// Shorter than the hint under the church field, which explains *why* a code is
// being asked for. Repeating that whole sentence under the input would put the
// same words on screen twice with no way to tell which one is the error.
export const JOIN_CODE_REQUIRED_MESSAGE = "초대 코드를 입력해 주세요.";

const tooShortMessage = (min: number) => `최소 ${min}자 이상 입력해 주세요.`;
const tooLongMessage = (max: number) => `최대 ${max}자까지 입력할 수 있습니다.`;

// `.trim()` runs before the length checks, so a field of nothing but spaces is
// rejected here rather than passing min_length and reaching the server as "".
// The parsed output is what gets sent, which keeps "what was validated" and
// "what was submitted" from drifting apart.
const requiredText = (max: number) =>
  z.string().trim().min(1, REQUIRED_MESSAGE).max(max, tooLongMessage(max));

// Both forms check only that something was typed. Any format rule here risks
// being stricter than EmailStr somewhere: on login that costs an account (the
// request is never sent and there is no password reset to recover through), on
// signup it costs a registration the server would have accepted. A malformed
// address is the server's 422 to answer.
//
// zod's own email pattern is not gone, it is demoted — lib/email-check.ts reuses
// it to decide when an address is worth a duplicate lookup, where being strict
// only skips a convenience.
const emailField = z.string().trim().toLowerCase().pipe(z.string().min(1, REQUIRED_MESSAGE));

// Counts code points the way Python len() does. pydantic's min/max_length count
// code points while JS .length counts UTF-16 code units, so an astral character
// (an emoji) weighs 2 here and 1 on the server. Counting units made this side
// up to twice as strict: a password the server accepted at signup could be
// refused here and never even sent — and on login there is no reset to recover
// through.
const codePointLength = (value: string) => [...value].length;

const passwordLengthChecks = (max: number) =>
  z
    .string()
    .refine((value) => codePointLength(value) >= PASSWORD_MIN_LENGTH, {
      message: tooShortMessage(PASSWORD_MIN_LENGTH),
    })
    .refine((value) => codePointLength(value) <= max, { message: tooLongMessage(max) });

// A password being set. Mirrors the NewPassword type in schemas/auth.py, and is
// shared by signup and the change form for the reason the server shares
// validate_password_strength: two gates on the same thing drift, and the drift
// would let one screen set a password the other would have refused.
const newPasswordField = z
  .string()
  .regex(/[a-z]/, PASSWORD_CASE_MESSAGE)
  .regex(/[A-Z]/, PASSWORD_CASE_MESSAGE)
  .pipe(passwordLengthChecks(PASSWORD_MAX_LENGTH));

/** The exact body POST /auth/signup accepts. Keep 1:1 with SignupRequest. */
export const signupSchema = z.object({
  name: requiredText(NAME_MAX_LENGTH),
  email: emailField,
  password: newPasswordField,
  // Same normalization the lookup cache keys by and the server stores (NFC,
  // invisibles stripped) — mirrors ChurchName in schemas/auth.py. Without it
  // the submitted spelling could miss the row the lookup just said exists.
  church: z.string().transform(normalizeChurchName).pipe(requiredText(NAME_MAX_LENGTH)),
  // Optional here because founding a church is issued a code rather than asked
  // for one. Whether it is required for *this* signup depends on whether the
  // church already exists, which only the server knows — the refine below reads
  // that answer off the form, and a 403 is the last word either way.
  // Lowercased to match the generated alphabet, so a phone keyboard's automatic
  // capital is not a wrong code.
  join_code: z
    .string()
    .trim()
    .toLowerCase()
    .max(JOIN_CODE_MAX_LENGTH, tooLongMessage(JOIN_CODE_MAX_LENGTH))
    .optional(),
  church_address: requiredText(NAME_MAX_LENGTH),
  phone: z
    .string()
    .trim()
    .min(PHONE_MIN_LENGTH, tooShortMessage(PHONE_MIN_LENGTH))
    .max(PHONE_MAX_LENGTH, tooLongMessage(PHONE_MAX_LENGTH)),
  agreed_terms: z.literal(true, AGREED_TERMS_MESSAGE),
});

/**
 * What the signup form gates on. `password_confirm` and `church_is_registered`
 * have no server counterpart — they live here rather than as separate booleans
 * in the page so the form has exactly one gate and every field reports through
 * the same channel.
 *
 * `church_is_registered` is what the church lookup answered. It is an input to
 * the gate rather than a rule of its own because the requirement it creates is
 * conditional: the same empty code is fine when founding a church and wrong
 * when joining one, and only the lookup can tell those apart.
 */
export const signupFormSchema = signupSchema
  .extend({ password_confirm: z.string(), church_is_registered: z.boolean() })
  .refine((values) => values.password === values.password_confirm, {
    message: PASSWORD_MISMATCH_MESSAGE,
    path: ["password_confirm"],
  })
  .refine((values) => !values.church_is_registered || Boolean(values.join_code), {
    message: JOIN_CODE_REQUIRED_MESSAGE,
    path: ["join_code"],
  });

/**
 * Fields whose error the key field also settles.
 *
 * `refine` files its message under a single `path`, so the mismatch above lands
 * on `password_confirm` alone even though `password` is half of the comparison.
 * Without this map, fixing the mismatch from the `password` side leaves the
 * message — and `aria-invalid` — on a field that is now correct.
 *
 * Declared beside the rule that creates the pairing rather than in the page, so
 * that changing the `path` above and forgetting this stays a one-file mistake.
 */
export const FIELDS_SETTLED_TOGETHER: Readonly<Record<string, readonly string[]>> = {
  password: ["password_confirm"],
  password_confirm: ["password"],
  // Same shape: the missing-code message is filed under `join_code`, but
  // retyping the church name is the other way to settle it — a name that is not
  // registered needs no code at all, so leaving the message up would demand
  // something the form is no longer asking for.
  church: ["join_code"],
  join_code: ["church"],
  // The password change form's two refines, same shape again. "Must differ" is
  // filed under `new_password`, but editing `current_password` settles it just
  // as well — that is the other half of the comparison.
  new_password: ["new_password_confirm", "current_password"],
  new_password_confirm: ["new_password"],
  current_password: ["new_password"],
};

/** Shown under the password input at all times, so the rules do not have to be
 *  discovered one rejected submit at a time. Built from the constants above so
 *  it cannot drift from what the schema actually enforces. */
export const PASSWORD_RULE_HINT =
  `${PASSWORD_MIN_LENGTH}~${PASSWORD_MAX_LENGTH}자, ` + PASSWORD_CASE_MESSAGE;

// A password being offered as proof, not being set. The 128-char cap and the
// absence of strength rules are deliberate and mirror CurrentPassword on the
// server: a rule on this side locks out accounts that predate it — which is
// also why the cap counts code points like the server does, not UTF-16 units.
const currentPasswordField = passwordLengthChecks(LOGIN_PASSWORD_MAX_LENGTH);

/**
 * Still looser than signup in one field: the 128-char password cap exists so
 * that accounts created before the 16-char signup rule can sign in.
 */
export const loginSchema = z.object({
  email: emailField,
  password: currentPasswordField,
});

/** The exact body POST /auth/password accepts. Keep 1:1 with PasswordChangeRequest. */
export const passwordChangeSchema = z.object({
  current_password: currentPasswordField,
  new_password: newPasswordField,
});

/**
 * What the change form gates on. `new_password_confirm` has no server
 * counterpart and follows the `password_confirm` precedent — one gate, every
 * field reporting through the same channel.
 *
 * The "must differ" rule is checked here as well as on the server, and the
 * duplication buys placement rather than safety: the server's copy is a
 * model_validator, so its message arrives with no field attached and renders as
 * an alert. Filed under `new_password` here, it sits under the box the user has
 * to retype.
 */
export const passwordChangeFormSchema = passwordChangeSchema
  .extend({ new_password_confirm: z.string() })
  .refine((values) => values.new_password === values.new_password_confirm, {
    message: PASSWORD_MISMATCH_MESSAGE,
    path: ["new_password_confirm"],
  })
  .refine((values) => values.new_password !== values.current_password, {
    message: PASSWORD_UNCHANGED_MESSAGE,
    path: ["new_password"],
  });

/** The exact body POST /auth/password-reset/request accepts. 1:1 with PasswordResetRequest. */
export const passwordResetRequestSchema = z.object({ email: emailField });

/**
 * The exact body POST /auth/password-reset/confirm accepts. Keep 1:1 with
 * PasswordResetConfirm.
 *
 * The token is checked for presence and nothing else, deliberately unlike the
 * server's 16..256 bound. It arrives from a link rather than from typing, so a
 * length rule here could only ever reject a token the server would have
 * accepted — and the one case that produces is the server changing how long a
 * token is, which would then be refused on this side before it was ever sent.
 * `new_password` reuses the signup field for the reason the server reuses
 * NewPassword: two gates on the same thing drift apart.
 */
export const passwordResetSchema = z.object({
  token: z.string().trim().min(1, REQUIRED_MESSAGE),
  new_password: newPasswordField,
});

/**
 * What the reset form gates on. Same shape as the change form minus
 * `current_password` — a reset proves identity with the mailed link instead, so
 * there is no old password to ask for and nothing to compare against.
 *
 * The `FIELDS_SETTLED_TOGETHER` entries above already cover this form: the
 * `current_password` name they list is simply absent here, and clearing a field
 * that carries no error is a no-op.
 */
export const passwordResetFormSchema = passwordResetSchema
  .extend({ new_password_confirm: z.string() })
  .refine((values) => values.new_password === values.new_password_confirm, {
    message: PASSWORD_MISMATCH_MESSAGE,
    path: ["new_password_confirm"],
  });

export type SignupBody = z.infer<typeof signupSchema>;
export type LoginBody = z.infer<typeof loginSchema>;
export type PasswordChangeBody = z.infer<typeof passwordChangeSchema>;
export type PasswordResetRequestBody = z.infer<typeof passwordResetRequestSchema>;
export type PasswordResetBody = z.infer<typeof passwordResetSchema>;

/**
 * Reshapes zod issues into the same {@link ApiError} the server path produces, so
 * the pages render one error model instead of two.
 *
 * `status: 0` marks "never reached the server", matching `toFormError`.
 */
export function toValidationError(error: z.ZodError): ApiError {
  const fieldErrors: Record<string, string> = {};
  const formLines: string[] = [];

  for (const issue of error.issues) {
    const field = issue.path[0];
    // A schema-level issue (no path) has no field to sit under.
    if (typeof field !== "string") {
      formLines.push(issue.message);
      continue;
    }
    // First issue per field wins; a second one would only overwrite the message
    // the user is already reading. Mirrors fromValidationItems() in api-error.ts.
    if (!(field in fieldErrors)) fieldErrors[field] = issue.message;
  }

  return { status: 0, formError: formLines.join(" "), fieldErrors };
}
