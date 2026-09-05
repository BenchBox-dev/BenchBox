import { createContext, createElement, type ComponentChildren } from "preact";
import { useContext, useMemo, useState } from "preact/hooks";
import { importLocalResultFile, type LocalResultPreview } from "@/lib/localResult";

export interface LocalResultStateValue {
  preview: LocalResultPreview | null;
  importFile: (file: File) => Promise<LocalResultPreview>;
  clear: () => void;
}

const MISSING_PROVIDER_STATE: LocalResultStateValue = {
  preview: null,
  importFile: async () => {
    throw new Error("Local result import is unavailable outside LocalResultProvider");
  },
  clear: () => undefined,
};

const LocalResultContext = createContext<LocalResultStateValue>(MISSING_PROVIDER_STATE);

export function LocalResultProvider({ children }: { children: ComponentChildren }) {
  const [preview, setPreview] = useState<LocalResultPreview | null>(null);
  const value = useMemo<LocalResultStateValue>(() => ({
    preview,
    importFile: async (file) => {
      const nextPreview = await importLocalResultFile(file);
      setPreview(nextPreview);
      return nextPreview;
    },
    clear: () => setPreview(null),
  }), [preview]);
  return createElement(LocalResultContext.Provider, { value }, children);
}

export function useLocalResultState(): LocalResultStateValue {
  return useContext(LocalResultContext);
}
