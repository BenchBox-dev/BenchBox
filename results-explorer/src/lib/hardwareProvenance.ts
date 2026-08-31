import type { Environment } from "@/types";

export function formatCpuIdentityProvenance(
  value: Environment["cpu_identity_provenance"] | string | null | undefined,
): string {
  if (value === null || value === undefined || value === "") return "Not recorded";
  if (value === "user_attested") return "User attested";
  if (value === "measured") return "Measured";
  if (value === "inferred") return "Inferred";
  return "Unknown";
}
