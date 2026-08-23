import type { JSX, RefObject } from "preact";
import { useLayoutEffect, useState } from "preact/hooks";

/**
 * Standardized "← scroll →" affordance for tables that scroll horizontally on
 * narrow viewports. Owns the `bb-scroll-affordance` class wiring, the
 * `data-testid` shape, and the default placement (`mb-2 flex justify-end`)
 * so callers do not duplicate the markup that PR #270 introduced and PR #270's
 * follow-up standardized.
 *
 * Visibility follows the target scroll container's measured geometry rather
 * than a viewport breakpoint, because table widths vary by result corpus.
 *
 * Pass `wrapperClassName={null}` to render only the span (used when the cue
 * lives inside a meta-row or a custom flex layout).
 */
export interface TableScrollHintProps {
  /** Ref for the sibling overflow container whose geometry controls visibility. */
  scrollerRef: RefObject<HTMLElement>;
  /** Visible text. Defaults to "← scroll →"; pass a longer copy when the
   *  affordance describes what the user can scroll to. */
  label?: string;
  /** Stable test id applied to the inner span. */
  testId?: string;
  /** Additional classes applied to the span. */
  className?: string;
  /** Classes applied to the wrapper div. `null` skips the wrapper. */
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
