import js from '@eslint/js'
import prettier from 'eslint-config-prettier/flat'
import pluginVue from 'eslint-plugin-vue'
import pluginVueA11y from 'eslint-plugin-vuejs-accessibility'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default [
  { ignores: ['dist', 'node_modules', 'coverage', 'playwright-report', 'test-results'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  ...pluginVueA11y.configs['flat/recommended'],
  {
    files: ['**/*.{js,ts,vue}'],
    languageOptions: {
      globals: { ...globals.browser, ...globals.node }
    }
  },
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser
      }
    }
  },
  {
    // Type-aware rules, on the application code only: tests sit outside the
    // tsconfig project, and what these rules catch (a dropped promise, an awaited
    // non-promise) is a UI bug class, not a test-harness one.
    files: ['src/**/*.{ts,vue}'],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
        // .vue is not a TypeScript extension; the project service needs telling.
        extraFileExtensions: ['.vue']
      }
    },
    rules: {
      '@typescript-eslint/no-floating-promises': 'error',
      '@typescript-eslint/no-misused-promises': 'error',
      '@typescript-eslint/await-thenable': 'error',
      '@typescript-eslint/no-explicit-any': 'error'
    }
  },
  {
    files: ['tests/**/*.ts'],
    rules: {
      // Test doubles are deliberately loosely typed.
      '@typescript-eslint/no-explicit-any': 'off'
    }
  },
  // Must stay last: switches off every formatting rule Prettier owns.
  prettier
]
