import { Select } from "@/components/Select";
import { decodeBasis, encodeBasis, formatBasisLabel, type MeasurementBasis } from "@/lib/measurementBasis";

interface Props {
  basis: MeasurementBasis;
  options: readonly MeasurementBasis[];
  onChange: (basis: MeasurementBasis) => void;
  loading: boolean;
  error: string | null;
}

export function PlatformBasisControl({ basis, options, onChange, loading, error }: Props) {
  return <section class="panel mb-4 px-4 py-3" aria-label="Measurement basis">
    <label for="platform-measurement-basis" class="mb-2 block text-sm font-medium">Measurement basis</label>
    <Select id="platform-measurement-basis" ariaLabel="Measurement basis" value={encodeBasis(basis)}
      options={options.map((option) => ({ value: encodeBasis(option), label: formatBasisLabel(option) }))}
      onChange={(value) => { const next = decodeBasis(value); if (next) onChange(next); }} />
    <p class="mt-2 text-xs text-[var(--bb-data-fg-muted)]">
      Geomean uses each run’s own available queries. Compare only matching benchmarks and scales; open Compare to use a shared query set.
      Power scores are available only for the published measurement basis. A dash means the selected passes are unavailable.
    </p>
    {loading && <p role="status" class="mt-2 text-sm">Loading measurement passes…</p>}
    {error && <p role="status" class="mt-2 text-sm">{error}</p>}
  </section>;
}
