import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

const siteUrl = process.env.SITE_URL || 'https://CLINIC_SUBDOMAIN.medplatform.io';
const hasSite = !siteUrl.includes('CLINIC_SUBDOMAIN');

export default defineConfig({
  site: siteUrl,
  integrations: [...(hasSite ? [sitemap()] : [])],
  output: 'static',
  build: { assets: '_assets' },
});
