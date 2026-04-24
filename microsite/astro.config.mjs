// @ts-check
import { defineConfig, passthroughImageService } from 'astro/config';
import starlight from '@astrojs/starlight';

// https://astro.build/config
export default defineConfig({
	site: 'https://GranatenUdo.github.io',
	base: '/docforge',
	image: {
		// All assets are SVG or pre-sized PNG; skip raster processing so we
		// don't need the `sharp` native binary.
		service: passthroughImageService(),
	},
	integrations: [
		starlight({
			title: 'docforge',
			description: 'Self-hosted context engine for AI coding assistants.',
			logo: { src: './src/assets/logo.svg', replacesTitle: false },
			favicon: '/favicon.ico',
			social: [
				{ icon: 'github', label: 'GitHub', href: 'https://github.com/GranatenUdo/docforge' },
			],
			sidebar: [
				{ label: 'Install', slug: 'install' },
				{ label: 'Architecture', slug: 'architecture' },
				{ label: 'Deployment', slug: 'deployment' },
				{ label: 'FAQ', slug: 'faq' },
				{ label: 'Blog', autogenerate: { directory: 'blog' } },
			],
		}),
	],
});
