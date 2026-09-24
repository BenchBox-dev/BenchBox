import { useState } from "preact/hooks";
import { splitVersion } from "@/lib/versionLabel";

interface VersionLabelProps {
  version: string | null | undefined;
  /** Render as a plain span rather than the bordered metadata chip. */
  plain?: boolean;
  class?: string;
}

/**
 * The site-wide treatment for a platform or driver version.
 *
 * Leads with the release core and elides a prerelease/build suffix, which is
 * both the longest and the least comparable part of the value. The full
 * version stays in the accessible name and the title, and one click expands
 * it in place, so nothing is lost - only deferred.
 */
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
