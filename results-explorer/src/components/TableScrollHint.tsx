import type { JSX, RefObject } from "preact";
import { useLayoutEffect, useState } from "preact/hooks";

export interface TableScrollHintProps {
  scrollerRef: RefObject<HTMLElement>;
  label?: string;
  testId?: string;
  className?: string;
  wrapperClassName?: string | null;
}

const DEFAULT_LABEL = "← scroll →";
const DEFAULT_WRAPPER_CLASS = "mb-2 flex justify-end";

export function TableScrollHint({
  scrollerRef,
  label = DEFAULT_LABEL,
  testId,
  className = "",
  wrapperClassName = DEFAULT_WRAPPER_CLASS,
}: TableScrollHintProps): JSX.Element | null {
  const [hasOverflow, setHasOverflow] = useState(false);

  useLayoutEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;

    const measure = () => setHasOverflow(scroller.scrollWidth > scroller.clientWidth);
    measure();

    const observer = new ResizeObserver(measure);
    observer.observe(scroller);
    if (scroller.firstElementChild instanceof HTMLElement) observer.observe(scroller.firstElementChild);
    return () => observer.disconnect();
  }, [scrollerRef]);

  if (!hasOverflow) return null;
  const spanClass = `bb-scroll-affordance${className === "" ? "" : ` ${className}`}`;
  const span = (
    <span class={spanClass} data-testid={testId}>
      {label}
    </span>
  );
  if (wrapperClassName === null) return span;
  return <div class={wrapperClassName}>{span}</div>;
}
