import { useState } from "preact/hooks";
import { splitVersion } from "@/lib/versionLabel";

interface VersionLabelProps {
  version: string | null | undefined;
  plain?: boolean;
  class?: string;
}

export function VersionLabel({ version, plain = false, class: extraClass = "" }: VersionLabelProps) {
  const [expanded, setExpanded] = useState(false);
  const parts = splitVersion(version);
  if (parts === null) return null;

  const className = `${plain ? "whitespace-nowrap font-mono text-xs" : "bb-meta-chip font-mono"} ${extraClass}`;

  if (parts.suffix === null) {
    return (
      <span class={className} data-testid="version-label">
        {parts.core}
      </span>
    );
  }

  return (
    <button
      type="button"
      class={className}
      data-testid="version-label"
      data-expanded={expanded ? "true" : "false"}
      title={parts.full}
      aria-label={`Version ${parts.full}. Activate to ${expanded ? "collapse" : "show"} the full version.`}
      onClick={(event) => {
        event.stopPropagation();
        event.preventDefault();
        setExpanded((value) => !value);
      }}
    >
      {expanded ? parts.full : `${parts.core}…`}
    </button>
  );
}
