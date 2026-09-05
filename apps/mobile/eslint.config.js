const { defineConfig } = require('eslint/config');
const expoConfig = require('eslint-config-expo/flat');

module.exports = defineConfig([
  expoConfig,
  {
    ignores: ['dist/**'],
    rules: {
      // eslint-plugin-import traverses above the workspace and hits a protected Windows directory.
      'import/no-unresolved': 'off',
    },
  },
]);
