import { useState, type ChangeEvent, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { changePassword } from "../api/password";
import { alertMessageOf, clearFieldErrors, toFormError, type ApiError } from "../lib/api-error";
import {
  FIELDS_SETTLED_TOGETHER,
  PASSWORD_RULE_HINT,
  passwordChangeFormSchema,
  toValidationError,
} from "../lib/validation/auth-schema";
import { Alert, AlertDescription, AlertTitle } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

/**
 * The account screen: today it does one thing, change the password.
 *
 * Not folded into the church management page, which is leader-only — a member
 * has a password too. The server is the gate on everything here; this page only
 * spares the user a round trip for mistakes it can already see.
 *
 * A successful change ends every session including this one, so the page does
 * not show a confirmation — it navigates to /login and lets that screen say so.
 * Anything rendered here would be gone before it could be read.
 */
export default function AccountPage() {
  const navigate = useNavigate();
  const [currentPassword, setCurrentPassword] = useState("");
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
      // Also clears the fields this one settles: a refine files its message
      // under a single path, so editing the other half of the comparison would
      // otherwise leave a message on input that is now correct.
      setApiError((previous) =>
        clearFieldErrors(previous, [field, ...(FIELDS_SETTLED_TOGETHER[field] ?? [])])
      );
    };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSubmitting) return;

    const parsed = passwordChangeFormSchema.safeParse({
      current_password: currentPassword,
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
      const outcome = await changePassword({
        current_password: parsed.data.current_password,
        new_password: parsed.data.new_password,
      });

      if (!outcome.ok) {
        // Nothing is cleared here: after a failure the three fields are what the
        // user is about to correct, and wiping them would make a typo in one
        // cost all three.
        setApiError(outcome.error);
        return;
      }

      // changePassword has already dropped the tokens, so this navigation lands
      // on the login form rather than bouncing back home. `replace` keeps Back
      // from returning to a form whose session no longer exists.
      navigate("/login", { replace: true, state: { passwordChanged: true } });
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
            <h1 className="mb-4 text-[15px] font-medium text-stone-800">비밀번호 변경</h1>
            <form className="space-y-4" onSubmit={handleSubmit}>
              <div className="space-y-2">
                <Label htmlFor="current-password" className="text-stone-500">
                  현재 비밀번호
                </Label>
                <Input
                  id="current-password"
                  type="password"
                  value={currentPassword}
                  onChange={handleFieldChange("current_password", setCurrentPassword)}
                  autoComplete="current-password"
                  aria-invalid={Boolean(fieldErrors.current_password)}
                  aria-describedby={
                    fieldErrors.current_password ? "current-password-error" : undefined
                  }
                />
                {fieldErrors.current_password ? (
                  <p id="current-password-error" className="text-[12px] text-red-500">
                    {fieldErrors.current_password}
                  </p>
                ) : null}
              </div>

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
                  // Shown at all times rather than after a rejection, so the
                  // rules do not have to be discovered one submit at a time.
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
                  <AlertTitle>변경 실패</AlertTitle>
                  <AlertDescription>{alertMessage}</AlertDescription>
                </Alert>
              ) : null}

              <p className="text-[12px] text-stone-500">
                변경하면 모든 기기에서 로그아웃되고, 새 비밀번호로 다시 로그인해야 합니다.
              </p>

              <Button type="submit" className="w-full" disabled={isSubmitting}>
                {isSubmitting ? "변경 중..." : "비밀번호 변경"}
              </Button>
            </form>

            <p className="mt-4 text-center text-[12px] text-stone-500">
              <Link to="/" className="font-medium text-stone-700 underline underline-offset-2">
                홈으로
              </Link>
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
