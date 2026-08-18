import { useState, type ChangeEvent, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { requestPasswordReset } from "../api/password-reset";
import { clearFieldError, toFormError, type ApiError } from "../lib/api-error";
import { passwordResetRequestSchema, toValidationError } from "../lib/validation/auth-schema";
import { Alert, AlertDescription, AlertTitle } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

/**
 * Says the same thing whether or not the address belongs to an account.
 *
 * The server's half of that promise is answering 202 for every address; this is
 * the other half. "메일을 보냈습니다" would confirm the account exists to anyone
 * who typed the address, which is exactly the unauthenticated oracle the 202 was
 * shaped to avoid — the copy has to stay conditional even though it reads a
 * little more awkwardly than the truthful-sounding version.
 */
export const RESET_REQUESTED_MESSAGE =
  "해당 주소로 가입된 계정이 있다면 재설정 링크를 보냈습니다. 30분 안에 링크를 열어 주세요.";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [apiError, setApiError] = useState<ApiError | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Not derived from `apiError === null`: that is also the state before the
  // first submit, and the form would announce success on arrival.
  const [isRequested, setIsRequested] = useState(false);

  const fieldErrors = apiError?.fieldErrors ?? {};
  // `formError` directly, not alertMessageOf(): that helper falls back to a
  // generic "check your input" line whenever any field error exists, which
  // earns its place on a long form where the offending field may be off screen.
  // This form has one field and its message is two lines above the alert, so
  // the summary only says the same thing twice. What is left for the alert is
  // what has no field to sit under — a rate limit, a 404, a dead network.
  const alertMessage = apiError?.formError ?? "";

  const handleEmailChange = (event: ChangeEvent<HTMLInputElement>) => {
    setEmail(event.target.value);
    setApiError((previous) => clearFieldError(previous, "email"));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSubmitting) return;

    const parsed = passwordResetRequestSchema.safeParse({ email });
    if (!parsed.success) {
      setApiError(toValidationError(parsed.error));
      return;
    }

    setApiError(null);
    setIsSubmitting(true);
    try {
      const outcome = await requestPasswordReset(parsed.data);
      if (!outcome.ok) {
        // A 429 lands here and keeps the form on screen, which is correct: the
        // limit is 5/hour and the user needs to read why nothing happened.
        setApiError(outcome.error);
        return;
      }
      setIsRequested(true);
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
            <h1 className="mb-4 text-[15px] font-medium text-stone-800">비밀번호 재설정</h1>

            {isRequested ? (
              // The form is replaced rather than disabled: leaving it up invites
              // a second submit that would spend one of the five hourly slots
              // for no reason.
              <Alert>
                <AlertTitle>메일을 확인해 주세요</AlertTitle>
                <AlertDescription>{RESET_REQUESTED_MESSAGE}</AlertDescription>
              </Alert>
            ) : (
              <form className="space-y-4" onSubmit={handleSubmit}>
                <div className="space-y-2">
                  <Label htmlFor="email" className="text-stone-500">
                    이메일
                  </Label>
                  <Input
                    id="email"
                    type="email"
                    placeholder="you@church.org"
                    value={email}
                    onChange={handleEmailChange}
                    autoComplete="email"
                    aria-invalid={Boolean(fieldErrors.email)}
                    aria-describedby={fieldErrors.email ? "email-error" : "email-hint"}
                  />
                  {fieldErrors.email ? (
                    <p id="email-error" className="text-[12px] text-red-500">
                      {fieldErrors.email}
                    </p>
                  ) : (
                    <p id="email-hint" className="text-[12px] text-stone-500">
                      가입할 때 사용한 이메일 주소를 입력해 주세요.
                    </p>
                  )}
                </div>

                {alertMessage ? (
                  <Alert variant="destructive">
                    <AlertTitle>요청 실패</AlertTitle>
                    <AlertDescription>{alertMessage}</AlertDescription>
                  </Alert>
                ) : null}

                <Button type="submit" className="w-full" disabled={isSubmitting}>
                  {isSubmitting ? "전송 중..." : "재설정 링크 받기"}
                </Button>
              </form>
            )}

            <p className="mt-4 text-center text-[12px] text-stone-500">
              <Link to="/login" className="font-medium text-stone-700 underline underline-offset-2">
                로그인으로 돌아가기
              </Link>
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
