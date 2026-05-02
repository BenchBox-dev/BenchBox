import type { FacetKey } from "@/lib/facetModel";
import { formatFacetDisplayValue } from "@/lib/facetDisplay";

export interface CoverageBadgeProps {
  facetKey: FacetKey | string;
  value: string;
  label?: string;
  count?: number;
}

export function CoverageBadge({ facetKey, value, label, count }: CoverageBadgeProps) {
  const displayLabel = formatFacetDisplayValue(facetKey, value, label);
  return (
    <span class="rounded-full bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-600">
      {displayLabel}
      {count !== undefined && <span class="ml-1 text-gray-400">{count.toLocaleString()}</span>}
    </span>
  );
}
