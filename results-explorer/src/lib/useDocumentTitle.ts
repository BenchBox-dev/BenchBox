import { useEffect } from "preact/hooks";

const DEFAULT_DOCUMENT_TITLE = "BenchBox Results Explorer";

export function useDocumentTitle(title: string) {
  useEffect(() => {
    if (typeof document === "undefined") return;
    document.title = title;
    return () => {
      document.title = DEFAULT_DOCUMENT_TITLE;
    };
  }, [title]);
}
