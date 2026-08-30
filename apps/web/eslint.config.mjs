import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Eve dev-server cache: vendored snapshots and compiled bundles. Without
    // this, `npm run lint` reports 20k problems from generated code and the
    // handful in our own source is unfindable.
    ".eve/**",
    "node_modules/**",
  ]),
]);

export default eslintConfig;
