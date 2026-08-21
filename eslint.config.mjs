export default [
  {
    ignores: [
      "**/node_modules/**",
      "**/vendor/**",
      "**/*.min.js",
      "apps/gateway/server/static/workbench-preact.js",
      "apps/owner/local-tmux-owner/static/owner-ui.js",
    ],
  },
  {
    files: ["apps/**/*.{js,mjs,jsx}", "tools/**/*.{js,mjs}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    rules: {
      "no-dupe-args": "error",
      "no-dupe-keys": "error",
      "no-func-assign": "error",
      "no-import-assign": "error",
      "no-self-assign": "error",
      "no-unreachable": "error",
      "no-unsafe-finally": "error",
      "no-unused-vars": [
        "error",
        {
          args: "after-used",
          argsIgnorePattern: "^_",
          caughtErrors: "none",
          varsIgnorePattern: "^_",
        },
      ],
      "valid-typeof": "error",
    },
  },
  {
    files: ["apps/**/*.jsx"],
    rules: {
      // JSX identifiers are resolved by esbuild; core ESLint has no JSX
      // reference tracker without adding a framework-specific plugin.
      "no-unused-vars": "off",
    },
  },
];
