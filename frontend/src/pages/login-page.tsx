import { useState, type ChangeEvent, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { requestAuth } from "../api/auth";
import { API_PATHS } from "../api/paths";
import { alertMessageOf, clearFieldError, toFormError, type ApiError } from "../lib/api-error";
import {
  PASSWORD_CHANGED_NOTICE,
  PASSWORD_RESET_NOTICE,
  wasPasswordChanged,
  wasPasswordReset,
} from "../lib/auth-notice";
import { setTokens } from "../lib/auth-storage";
import { loginSchema, toValidationError } from "../lib/validation/auth-schema";
import { Alert, AlertDescription, AlertTitle } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

// Backend field names this form renders inline; anything else lands in the alert.
const RENDERED_FIELDS = ["email", "password"] as const;

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  // Set by the account or reset page, each of which ends its own session and so
  // cannot show the confirmation itself. Read once at render: it describes how
  // the user arrived, not anything they do from here. Only one can ever be set —
  // they are written by different pages on different navigations.
  const noticeMessage = wasPasswordReset(location)
    ? PASSWORD_RESET_NOTICE
    : wasPasswordChanged(location)
      ? PASSWORD_CHANGED_NOTICE
      : "";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [apiError, setApiError] = useState<ApiError | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const fieldErrors = apiError?.fieldErrors ?? {};
  const alertMessage = alertMessageOf(apiError);

  const handleFieldChange =
    (field: string, setValue: (value: string) => void) =>
    (event: ChangeEvent<HTMLInputElement>) => {
      setValue(event.target.value);
      setApiError((previous) => clearFieldError(previous, field));
    };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSubmitting) return;

    // Mirrors LoginRequest, so a malformed address never costs a round trip. The
    // 128-char cap here is wider than signup's on purpose — see auth-schema.ts.
    const parsed = loginSchema.safeParse({ email, password });
    if (!parsed.success) {
      setApiError(toValidationError(parsed.error));
      return;
    }

    setApiError(null);
    setIsSubmitting(true);
    try {
      const outcome = await requestAuth({
        url: API_PATHS.authLogin,
        body: parsed.data,
        failureMessage: "로그인에 실패했습니다.",
        unreadableMessage: "로그인 응답을 읽지 못했습니다. 잠시 후 다시 시도해 주세요.",
        renderedFields: RENDERED_FIELDS,
      });

      if (!outcome.ok) {
        setApiError(outcome.error);
        return;
      }

      setTokens(outcome.tokens);
      navigate("/", { replace: true });
    } catch {
      // requestAuth already classified every request failure; anything left is
      // local (a blocked localStorage write), so it must not blame the network.
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
            {noticeMessage ? (
              <Alert className="mb-4">
                <AlertTitle>변경 완료</AlertTitle>
                <AlertDescription>{noticeMessage}</AlertDescription>
              </Alert>
            ) : null}
            <p className="mb-4 text-center text-lg font-normal text-stone-300">H Y M N</p>
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
                  onChange={handleFieldChange("email", setEmail)}
                  autoComplete="email"
                  aria-invalid={Boolean(fieldErrors.email)}
                  aria-describedby={fieldErrors.email ? "email-error" : undefined}
                />
                {fieldErrors.email ? (
                  <p id="email-error" className="text-[12px] text-red-500">
                    {fieldErrors.email}
                  </p>
                ) : null}
              </div>

              <div className="space-y-2">
                <Label htmlFor="password" className="text-stone-500">
                  비밀번호
                </Label>
                <Input
                  id="password"
                  type="password"
                  placeholder="비밀번호"
                  value={password}
                  onChange={handleFieldChange("password", setPassword)}
                  autoComplete="current-password"
                  aria-invalid={Boolean(fieldErrors.password)}
                  aria-describedby={fieldErrors.password ? "password-error" : undefined}
                />
                {fieldErrors.password ? (
                  <p id="password-error" className="text-[12px] text-red-500">
                    {fieldErrors.password}
                  </p>
                ) : null}
              </div>

              <p className="mt-4 text-center text-[12px] text-stone-500">
                <Link
                  to="/forgot-password"
                  className="font-medium text-stone-700 underline underline-offset-2"
                >
                  비밀번호를 잊으셨나요?
                </Link>
              </p>

              <p className="my-8 text-center text-[12px] text-stone-500">
                계정이 없으신가요?{" "}
                <Link
                  to="/signup"
                  className="font-medium text-stone-700 underline underline-offset-2"
                >
                  회원가입
                </Link>
              </p>

              {alertMessage ? (
                <Alert variant="destructive">
                  <AlertTitle>로그인 실패</AlertTitle>
                  <AlertDescription>{alertMessage}</AlertDescription>
                </Alert>
              ) : null}

              <Button type="submit" className="w-full" disabled={isSubmitting}>
                {isSubmitting ? "로그인 중..." : "로그인"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
