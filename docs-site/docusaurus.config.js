// @ts-check
import {themes as prismThemes} from 'prism-react-renderer';

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'DrawGen',
  tagline: 'Turn a spreadsheet into a finished diagram',
  favicon: 'img/favicon.ico',

  future: {
    v4: true,
  },

  url: 'https://drawgen.dev-ai.site',
  // Must stay exactly '/docs/': the site is served at drawgen.dev-ai.site/docs
  // (a path on the existing app's domain, not a subdomain) via Caddy's
  // `handle_path /docs/*` block. Every internal link/asset breaks if this
  // doesn't match that prefix.
  baseUrl: '/docs/',

  organizationName: 'manav2109',
  projectName: 'dungen',

  onBrokenLinks: 'throw',
  markdown: {
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          // Docs mounted at the site root (under baseUrl) instead of the
          // default 'docs' sub-path, so pages read as /docs/<page> in
          // production rather than /docs/docs/<page>.
          routeBasePath: '/',
          sidebarPath: './sidebars.js',
          editUrl: 'https://github.com/manav2109/dungen/edit/main/docs-site/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      image: 'img/docusaurus-social-card.jpg',
      colorMode: {
        respectPrefersColorScheme: true,
      },
      navbar: {
        title: 'DrawGen',
        logo: {
          alt: 'DrawGen Logo',
          src: 'img/logo.svg',
        },
        items: [
          {
            type: 'docSidebar',
            sidebarId: 'docsSidebar',
            position: 'left',
            label: 'Docs',
          },
          {
            // Fully-qualified: a bare '/api/docs' would be treated as
            // internal and get baseUrl ('/docs/') prepended, which is not
            // what we want here — this points at the backend's own Swagger
            // UI, a different path on the same domain, not under /docs/.
            href: 'https://drawgen.dev-ai.site/api/docs',
            label: 'API Reference',
            position: 'left',
          },
          {
            href: 'https://drawgen.dev-ai.site',
            label: 'Open App',
            position: 'right',
          },
          {
            href: 'https://github.com/manav2109/dungen',
            label: 'GitHub',
            position: 'right',
          },
        ],
      },
      footer: {
        style: 'dark',
        links: [
          {
            title: 'Docs',
            items: [
              {label: 'Product Overview', to: '/'},
              {label: 'User Guide', to: '/user-guide/operations'},
              {label: 'Architecture', to: '/architecture/overview'},
              {label: 'Deployment', to: '/deployment/home-server'},
            ],
          },
          {
            title: 'More',
            items: [
              {label: 'API Reference', to: '/api-reference'},
              {label: 'GitHub', href: 'https://github.com/manav2109/dungen'},
            ],
          },
        ],
        copyright: `Copyright © ${new Date().getFullYear()} DrawGen. Built with Docusaurus.`,
      },
      prism: {
        theme: prismThemes.github,
        darkTheme: prismThemes.dracula,
      },
    }),
};

export default config;
