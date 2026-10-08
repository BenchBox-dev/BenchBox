import { configureAxe, toHaveNoViolations } from "jest-axe";
import { expect } from "vitest";

expect.extend(toHaveNoViolations);

const axe = configureAxe({ impactLevels: ["serious", "critical"] });

export async function expectNoAxeViolations(container: Element): Promise<void> {
  expect(await axe(container)).toHaveNoViolations();
}
