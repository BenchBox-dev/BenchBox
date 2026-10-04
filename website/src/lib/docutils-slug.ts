const DIGRAPHS: Readonly<Record<string, string>> = { "ß": "sz", "æ": "ae", "œ": "oe", "ȸ": "db", "ȹ": "qp" };

const SINGLES: Readonly<Record<string, string>> = {
  "ø": "o",
  "đ": "d",
  "ħ": "h",
  "ı": "i",
  "ł": "l",
  "ŧ": "t",
  "ƀ": "b",
  "ƃ": "b",
  "ƈ": "c",
  "ƌ": "d",
  "ƒ": "f",
  "ƙ": "k",
  "ƚ": "l",
  "ƞ": "n",
  "ƥ": "p",
  "ƫ": "t",
  "ƭ": "t",
  "ƴ": "y",
  "ƶ": "z",
  "ǥ": "g",
  "ȥ": "z",
  "ȴ": "l",
  "ȵ": "n",
  "ȶ": "t",
  "ȷ": "j",
  "ȼ": "c",
  "ȿ": "s",
  "ɀ": "z",
  "ɇ": "e",
  "ɉ": "j",
  "ɋ": "q",
  "ɍ": "r",
  "ɏ": "y",
};

export function docutilsMakeId(text: string): string {
  let lowered = "";
  for (const character of text.toLowerCase()) lowered += DIGRAPHS[character] ?? SINGLES[character] ?? character;
  const ascii = lowered.normalize("NFKD").replace(/[^\x00-\x7f]/g, "");
  return ascii
    .split(/\s+/)
    .filter(Boolean)
    .join(" ")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^[-0-9]+|-+$/g, "");
}
