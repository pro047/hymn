import { useEffect, useState } from "react";

import { msUntilNextWeek, upcomingSundayOf } from "../../../lib/dates";

// The coming Sunday, kept current while the page stays open. It only changes
// at Monday 00:00, so one timer aimed at that moment does the work instead of
// polling. A sleeping device can hold that timer past midnight, which is why a
// return to the page recomputes too.
export function useUpcomingSunday() {
  const [weekOf, setWeekOf] = useState(() => upcomingSundayOf());

  useEffect(() => {
    let timer;

    const refresh = () => {
      clearTimeout(timer);
      setWeekOf(upcomingSundayOf());
      timer = setTimeout(refresh, msUntilNextWeek());
    };

    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") refresh();
    };

    timer = setTimeout(refresh, msUntilNextWeek());
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, []);

  return weekOf;
}
