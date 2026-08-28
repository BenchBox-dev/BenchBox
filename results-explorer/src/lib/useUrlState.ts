/**
 * useUrlState - sync a state value to/from the URL query string.
 *
 * Uses history.replaceState (no history spam) and popstate (back/forward
 * navigation re-hydrates state). SSR-safe: reads/writes to window are gated
 * on `typeof window !== "undefined"` so vite-ssg static builds don't break.
 */

import { useCallback, useEffect, useState } from "preact/hooks";

export interface UrlSerde<T> {
  encode: (value: T) => string;
  decode: (raw: string) => T | null;
}

// ---------------------------------------------------------------------------
// Built-in serdes
// ---------------------------------------------------------------------------

export const stringSerde: UrlSerde<string> = {
  encode: (v) => v,
  decode: (raw) => raw,
};

export const numberSerde: UrlSerde<number> = {
  encode: (v) => String(v),
  decode: (raw) => {
    const n = Number(raw);
    return isNaN(n) ? null : n;
  },
};

/** Comma-separated list serde. Empty string decodes to empty array. */
export const arraySerde: UrlSerde<string[]> = {
  encode: (v) => v.join(","),
  decode: (raw) => (raw === "" ? [] : raw.split(",")),
};

export const jsonSerde = <T>(): UrlSerde<T> => ({
  encode: (v) => JSON.stringify(v),
  decode: (raw) => {
    try {
      return JSON.parse(raw) as T;
    } catch {
      return null;
    }
  },
});

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

function readFromUrl<T>(key: string, serde: UrlSerde<T>): T | null {
  if (typeof window === "undefined") return null;
  const params = new URLSearchParams(window.location.search);
  const raw = params.get(key);
  if (raw === null) return null;
  return serde.decode(raw);
}

function writeToUrl<T>(key: string, value: T, initial: T, serde: UrlSerde<T>): void {
  if (typeof window === "undefined") return;
  const params = new URLSearchParams(window.location.search);
  const encoded = serde.encode(value);
  const encodedInitial = serde.encode(initial);
  // Strip the key when the encoded value is empty or matches the default -
  // keeps the URL tidy and avoids `?bm=` noise for empty arrays.
  if (encoded === "" || encoded === encodedInitial) {
    params.delete(key);
  } else {
    params.set(key, encoded);
  }
  const newSearch = params.toString();
  const search = newSearch.length > 0 ? `?${newSearch}` : "";
  const newUrl = `${window.location.pathname}${search}${window.location.hash}`;
  history.replaceState(null, "", newUrl);
}

/**
 * useUrlState<T> - drop-in replacement for useState that round-trips through
 * the URL query string.
 *
 * @param key      URL param key (e.g. "sf", "phase")
 * @param initial  Default value when the key is absent or invalid
 * @param serde    Encode/decode pair; defaults to stringSerde
 */
export function useUrlState<T>(
  key: string,
  initial: T,
  serde: UrlSerde<T> = stringSerde as unknown as UrlSerde<T>,
): [T, (value: T) => void] {
  const [value, setValueRaw] = useState<T>(() => {
    const fromUrl = readFromUrl(key, serde);
    return fromUrl !== null ? fromUrl : initial;
  });

  // On mount, strip the key from the URL if its decoded value equals the
  // initial/default - avoids stale `?bm=` noise persisting in shared links.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (!params.has(key)) return;
    const encoded = serde.encode(value);
    const encodedInitial = serde.encode(initial);
    if (encoded !== "" && encoded !== encodedInitial) return;
    params.delete(key);
    const newSearch = params.toString();
    const search = newSearch.length > 0 ? `?${newSearch}` : "";
    history.replaceState(null, "", `${window.location.pathname}${search}${window.location.hash}`);
    // Intentionally mount-only: later equality checks happen inside setValue → writeToUrl.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-hydrate on popstate (back/forward navigation).
  useEffect(() => {
    if (typeof window === "undefined") return;
    function onPopState() {
      const fromUrl = readFromUrl(key, serde);
      setValueRaw(fromUrl !== null ? fromUrl : initial);
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [key, initial]);

  const setValue = useCallback(
    (newValue: T) => {
      setValueRaw(newValue);
      writeToUrl(key, newValue, initial, serde);
    },
    [key, initial],
  );

  return [value, setValue];
}
