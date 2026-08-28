/**
 * Accessibility test helper.
 *
 * Wraps jest-axe so tests can call `await expectNoAxeViolations(container)`
 * and get a clean assertion.  Fails the test on "serious" or "critical"
 * violations only; minor and moderate issues are suppressed.
 */

import { configureAxe, toHaveNoViolations } from "jest-axe";
import { expect } from "vitest";

expect.extend(toHaveNoViolations);

// Scoped to this helper - does not suppress violations in other tests.
const axe = configureAxe({ impactLevels: ["serious", "critical"] });

/**
 * Run axe against ``container`` and fail on serious/critical violations.
 */
export async function expectNoAxeViolations(container: Element): Promise<void> {
  // toHaveNoViolations only reads .violations; the cast is safe.
  expect(await axe(container)).toHaveNoViolations();
}
