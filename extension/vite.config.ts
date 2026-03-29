import { defineConfig } from 'vite';
import { resolve } from 'path';
import {
  readFileSync,
  writeFileSync,
  mkdirSync,
  cpSync,
  existsSync,
} from 'fs';
import { build } from 'vite';

/**
 * Plugin: build content scripts as self-contained IIFE bundles.
 *
 * Chrome MV3 content scripts declared in manifest.json cannot use
 * ES module imports. They must be self-contained. This plugin runs
 * separate Vite builds for each content script after the main build,
 * producing IIFE bundles with all dependencies inlined.
 */
function buildContentScriptsPlugin(env: string, mode: string) {
  return {
    name: 'build-content-scripts',
    async closeBundle() {
      const outDir = resolve(__dirname, `dist/${env}`);
      const contentScripts = [
        {
          name: 'sales-navigator',
          entry: resolve(__dirname, 'src/content/sales-navigator.ts'),
        },
        {
          name: 'activity-monitor',
          entry: resolve(__dirname, 'src/content/activity-monitor.ts'),
        },
      ];

      for (const script of contentScripts) {
        await build({
          configFile: false,
          build: {
            outDir,
            emptyOutDir: false, // Don't clean the directory
            sourcemap: env === 'staging' ? 'inline' : false,
            minify: env === 'prod',
            lib: {
              entry: script.entry,
              name: script.name.replace(/-/g, '_'),
              formats: ['iife'],
              fileName: () => `${script.name}.js`,
            },
            rollupOptions: {
              output: {
                // Ensure no imports in the output
                inlineDynamicImports: true,
              },
            },
          },
          define: {
            __API_BASE__: JSON.stringify(
              mode === 'production'
                ? 'https://leadgen.visionvolve.com'
                : 'https://leadgen-staging.visionvolve.com',
            ),
            __IAM_BASE__: JSON.stringify(
              mode === 'production'
                ? 'https://iam.visionvolve.com'
                : 'https://iam-staging.visionvolve.com',
            ),
            __EXT_ENV__: JSON.stringify(env),
          },
          logLevel: 'warn',
        });
      }
    },
  };
}

/**
 * Plugin: merge manifest files and copy static assets.
 */
function mergeManifestPlugin(env: string) {
  return {
    name: 'merge-manifest',
    closeBundle() {
      const outDir = resolve(__dirname, `dist/${env}`);

      // Merge manifests: base + environment overlay
      const base = JSON.parse(
        readFileSync(resolve(__dirname, 'manifests/base.json'), 'utf-8'),
      );
      const overlay = JSON.parse(
        readFileSync(resolve(__dirname, `manifests/${env}.json`), 'utf-8'),
      );

      const merged = { ...base, ...overlay };

      // Merge host_permissions (union of both)
      if (base.host_permissions && overlay.host_permissions) {
        const allHosts = new Set([
          ...base.host_permissions,
          ...overlay.host_permissions,
        ]);
        merged.host_permissions = [...allHosts];
      }

      // Update action icons from overlay
      if (overlay.icons) {
        merged.action = {
          ...merged.action,
          default_icon: overlay.icons,
        };
      }

      writeFileSync(
        resolve(outDir, 'manifest.json'),
        JSON.stringify(merged, null, 2),
      );

      // Copy side panel HTML
      const sidepanelSrc = resolve(__dirname, 'src/popup/sidepanel.html');
      if (existsSync(sidepanelSrc)) {
        let sidepanelHtml = readFileSync(sidepanelSrc, 'utf-8');
        sidepanelHtml = sidepanelHtml.replace('./sidepanel.ts', './sidepanel.js');
        sidepanelHtml = sidepanelHtml.replace('./icons/logo-white.png', './icons/logo-white.png');
        writeFileSync(resolve(outDir, 'sidepanel.html'), sidepanelHtml);
      }

      // Copy icons
      const iconSrcDir = resolve(__dirname, `src/icons/${env}`);
      const iconOutDir = resolve(outDir, `icons/${env}`);
      if (existsSync(iconSrcDir)) {
        mkdirSync(iconOutDir, { recursive: true });
        cpSync(iconSrcDir, iconOutDir, { recursive: true });
      }

      // Copy logo
      const logoSrc = resolve(__dirname, 'src/icons/logo-white.png');
      const logoOutDir = resolve(outDir, 'icons');
      if (existsSync(logoSrc)) {
        mkdirSync(logoOutDir, { recursive: true });
        cpSync(logoSrc, resolve(logoOutDir, 'logo-white.png'));
      }
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = mode === 'production' ? 'prod' : 'staging';

  return {
    build: {
      outDir: `dist/${env}`,
      emptyOutDir: true,
      sourcemap: env === 'staging' ? 'inline' : false,
      minify: env === 'prod',
      rollupOptions: {
        input: {
          // Service worker and side panel use ES modules (supported in MV3)
          'service-worker': resolve(
            __dirname,
            'src/background/service-worker.ts',
          ),
          sidepanel: resolve(__dirname, 'src/popup/sidepanel.ts'),
        },
        output: {
          entryFileNames: '[name].js',
          chunkFileNames: 'chunks/[name]-[hash].js',
        },
      },
    },
    define: {
      __API_BASE__: JSON.stringify(
        mode === 'production'
          ? 'https://leadgen.visionvolve.com'
          : 'https://leadgen-staging.visionvolve.com',
      ),
      __IAM_BASE__: JSON.stringify(
        mode === 'production'
          ? 'https://iam.visionvolve.com'
          : 'https://iam-staging.visionvolve.com',
      ),
      __EXT_ENV__: JSON.stringify(env),
    },
    plugins: [
      // First: merge manifest and copy assets
      mergeManifestPlugin(env),
      // Then: build content scripts as self-contained IIFE bundles
      buildContentScriptsPlugin(env, mode),
    ],
  };
});
