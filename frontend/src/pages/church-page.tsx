import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { fetchSession, rotateJoinCode, type Session } from "../api/session";
import { alertMessageOf, type ApiError } from "../lib/api-error";
import JoinCodeDisplay from "../components/join-code-display";
import { Alert, AlertDescription, AlertTitle } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";

const ROTATE_CONFIRM_MESSAGE =
  "초대 코드를 재발급하면 지금 코드는 즉시 사용할 수 없습니다. 계속할까요?";

/**
 * The leader's view of their church invite code: read it, copy it, replace it.
 *
 * The code is fetched from /auth/me rather than kept from signup, so a leader
 * who comes back tomorrow — or who has rotated it since — sees the one that
 * actually works. The server is the gate on all three actions; this page only
 * decides what is worth offering.
 */
export default function ChurchPage() {
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRotating, setIsRotating] = useState(false);
  const [apiError, setApiError] = useState<ApiError | null>(null);

  useEffect(() => {
    let active = true;
    fetchSession().then((loaded) => {
      // The request outlived the page; setting state now would be a write to a
      // component nobody is looking at.
      if (!active) return;
      setSession(loaded);
      setIsLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);

  const handleRotate = async () => {
    if (isRotating) return;
    // Irreversible and immediate: everyone holding the old code loses access
    // the moment this succeeds, so it is worth one deliberate confirmation.
    if (!window.confirm(ROTATE_CONFIRM_MESSAGE)) return;

    setApiError(null);
    setIsRotating(true);
    const outcome = await rotateJoinCode();
    setIsRotating(false);

    if (!outcome.ok) {
      setApiError(outcome.error);
      return;
    }
    setSession((previous) => (previous ? { ...previous, churchCode: outcome.code } : previous));
  };

  const alertMessage = alertMessageOf(apiError);

  return (
    <div className="flex min-h-screen items-center justify-center bg-white px-4 text-stone-900 sm:px-6 lg:px-8">
      <div className="mx-auto w-full max-w-md">
        <Card className="border-stone-200">
          <CardContent className="space-y-4 pt-6">
            <div className="space-y-1">
              <h1 id="church-code-label" className="text-[15px] font-medium text-stone-800">
                교회 초대 코드
              </h1>
              {session?.churchName ? (
                <p className="text-[12px] text-stone-500">{session.churchName}</p>
              ) : null}
            </div>

            {isLoading ? (
              <p className="text-[12px] text-stone-500">불러오는 중...</p>
            ) : session?.churchCode ? (
              <>
                <JoinCodeDisplay code={session.churchCode} labelledBy="church-code-label" />
                <p className="text-[12px] text-stone-500">
                  이 코드를 가진 사람은 누구나 교회에 가입할 수 있습니다. 외부에 노출됐다면 재발급해
                  주세요.
                </p>
                {alertMessage ? (
                  <Alert variant="destructive">
                    <AlertTitle>재발급 실패</AlertTitle>
                    <AlertDescription>{alertMessage}</AlertDescription>
                  </Alert>
                ) : null}
                <Button
                  type="button"
                  variant="outline"
                  className="w-full"
                  onClick={handleRotate}
                  disabled={isRotating}
                >
                  {isRotating ? "재발급 중..." : "초대 코드 재발급"}
                </Button>
              </>
            ) : (
              // Covers both a member and an unreadable session: neither has a
              // code to show, and neither can act on the difference.
              <p className="text-[12px] text-stone-500">
                초대 코드는 교회 리더만 확인할 수 있습니다.
              </p>
            )}

            <p className="text-center text-[12px] text-stone-500">
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
