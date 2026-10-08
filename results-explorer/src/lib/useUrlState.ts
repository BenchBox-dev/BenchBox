import { useCallback, useEffect, useState } from "preact/hooks";

export interface UrlSerde<T> {
  encode: (value: T) => string;
  decode: (raw: string) => T | null;
}

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
  if (encoded === "" || encoded === encodedInitial) {
    params.delete(key);
  } else {
    params.set(key, encoded);
  }
  const newSearch = params.toString();
  const search = newSearch.length > 0 ? `?${newSearch}` : "";
  const newUrl = `${window.location.pathname}${search}${window.location.hash}`;
  history.replaceState(history.state, "", newUrl);
}

export function useUrlState<T>(
  key: string,
  initial: T,
  serde: UrlSerde<T> = stringSerde as unknown as UrlSerde<T>,
): [T, (value: T) => void] {
  const [value, setValueRaw] = useState<T>(() => {
    const fromUrl = readFromUrl(key, serde);
    return fromUrl !== null ? fromUrl : initial;
  });

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
    history.replaceState(
      history.state,
      "",
      `${window.location.pathname}${search}${window.location.hash}`,
    );
  }, []);

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
