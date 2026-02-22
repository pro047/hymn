import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { API_PATHS } from "../api/paths";
import { Alert, AlertDescription, AlertTitle } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";

export default function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const canSubmit = email.trim() && password;

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!canSubmit || isSubmitting) return;

    setError("");
    setIsSubmitting(true);
    try {
      const response = await fetch(API_PATHS.authLogin, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email.trim().toLowerCase(),
          password,
        }),
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail || "로그인에 실패했습니다.");
      }

      const payload = await response.json();
      const accessToken = payload?.tokens?.access_token;
      const refreshToken = payload?.tokens?.refresh_token;
      if (!accessToken || !refreshToken) {
        throw new Error("토큰 응답이 올바르지 않습니다.");
      }

      localStorage.setItem("hymn_access_token", accessToken);
      localStorage.setItem("hymn_refresh_token", refreshToken);
      navigate("/", { replace: true });
    } catch (submitError) {
      setError(submitError.message || "로그인 처리 중 오류가 발생했습니다.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-white px-4 text-stone-900 sm:px-6 lg:px-8">
      <div className="mx-auto w-full max-w-md">
        <Card className="border-stone-200">
          <CardContent className="pt-6">
            <p className="mb-4 text-center text-lg font-normal text-stone-300">
              H Y M N
            </p>
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
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="email"
                />
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
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="current-password"
                />
              </div>

              <p className="my-8 text-center text-[12px] text-stone-500">
                계정이 없으신가요?{" "}
                <Link
                  to="/signup"
                  className="font-medium text-stone-700 underline underline-offset-2"
                >
                  회원가입
                </Link>
              </p>

              {error ? (
                <Alert variant="destructive">
                  <AlertTitle>로그인 실패</AlertTitle>
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              ) : null}

              <Button
                type="submit"
                className="w-full"
                disabled={!canSubmit || isSubmitting}
              >
                {isSubmitting ? "로그인 중..." : "로그인"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
