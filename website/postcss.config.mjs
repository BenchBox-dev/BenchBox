import { scopeCss } from "./src/lib/scope-css.mjs";

export default {
  plugins: [
    scopeCss({ match: /landing\/style\.css$/, scope: ".landing", drop: [/^\.token/, /^\.language-css/, /^\.style\s/] }),
    scopeCss({ match: /landing\/prompts\/prompts\.css$/, scope: ".prompts-page" }),
  ],
};
