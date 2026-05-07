/**
 * Regression coverage for shared retheme primitives.
 *
 * These primitives are introduced by
 * `results-explorer-retheme-theme-system-foundation` and consumed by every
 * downstream retheme TODO. We exercise:
 *
 *   - accessible names (aria-label / role / labelled headers)
 *   - selected / pressed state (aria-checked / aria-selected / aria-pressed)
 *   - disabled state (does not trigger callbacks; aria-disabled)
 *   - status-tone semantics for StatusBadge
 *   - keyboard-focus surface (the focus-visible CSS rule is asserted via
 *     surface attribute presence — actual paint is verified in browser
 *     screenshots)
 */

import { fireEvent, render, screen } from "@testing-library/preact";
import { describe, expect, it, vi } from "vitest";
import { Button } from "@/components/Button";
import { SegmentedControl } from "@/components/SegmentedControl";
import { Tabs } from "@/components/Tabs";
import { Panel, DataCard } from "@/components/Panel";
import { DataTable, TableHead, TableBody } from "@/components/DataTable";
import { Select } from "@/components/Select";
import { Checkbox } from "@/components/Checkbox";
import { FacetChip } from "@/components/FacetChip";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";

describe("Button", () => {
  it("renders primary by default with btn-primary class", () => {
    const { container } = render(<Button>Run</Button>);
    const button = container.querySelector("button")!;
    expect(button.className).toContain("btn-primary");
    expect(button.textContent).toContain("Run");
  });

  it("respects variant=danger", () => {
    const { container } = render(<Button variant="danger">Delete</Button>);
    expect(container.querySelector("button")!.className).toContain("btn-danger");
  });

  it("does not invoke onClick when disabled", () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Locked
      </Button>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Locked" }));
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("SegmentedControl", () => {
  it("renders a radiogroup with aria-checked tracking value", () => {
    const onChange = vi.fn();
    render(
      <SegmentedControl
        ariaLabel="Density"
        value="comfy"
        onChange={onChange}
        options={[
          { value: "compact", label: "Compact" },
          { value: "comfy", label: "Comfy" },
        ]}
      />,
    );
    const compact = screen.getByRole("radio", { name: "Compact" });
    const comfy = screen.getByRole("radio", { name: "Comfy" });
    expect(compact.getAttribute("aria-checked")).toBe("false");
    expect(comfy.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(compact);
    expect(onChange).toHaveBeenCalledWith("compact");
  });

  it("does not invoke onChange when an option is disabled", () => {
    const onChange = vi.fn();
    render(
      <SegmentedControl
        ariaLabel="Density"
        value="comfy"
        onChange={onChange}
        options={[
          { value: "compact", label: "Compact", disabled: true },
          { value: "comfy", label: "Comfy" },
        ]}
      />,
    );
    fireEvent.click(screen.getByRole("radio", { name: "Compact" }));
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("Tabs", () => {
  it("marks the active tab with aria-selected and tabIndex=0", () => {
    const onChange = vi.fn();
    render(
      <Tabs
        ariaLabel="Sections"
        value="b"
        onChange={onChange}
        items={[
          { value: "a", label: "A" },
          { value: "b", label: "B" },
        ]}
      />,
    );
    const a = screen.getByRole("tab", { name: "A" });
    const b = screen.getByRole("tab", { name: "B" });
    expect(b.getAttribute("aria-selected")).toBe("true");
    expect(b.getAttribute("tabindex")).toBe("0");
    expect(a.getAttribute("aria-selected")).toBe("false");
    expect(a.getAttribute("tabindex")).toBe("-1");
    fireEvent.click(a);
    expect(onChange).toHaveBeenCalledWith("a");
  });

  it("renders an optional count alongside the label", () => {
    render(
      <Tabs
        ariaLabel="Sections"
        value="a"
        onChange={vi.fn()}
        items={[{ value: "a", label: "A", count: 7 }]}
      />,
    );
    expect(screen.getByText("(7)")).toBeTruthy();
  });

  it("ArrowRight / ArrowLeft / Home / End move selection and focus skipping disabled tabs", () => {
    const onChange = vi.fn();
    render(
      <Tabs
        ariaLabel="Sections"
        value="a"
        onChange={onChange}
        items={[
          { value: "a", label: "A" },
          { value: "b", label: "B", disabled: true },
          { value: "c", label: "C" },
        ]}
      />,
    );
    const a = screen.getByRole("tab", { name: "A" });
    const c = screen.getByRole("tab", { name: "C" });

    a.focus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith("c");
    expect(c).toHaveFocus();

    fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith("a");
    expect(a).toHaveFocus();

    fireEvent.keyDown(document.activeElement!, { key: "ArrowLeft" });
    expect(onChange).toHaveBeenLastCalledWith("c");
    expect(c).toHaveFocus();

    fireEvent.keyDown(document.activeElement!, { key: "Home" });
    expect(onChange).toHaveBeenLastCalledWith("a");
    expect(a).toHaveFocus();

    fireEvent.keyDown(document.activeElement!, { key: "End" });
    expect(onChange).toHaveBeenLastCalledWith("c");
    expect(c).toHaveFocus();
  });

  it("aria-controls links the tablist to a tabpanel id when supplied", () => {
    render(
      <Tabs
        ariaLabel="Sections"
        controls="my-panel"
        value="a"
        onChange={vi.fn()}
        items={[{ value: "a", label: "A" }]}
      />,
    );
    const tab = screen.getByRole("tab", { name: "A" });
    expect(tab.getAttribute("aria-controls")).toBe("my-panel");
  });
});

describe("Panel / DataCard", () => {
  it("Panel emits data-surface=data by default", () => {
    const { container } = render(<Panel>body</Panel>);
    const panel = container.querySelector("[data-surface='data']")!;
    expect(panel).toBeTruthy();
    expect(panel.className).toContain("panel");
  });

  it("Panel tone=hero sets data-surface=hero (focus-ring switches via CSS)", () => {
    const { container } = render(<Panel tone="hero">hero</Panel>);
    expect(container.querySelector("[data-surface='hero']")).toBeTruthy();
  });

  it("DataCard renders title, description, and actions", () => {
    render(
      <DataCard title="Charts" description="One per question" actions={<button>Export</button>}>
        body
      </DataCard>,
    );
    expect(screen.getByRole("heading", { name: "Charts" })).toBeTruthy();
    expect(screen.getByText("One per question")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Export" })).toBeTruthy();
  });
});

describe("DataTable", () => {
  it("renders an accessible table with optional caption", () => {
    render(
      <DataTable ariaLabel="Latency" caption="Latency by platform">
        <TableHead>
          <tr>
            <th>Platform</th>
            <th>p50</th>
          </tr>
        </TableHead>
        <TableBody>
          <tr>
            <td>DuckDB</td>
            <td>12 ms</td>
          </tr>
        </TableBody>
      </DataTable>,
    );
    const table = screen.getByRole("table", { name: "Latency" });
    expect(table.querySelector("caption")?.textContent).toContain("Latency by platform");
    expect(screen.getByRole("cell", { name: "DuckDB" })).toBeTruthy();
  });
});

describe("Select", () => {
  it("renders an accessible select that fires onChange with the new value", () => {
    const onChange = vi.fn();
    render(
      <Select
        ariaLabel="Platform"
        value="duckdb"
        onChange={onChange}
        options={[
          { value: "duckdb", label: "DuckDB" },
          { value: "datafusion", label: "DataFusion" },
        ]}
      />,
    );
    const select = screen.getByLabelText("Platform") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "datafusion" } });
    expect(onChange).toHaveBeenCalledWith("datafusion");
  });
});

describe("Checkbox", () => {
  it("toggles via onChange and exposes optional description through aria-describedby", () => {
    const onChange = vi.fn();
    const { container } = render(
      <Checkbox
        label="Show normalized cost"
        description="Requires normalized_cost_usd"
        checked={false}
        onChange={onChange}
      />,
    );
    const input = container.querySelector("input[type=checkbox]") as HTMLInputElement;
    expect(input.getAttribute("aria-describedby")).toBeTruthy();
    fireEvent.click(input);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("does not invoke onChange when disabled", () => {
    const onChange = vi.fn();
    const { container } = render(
      <Checkbox label="Locked" checked={false} disabled onChange={onChange} />,
    );
    const input = container.querySelector("input[type=checkbox]") as HTMLInputElement;
    fireEvent.click(input);
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe("FacetChip", () => {
  it("uses role=switch with aria-checked tracking selected state", () => {
    const onToggle = vi.fn();
    render(
      <FacetChip selected onToggle={onToggle} count={3}>
        TPC-H
      </FacetChip>,
    );
    const chip = screen.getByRole("switch", { name: /TPC-H/ });
    expect(chip.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(chip);
    expect(onToggle).toHaveBeenCalled();
  });
});

describe("StatusBadge", () => {
  it("emits data-role and data-tone for downstream targeting", () => {
    const { container } = render(
      <StatusBadge role="trust" tone="success">
        Maintainer
      </StatusBadge>,
    );
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-role")).toBe("trust");
    expect(badge?.getAttribute("data-tone")).toBe("success");
    expect(badge?.className).toContain("tone-success");
  });
});

describe("EmptyState", () => {
  it("uses role=status and renders title + description", () => {
    render(
      <EmptyState
        title="No platforms yet"
        description="Submit a result to populate this leaderboard."
      />,
    );
    expect(screen.getByRole("status")).toBeTruthy();
    expect(screen.getByText("No platforms yet")).toBeTruthy();
    expect(screen.getByText("Submit a result to populate this leaderboard.")).toBeTruthy();
  });
});

describe("ErrorState", () => {
  it("uses role=alert and renders detail block when provided", () => {
    render(
      <ErrorState
        title="Failed to load benchmark"
        description="DuckDB raised a binder error."
        detail={"Binder Error: Could not bind column normalized_cost_usd"}
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toBeTruthy();
    expect(alert.querySelector("pre")?.textContent).toContain("Binder Error");
  });
});
