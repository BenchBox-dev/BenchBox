import type { JSX } from "preact";

/**
 * Standardized "← scroll →" affordance for tables that scroll horizontally on
 * narrow viewports. Owns the `bb-scroll-affordance` class wiring, the
 * `data-testid` shape, and the default placement (`mb-2 flex justify-end`)
 * so callers do not duplicate the markup that PR #270 introduced and PR #270's
 * follow-up standardized.
 *
 * The visibility threshold (`max-width: 48rem`) is enforced in
 * `index.css` via the `.bb-scroll-affordance` class, not here, so this helper
 * stays pure markup.
 *
 * Pass `wrapperClassName={null}` to render only the span (used when the cue
 * lives inside a meta-row or a custom flex layout).
 */
export interface TableScrollHintProps {
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
  label = DEFAULT_LABEL,
  testId,
  className = "",
  wrapperClassName = DEFAULT_WRAPPER_CLASS,
}: TableScrollHintProps): JSX.Element {
  const spanClass = `bb-scroll-affordance${className === "" ? "" : ` ${className}`}`;
  const span = (
    <span class={spanClass} data-testid={testId}>
      {label}
    </span>
  );
  if (wrapperClassName === null) return span;
  return <div class={wrapperClassName}>{span}</div>;
}
