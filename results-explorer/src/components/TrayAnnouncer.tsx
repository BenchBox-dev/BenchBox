import { useEffect, useRef, useState } from "preact/hooks";

interface TrayAnnouncerProps {
  count: number;
}

export function TrayAnnouncer({ count }: TrayAnnouncerProps) {
  const [announcement, setAnnouncement] = useState("");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isInitialMount = useRef(true);

  useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false;
      if (count === 0) return;
    }
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      if (count === 0) setAnnouncement("No results selected");
      else if (count === 1) setAnnouncement("1 result selected. Select one more to compare.");
      else setAnnouncement(`${count} results selected. Ready to compare.`);
    }, 180);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [count]);

  return (
    <div
      aria-live="polite"
      aria-atomic="true"
      style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap"
      data-testid="compare-tray-announcer"
      role="status"
    >
      {announcement}
    </div>
  );
}
