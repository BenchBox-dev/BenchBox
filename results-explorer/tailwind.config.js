const brandStops = [50, 100, 200, 300, 500, 600, 700, 900];

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: Object.fromEntries(brandStops.map((stop) => [stop, `var(--bb-brand-${stop})`])),
      },
      fontFamily: {
        mono: ["var(--bb-font-mono-system)"],
      },
    },
  },
  plugins: [],
};
