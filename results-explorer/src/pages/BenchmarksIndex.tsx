import type { RoutableProps } from "preact-router";
import { CorpusSectionIndex } from "@/pages/CorpusSectionIndex";

export function BenchmarksIndex(_: RoutableProps) {
  return <CorpusSectionIndex kind="benchmarks" />;
}
