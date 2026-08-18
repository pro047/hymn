import { useState, type ChangeEvent, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { confirmPasswordReset, INVALID_LINK_MESSAGE } from "../api/password-reset";
import { alertMessageOf, clearFieldErrors, toFormError, type ApiError } from "../lib/api-error";
import {
  FIELDS_SETTLED_TOGETHER,
  PASSWORD_RULE_HINT,
  passwordResetFormSchema,
  toValidationError,
} from "../lib/validation/auth-schema";
import { Alert, AlertDescription, AlertTitle } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

/**
 * Sets a new password from a mailed link.
 *
 * The token arrives in the query string because a link is the only way to carry
 * it, but it is submitted in the POST body — a token in a URL ends up in access
 * logs, Referer headers and browser history, and the whole point of it is that
 * only the mailbox owner has it. The successful navigation below uses `replace`
 * for the same reason: it drops the tokened URL out of history.
 *
 * The page is deliberately reachable while signed in. The mail is read wherever
 * the user reads mail, which may be a browser with a live session, and someone
 * who has forgotten their password cannot use /account — that form asks for the
 * password they have forgotten.
 */
export default function ResetPasswordPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  // Presence is all that is checked. The server bounds the length; copying that
  // bound here could only ever refuse a token the server would have taken.
  // Trimmed first: a mail client that wraps the URL can leave `?token=%20`,
  // which is not a token but would sail past an untrimmed emptiness check and
  // be submitted as whitespace.
  const token = (searchParams.get("token") ?? "").trim();

  const [newPassword, setNewPassword] = useState("");
  const [newPasswordConfirm, setNewPasswordConfirm] = useState("");
  const [apiError, setApiError] = useState<ApiError | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const fieldErrors = apiError?.fieldErrors ?? {};
  const alertMessage = alertMessageOf(apiError);

  const handleFieldChange =
    (field: string, setValue: (value: string) => void) =>
    (event: ChangeEvent<HTMLInputElement>) => {
      setValue(event.target.value);
      setApiError((previous) =>
        clearFieldErrors(previous, [field, ...(FIELDS_SETTLED_TOGETHER[field] ?? [])])
      );
    };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSubmitting) return;

    const parsed = passwordResetFormSchema.safeParse({
      token,
      new_password: newPassword,
      new_password_confirm: newPasswordConfirm,
    });
    if (!parsed.success) {
      setApiError(toValidationError(parsed.error));
      return;
    }

    setApiError(null);
    setIsSubmitting(true);
    try {
      const outcome = await confirmPasswordReset({
        token: parsed.data.token,
        new_password: parsed.data.new_password,
      });

      if (!outcome.ok) {
        // A 401 stays on this page as a readable sentence. It reaches here at
        // all only because confirmPasswordReset uses plain fetch — apiFetch
        // would have read it as an expired access token and navigated away.
        setApiError(outcome.error);
        return;
      }

      // confirmPasswordReset has already cleared any session in this browser.
      navigate("/login", { replace: true, state: { passwordReset: true } });
    } catch {
      setApiError(toFormError("요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요."));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-white px-4 text-stone-900 sm:px-6 lg:px-8">
      <div className="mx-auto w-full max-w-md">
        <Card className="border-stone-200">
          <CardContent className="pt-6">
            <h1 className="mb-4 text-[15px] font-medium text-stone-800">새 비밀번호 설정</h1>

            {token === "" ? (
              // No form at all rather than a disabled one: every field on it
              // would be work the user cannot submit.
              <Alert variant="destructive">
                <AlertTitle>링크가 올바르지 않습니다</AlertTitle>
                <AlertDescription>{INVALID_LINK_MESSAGE}</AlertDescription>
              </Alert>
            ) : (
              <form className="space-y-4" onSubmit={handleSubmit}>
                <div className="space-y-2">
                  <Label htmlFor="new-password" className="text-stone-500">
                    새 비밀번호
                  </Label>
                  <Input
                    id="new-password"
                    type="password"
                    value={newPassword}
                    onChange={handleFieldChange("new_password", setNewPassword)}
                    autoComplete="new-password"
                    aria-invalid={Boolean(fieldErrors.new_password)}
                    aria-describedby={
                      fieldErrors.new_password ? "new-password-error" : "new-password-hint"
                    }
                  />
                  {fieldErrors.new_password ? (
                    <p id="new-password-error" className="text-[12px] text-red-500">
                      {fieldErrors.new_password}
                    </p>
                  ) : (
                    <p id="new-password-hint" className="text-[12px] text-stone-500">
                      {PASSWORD_RULE_HINT}
                    </p>
                  )}
                </div>

                <div className="space-y-2">
                  <Label htmlFor="new-password-confirm" className="text-stone-500">
                    새 비밀번호 확인
                  </Label>
                  <Input
                    id="new-password-confirm"
                    type="password"
                    value={newPasswordConfirm}
                    onChange={handleFieldChange("new_password_confirm", setNewPasswordConfirm)}
                    autoComplete="new-password"
                    aria-invalid={Boolean(fieldErrors.new_password_confirm)}
                    aria-describedby={
                      fieldErrors.new_password_confirm ? "new-password-confirm-error" : undefined
                    }
                  />
                  {fieldErrors.new_password_confirm ? (
                    <p id="new-password-confirm-error" className="text-[12px] text-red-500">
                      {fieldErrors.new_password_confirm}
                    </p>
                  ) : null}
                </div>

                {alertMessage ? (
                  <Alert variant="destructive">
                    <AlertTitle>재설정 실패</AlertTitle>
                    <AlertDescription>{alertMessage}</AlertDescription>
                  </Alert>
                ) : null}

                <p className="text-[12px] text-stone-500">
                  재설정하면 모든 기기에서 로그아웃되고, 새 비밀번호로 다시 로그인해야 합니다.
                </p>

                <Button type="submit" className="w-full" disabled={isSubmitting}>
                  {isSubmitting ? "재설정 중..." : "비밀번호 재설정"}
                </Button>
              </form>
            )}

            <p className="mt-4 text-center text-[12px] text-stone-500">
              <Link
                to="/forgot-password"
                className="font-medium text-stone-700 underline underline-offset-2"
              >
                재설정 링크 다시 받기
              </Link>
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
