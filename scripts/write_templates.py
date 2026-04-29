"""
Writes complete source files for orthopedics, dental, med-spa, and general templates.
Run: python3 scripts/write_templates.py
"""
import os

BASE = "/Users/servinemilio/Documents/REPOS/website-generator/templates"

def w(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)

# ══════════════════════════════════════════════════════════════
# ORTHOPEDICS
# ══════════════════════════════════════════════════════════════
T = f"{BASE}/orthopedics"

w(f"{T}/src/styles/global.css", """\
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Bebas+Neue&display=swap');

:root {
  --color-brand-primary: #0A2E6E;
  --color-brand-secondary: #1565C0;
  --color-brand-accent: #FF6B35;
  --color-surface-base: #FFFFFF;
  --color-surface-alt: #F0F4FF;
  --color-text-primary: #1A1A2E;
  --color-text-secondary: #4A5568;
  --color-text-inverse: #FFFFFF;
  --font-display: 'Arial Black', 'Helvetica Neue', sans-serif;
  --font-body: 'Inter', system-ui, sans-serif;
  --font-stats: 'Bebas Neue', sans-serif;
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-xl: 16px;
  --shadow-sm: 0 2px 8px rgba(10,46,110,0.08);
  --shadow-md: 0 8px 32px rgba(10,46,110,0.14);
  --shadow-lg: 0 20px 60px rgba(10,46,110,0.18);
  --transition-base: 0.3s ease;
}

*, *::before, *::after { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  font-family: var(--font-body);
  color: var(--color-text-primary);
  background: var(--color-surface-base);
  margin: 0; line-height: 1.65;
  -webkit-font-smoothing: antialiased;
}
img { max-width: 100%; display: block; }
a { color: inherit; text-decoration: none; }
h1, h2, h3, h4 { font-family: var(--font-display); line-height: 1.1; }
h1 { font-size: clamp(2.25rem, 5vw, 4.5rem); }
h2 { font-size: clamp(1.75rem, 3vw, 2.75rem); }

.container { max-width: 1280px; margin: 0 auto; padding: 0 clamp(1.25rem, 4vw, 4rem); }
.section { padding: clamp(4rem, 8vw, 7rem) 0; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0,0,0,0); }

.btn {
  display: inline-flex; align-items: center; gap: 0.5rem;
  padding: 0.875rem 2rem; font-family: var(--font-body);
  font-size: 0.9375rem; font-weight: 600; border-radius: var(--radius-md);
  border: 2px solid transparent; cursor: pointer; transition: var(--transition-base);
  text-decoration: none; letter-spacing: 0.02em;
}
.btn-primary { background: var(--color-brand-primary); color: white; border-color: var(--color-brand-primary); }
.btn-primary:hover { background: #081F4D; box-shadow: 0 4px 20px rgba(10,46,110,0.3); transform: translateY(-2px); }
.btn-accent { background: var(--color-brand-accent); color: white; border-color: var(--color-brand-accent); }
.btn-accent:hover { background: #E55A24; transform: translateY(-2px); }
.btn-outline { background: transparent; color: var(--color-brand-accent); border-color: var(--color-brand-accent); }
.btn-outline:hover { background: var(--color-brand-accent); color: white; }
.btn-white { background: white; color: var(--color-brand-primary); }
.btn-white:hover { background: #f0f4ff; transform: translateY(-2px); }

:focus-visible { outline: 2px solid var(--color-brand-accent); outline-offset: 3px; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
""")

w(f"{T}/src/layouts/Layout.astro", """\
---
import '../styles/global.css';
const { title, description = '', schema = null } = Astro.props;
const siteUrl = import.meta.env.SITE || 'https://CLINIC_SUBDOMAIN.medplatform.io';
const googleVerification = import.meta.env.PUBLIC_GOOGLE_VERIFICATION;
---
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  {description && <meta name="description" content={description} />}
  <meta property="og:title" content={title} />
  {description && <meta property="og:description" content={description} />}
  <meta property="og:type" content="website" />
  <link rel="sitemap" href="/sitemap-index.xml" />
  {googleVerification && <meta name="google-site-verification" content={googleVerification} />}
  {schema && <script type="application/ld+json" set:html={JSON.stringify(schema)} />}
  <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js" defer></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/ScrollTrigger.min.js" defer></script>
  <slot name="head" />
</head>
<body>
  <slot />
  <script src="/scripts/animations.js" defer></script>
</body>
</html>
""")

os.makedirs(f"{T}/public/scripts", exist_ok=True)
w(f"{T}/public/scripts/animations.js", """\
document.addEventListener('DOMContentLoaded', () => {
  if (typeof gsap === 'undefined') return;
  gsap.registerPlugin(ScrollTrigger);
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  // Split hero: image panel from left, content from right
  gsap.from('.hero-image-panel', { x: -60, opacity: 0, duration: 0.85, ease: 'power3.out' });
  gsap.from('.hero-content > *', { x: 40, opacity: 0, duration: 0.7, ease: 'power2.out', stagger: 0.15, delay: 0.2 });

  // Stat counters
  document.querySelectorAll('.stat-number').forEach(el => {
    const target = parseInt(el.dataset.target || '0');
    const suffix = el.dataset.suffix || '';
    const obj = { val: 0 };
    gsap.to(obj, {
      val: target, duration: 2.5, ease: 'power2.out',
      scrollTrigger: { trigger: el, start: 'top 85%', once: true },
      onUpdate() { el.textContent = Math.round(obj.val).toLocaleString() + suffix; }
    });
  });

  // Nav scroll
  const nav = document.querySelector('.site-nav');
  if (nav) {
    ScrollTrigger.create({
      start: 'top -80',
      onUpdate: self => nav.classList.toggle('nav-scrolled', self.progress > 0)
    });
  }

  // Timeline draw
  if (document.querySelector('.timeline-line')) {
    gsap.from('.timeline-line', {
      scaleX: 0, transformOrigin: 'left center', duration: 1.5, ease: 'power2.inOut',
      scrollTrigger: { trigger: '.timeline-section', start: 'top 65%' }
    });
    gsap.from('.timeline-step', {
      y: 30, opacity: 0, stagger: 0.2, duration: 0.6,
      scrollTrigger: { trigger: '.timeline-section', start: 'top 65%' }
    });
  }

  // General reveals
  gsap.utils.toArray('.reveal').forEach(el => {
    gsap.from(el, { y: 30, opacity: 0, duration: 0.7, ease: 'power2.out',
      scrollTrigger: { trigger: el, start: 'top 85%' }
    });
  });
});
""")

# Components
os.makedirs(f"{T}/src/components", exist_ok=True)

w(f"{T}/src/components/Nav.astro", """\
---
import site from '../content/site.json';
const navLinks = [
  { href: '/services', label: 'Services' },
  { href: '/team', label: 'Our Team' },
  { href: '/about', label: 'About' },
  { href: '/patient-info', label: 'Patient Info' },
  { href: '/insurance', label: 'Insurance' },
];
const currentPath = Astro.url.pathname;
---
<nav class="site-nav" aria-label="Main navigation">
  <div class="nav-inner container">
    <a href="/" class="nav-logo" aria-label={site.clinic_name + ' home'}>
      <span class="nav-logo-text">{site.clinic_name}</span>
    </a>
    <ul class="nav-links" role="list">
      {navLinks.map(link => (
        <li>
          <a href={link.href}
            class={`nav-link${currentPath.startsWith(link.href) ? ' active' : ''}`}
            aria-current={currentPath.startsWith(link.href) ? 'page' : undefined}>
            {link.label}
          </a>
        </li>
      ))}
    </ul>
    <a href="/contact" class="btn btn-accent nav-cta">Book Appointment</a>
    <details class="nav-mobile-toggle">
      <summary aria-label="Toggle navigation">
        <span class="hamburger" aria-hidden="true"><span></span><span></span><span></span></span>
      </summary>
      <div class="nav-mobile-panel">
        <ul role="list">
          {navLinks.map(link => <li><a href={link.href} class="mobile-link">{link.label}</a></li>)}
          <li><a href="/contact" class="btn btn-accent" style="width:100%;text-align:center;margin-top:1rem;">Book Appointment</a></li>
        </ul>
      </div>
    </details>
  </div>
</nav>
<style>
.site-nav { position:fixed;top:0;left:0;right:0;z-index:100;padding:1.25rem 0;transition:background 0.4s,box-shadow 0.4s,padding 0.4s; }
.site-nav.nav-scrolled { background:rgba(255,255,255,0.97);backdrop-filter:blur(12px);box-shadow:0 2px 20px rgba(10,46,110,0.1);padding:0.75rem 0; }
.nav-inner { display:flex;align-items:center;gap:2rem; }
.nav-logo-text { font-family:var(--font-display);font-size:1.25rem;color:white;transition:color 0.4s; }
.nav-scrolled .nav-logo-text { color:var(--color-brand-primary); }
.nav-links { display:flex;gap:1.75rem;list-style:none;margin:0 0 0 auto;padding:0; }
.nav-link { font-size:0.9rem;font-weight:600;color:rgba(255,255,255,0.85);padding-bottom:3px;border-bottom:2px solid transparent;transition:color 0.2s,border-color 0.2s; }
.nav-link:hover,.nav-link.active { color:white;border-bottom-color:var(--color-brand-accent); }
.nav-scrolled .nav-link { color:var(--color-text-secondary); }
.nav-scrolled .nav-link:hover,.nav-scrolled .nav-link.active { color:var(--color-brand-primary);border-bottom-color:var(--color-brand-accent); }
.nav-cta { font-size:0.875rem;padding:0.625rem 1.5rem; }
.nav-mobile-toggle { display:none;margin-left:auto; }
.nav-mobile-toggle > summary { list-style:none;cursor:pointer; }
.nav-mobile-toggle > summary::-webkit-details-marker { display:none; }
.hamburger { display:flex;flex-direction:column;gap:5px; }
.hamburger span { display:block;width:24px;height:2px;background:white;border-radius:2px;transition:var(--transition-base); }
.nav-scrolled .hamburger span { background:var(--color-text-primary); }
.nav-mobile-panel { position:fixed;inset:0;background:white;padding:6rem 2rem 2rem;z-index:-1; }
.nav-mobile-panel ul { list-style:none;padding:0;margin:0; }
.mobile-link { display:block;padding:1rem 0;font-size:1.25rem;font-weight:700;color:var(--color-brand-primary);border-bottom:1px solid var(--color-surface-alt); }
@media(max-width:1023px){.nav-links,.nav-cta{display:none;}.nav-mobile-toggle{display:block;}}
</style>
""")

w(f"{T}/src/components/Footer.astro", """\
---
import site from '../content/site.json';
const year = new Date().getFullYear();
---
<footer class="site-footer">
  <div class="footer-top container">
    <div class="footer-brand">
      <p class="footer-name">{site.clinic_name}</p>
      <p class="footer-tagline">{site.tagline}</p>
    </div>
    <div>
      <p class="footer-heading">Services</p>
      <ul class="footer-list" role="list">
        <li><a href="/services">Joint Replacement</a></li>
        <li><a href="/services">Sports Medicine</a></li>
        <li><a href="/services">Spine Care</a></li>
        <li><a href="/services">Physical Therapy</a></li>
      </ul>
    </div>
    <div>
      <p class="footer-heading">Hours</p>
      <p class="footer-hours">{site.hours}</p>
    </div>
    <div>
      <p class="footer-heading">Contact</p>
      <address class="footer-addr">
        <p>{site.address}</p>
        <p><a href={`tel:${site.phone}`}>{site.phone}</a></p>
        <p><a href={`mailto:${site.email}`}>{site.email}</a></p>
      </address>
      <a href="/contact" class="btn btn-accent" style="margin-top:1.25rem;">Book Now</a>
    </div>
  </div>
  <div class="footer-bottom container">
    <p>&copy; {year} {site.clinic_name}. All rights reserved.</p>
    <ul role="list"><li><a href="/privacy">Privacy</a></li><li><a href="/terms">Terms</a></li></ul>
  </div>
</footer>
<style>
.site-footer { background:#0A1F4D;color:rgba(255,255,255,0.65); }
.footer-top { display:grid;grid-template-columns:1.5fr 1fr 1fr 1.25fr;gap:3rem;padding:4rem 0 3rem; }
.footer-name { font-family:var(--font-display);font-size:1.375rem;color:white;margin:0 0 0.5rem; }
.footer-tagline { color:var(--color-brand-accent);margin:0; }
.footer-heading { font-size:0.75rem;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;color:var(--color-brand-accent);margin:0 0 0.875rem; }
.footer-list { list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:0.5rem; }
.footer-list a,.footer-addr a { color:rgba(255,255,255,0.6);transition:color 0.2s; }
.footer-list a:hover,.footer-addr a:hover { color:var(--color-brand-accent); }
.footer-hours,.footer-addr { color:rgba(255,255,255,0.6);font-style:normal;line-height:1.9;margin:0; }
.footer-bottom { display:flex;justify-content:space-between;align-items:center;padding:1.25rem 0 2rem;border-top:1px solid rgba(255,255,255,0.1);font-size:0.8125rem;color:rgba(255,255,255,0.35); }
.footer-bottom ul { list-style:none;padding:0;margin:0;display:flex;gap:1.5rem; }
.footer-bottom a { color:inherit;transition:color 0.2s; }
.footer-bottom a:hover { color:var(--color-brand-accent); }
@media(max-width:1023px){.footer-top{grid-template-columns:1fr 1fr;gap:2rem;}}
@media(max-width:639px){.footer-top{grid-template-columns:1fr;}.footer-bottom{flex-direction:column;gap:0.75rem;}}
</style>
""")

w(f"{T}/src/components/CTASection.astro", """\
---
import site from '../content/site.json';
const { headline='Ready to Get Back in Motion?', subtext='Board-certified orthopedic surgeons. Personalized care. Proven results.', ctaLabel=site.main_cta, ctaHref='/contact' } = Astro.props;
---
<section class="cta-section">
  <div class="container cta-inner">
    <div class="reveal"><h2>{headline}</h2><p>{subtext}</p></div>
    <a href={ctaHref} class="btn btn-white">{ctaLabel}</a>
  </div>
</section>
<style>
.cta-section { background:var(--color-brand-accent);padding:5rem 0; }
.cta-inner { display:flex;align-items:center;justify-content:space-between;gap:2rem;flex-wrap:wrap; }
.cta-inner h2 { font-family:var(--font-display);font-size:clamp(1.75rem,3vw,2.75rem);color:white;margin:0 0 0.5rem; }
.cta-inner p { color:rgba(255,255,255,0.85);margin:0; }
@media(max-width:767px){.cta-inner{flex-direction:column;text-align:center;}}
</style>
""")

os.makedirs(f"{T}/src/pages/services", exist_ok=True)

w(f"{T}/src/pages/index.astro", """\
---
import Layout from '../layouts/Layout.astro';
import Nav from '../components/Nav.astro';
import Footer from '../components/Footer.astro';
import CTASection from '../components/CTASection.astro';
import site from '../content/site.json';

const siteUrl = import.meta.env.SITE || 'https://CLINIC_SUBDOMAIN.medplatform.io';
const schema = {
  "@context": "https://schema.org",
  "@type": "MedicalOrganization",
  "name": site.clinic_name,
  "url": siteUrl,
  "telephone": site.phone,
  "medicalSpecialty": "Orthopedic Surgery",
};

const stats = [
  { value: 5000, suffix: '+', label: 'Procedures Performed' },
  { value: 20, suffix: '+ Yrs', label: 'Combined Experience' },
  { value: 98, suffix: '%', label: 'Patient Satisfaction' },
  { value: 4, suffix: '', label: 'Board-Certified Surgeons' },
];

const defaultServices = [
  { name: 'Joint Replacement', description: 'Hip and knee replacement with minimally invasive techniques and rapid recovery protocols.', slug: 'joint-replacement', featured: true },
  { name: 'Sports Medicine', description: 'From weekend warriors to elite athletes — expert care for sports injuries and performance.', slug: 'sports-medicine', featured: true },
  { name: 'Spine Care', description: 'Comprehensive evaluation and treatment of neck, back, and spinal disorders.', slug: 'spine-care' },
  { name: 'Fracture Care', description: 'Immediate and expert management of acute fractures and trauma.', slug: 'fracture-care' },
  { name: 'Physical Therapy', description: 'Integrated rehabilitation programs designed for complete recovery and long-term strength.', slug: 'physical-therapy' },
  { name: 'Arthroscopy', description: 'Minimally invasive joint surgery for faster healing and less post-operative pain.', slug: 'arthroscopy' },
];
---
<Layout title={`${site.clinic_name} | Expert Orthopedic Care`} description={site.tagline} schema={schema}>
  <Nav />

  <!-- HERO: Split screen -->
  <section class="hero" aria-labelledby="hero-heading">
    <div class="hero-image-panel" aria-hidden="true"></div>
    <div class="hero-content-panel">
      <div class="hero-content">
        <p class="hero-overline">Expert Orthopedic Care</p>
        <h1 id="hero-heading">{site.hero_headline || 'Move Without Limits'}</h1>
        <p class="hero-sub">{site.hero_subtext}</p>
        <div class="hero-ctas">
          <a href="/contact" class="btn btn-primary">Book Consultation</a>
          <a href="/services" class="btn btn-outline">Our Services</a>
        </div>
      </div>
    </div>
  </section>

  <!-- STATS BAR -->
  <section class="stats-bar" aria-label="Practice statistics">
    <div class="container stats-inner">
      {stats.map(s => (
        <div class="stat-item">
          <p class="stat-number" data-target={s.value} data-suffix={s.suffix}>0</p>
          <p class="stat-label">{s.label}</p>
        </div>
      ))}
    </div>
  </section>

  <!-- SERVICES: Asymmetric grid -->
  <section class="section" aria-labelledby="services-heading">
    <div class="container">
      <header class="section-header reveal">
        <p class="section-tag">What We Treat</p>
        <h2 id="services-heading">Expert Orthopedic Services</h2>
      </header>
      <div class="services-asym">
        <a href={`/services/${defaultServices[0].slug}`} class="service-feature reveal" aria-label={defaultServices[0].name}>
          <div class="service-feature-img" aria-hidden="true"></div>
          <div class="service-feature-body">
            <span class="service-tag">Featured</span>
            <h3>{defaultServices[0].name}</h3>
            <p>{defaultServices[0].description}</p>
            <span class="arrow-link">Learn More →</span>
          </div>
        </a>
        <div class="services-stack">
          {defaultServices.slice(1, 3).map(s => (
            <a href={`/services/${s.slug}`} class="service-stack-card reveal" aria-label={s.name}>
              <h3>{s.name}</h3>
              <p>{s.description}</p>
              <span class="arrow-link">→</span>
            </a>
          ))}
        </div>
      </div>
      <div class="services-row">
        {defaultServices.slice(3).map(s => (
          <a href={`/services/${s.slug}`} class="service-row-card reveal" aria-label={s.name}>
            <h3>{s.name}</h3>
            <p>{s.description}</p>
          </a>
        ))}
      </div>
      <div style="text-align:center;margin-top:3rem">
        <a href="/services" class="btn btn-primary reveal">View All Services</a>
      </div>
    </div>
  </section>

  <!-- PROCEDURE TIMELINE -->
  <section class="section timeline-section" style="background:var(--color-surface-alt)" aria-labelledby="timeline-heading">
    <div class="container">
      <header class="section-header reveal">
        <p class="section-tag">Your Journey</p>
        <h2 id="timeline-heading">From Consultation to Recovery</h2>
      </header>
      <div class="timeline-track">
        <div class="timeline-line" aria-hidden="true"></div>
        {[
          { n:'1', title:'Consultation', desc:'Thorough evaluation and imaging review' },
          { n:'2', title:'Diagnosis', desc:'Precise diagnosis and treatment planning' },
          { n:'3', title:'Treatment', desc:'Expert surgical or non-surgical care' },
          { n:'4', title:'Recovery', desc:'Integrated rehabilitation and follow-up' },
        ].map(step => (
          <div class="timeline-step">
            <div class="timeline-dot" aria-hidden="true">{step.n}</div>
            <h3>{step.title}</h3>
            <p>{step.desc}</p>
          </div>
        ))}
      </div>
    </div>
  </section>

  <!-- TESTIMONIAL -->
  <section class="section" aria-labelledby="testimonial-heading">
    <div class="container testimonial-wrap">
      <div class="testimonial-quote-block reveal">
        <svg width="48" height="36" viewBox="0 0 48 36" fill="none" aria-hidden="true">
          <path d="M0 36V21.6C0 9.6 7.2 2.4 21.6 0L24 4.8C16.8 6.4 13.2 10.4 12 16.8H21.6V36H0ZM26.4 36V21.6C26.4 9.6 33.6 2.4 48 0L50.4 4.8C43.2 6.4 39.6 10.4 38.4 16.8H48V36H26.4Z" fill="currentColor" opacity="0.15"/>
        </svg>
        <blockquote>
          <p>"After my knee replacement I was back hiking in 8 weeks. The team here didn't just fix my knee — they gave me my life back."</p>
          <footer><strong>James M.</strong> — Total Knee Replacement</footer>
        </blockquote>
      </div>
    </div>
  </section>

  <CTASection />
  <Footer />
</Layout>

<style>
.hero { display:grid;grid-template-columns:55% 45%;min-height:100svh; }
.hero-image-panel {
  background:linear-gradient(135deg,#0A2E6E 0%,#1565C0 100%);
  clip-path:polygon(0 0,92% 0,100% 100%,0 100%);
  position:relative;
}
.hero-image-panel::after {
  content:'';position:absolute;inset:0;
  background:radial-gradient(ellipse at 30% 60%,rgba(255,107,53,0.15),transparent 60%);
}
.hero-content-panel { display:flex;align-items:center;padding:8rem 4rem 4rem 3rem; }
.hero-content { max-width:480px; }
.hero-overline { font-size:0.8rem;font-weight:700;letter-spacing:0.3em;text-transform:uppercase;color:var(--color-brand-accent);margin:0 0 1rem; }
h1 { margin:0 0 1.25rem;color:var(--color-text-primary); }
.hero-sub { font-size:1.125rem;color:var(--color-text-secondary);margin:0 0 2.5rem;line-height:1.7; }
.hero-ctas { display:flex;gap:1rem;flex-wrap:wrap; }

.stats-bar { background:var(--color-brand-primary);border-top:3px solid var(--color-brand-accent); }
.stats-inner { display:grid;grid-template-columns:repeat(4,1fr);padding:3rem 0; }
.stat-item { text-align:center;padding:1.5rem 1rem;border-right:1px solid rgba(255,255,255,0.1); }
.stat-item:last-child { border-right:none; }
.stat-number { font-family:var(--font-stats);font-size:clamp(2.5rem,4vw,4rem);color:var(--color-brand-accent);margin:0 0 0.25rem;line-height:1; }
.stat-label { color:rgba(255,255,255,0.7);font-size:0.875rem;margin:0; }

.section-header { margin-bottom:3.5rem; }
.section-tag { font-size:0.75rem;font-weight:700;letter-spacing:0.2em;text-transform:uppercase;color:var(--color-brand-accent);margin:0 0 0.5rem; }
.section-header h2 { margin:0;color:var(--color-brand-primary); }

.services-asym { display:grid;grid-template-columns:60% 40%;gap:1.5rem;margin-bottom:1.5rem; }
.service-feature { display:flex;flex-direction:column;background:var(--color-surface-alt);border-radius:var(--radius-xl);overflow:hidden;transition:transform 0.3s,box-shadow 0.3s; }
.service-feature:hover { transform:translateY(-6px);box-shadow:var(--shadow-md); }
.service-feature-img { height:280px;background:linear-gradient(135deg,#0A2E6E,#1565C0); }
.service-feature-body { padding:2rem; }
.service-tag { font-size:0.7rem;font-weight:700;letter-spacing:0.15em;text-transform:uppercase;color:var(--color-brand-accent); }
.service-feature h3 { font-family:var(--font-display);font-size:1.5rem;color:var(--color-brand-primary);margin:0.5rem 0 0.75rem; }
.service-feature p { color:var(--color-text-secondary);margin:0 0 1.25rem;line-height:1.7; }
.services-stack { display:flex;flex-direction:column;gap:1.5rem; }
.service-stack-card { display:flex;flex-direction:column;padding:2rem;background:var(--color-surface-alt);border-radius:var(--radius-xl);flex:1;transition:transform 0.3s; }
.service-stack-card:hover { transform:translateY(-4px); }
.service-stack-card h3 { font-family:var(--font-display);font-size:1.25rem;color:var(--color-brand-primary);margin:0 0 0.5rem; }
.service-stack-card p { color:var(--color-text-secondary);font-size:0.9rem;flex:1;margin:0 0 1rem;line-height:1.6; }
.services-row { display:grid;grid-template-columns:repeat(3,1fr);gap:1.5rem; }
.service-row-card { padding:1.75rem;border:1px solid rgba(10,46,110,0.1);border-radius:var(--radius-lg);transition:border-color 0.3s,box-shadow 0.3s; }
.service-row-card:hover { border-color:var(--color-brand-accent);box-shadow:var(--shadow-sm); }
.service-row-card h3 { font-family:var(--font-display);font-size:1.125rem;color:var(--color-brand-primary);margin:0 0 0.5rem; }
.service-row-card p { color:var(--color-text-secondary);font-size:0.875rem;margin:0;line-height:1.6; }
.arrow-link { color:var(--color-brand-accent);font-weight:700;font-size:0.875rem; }

.timeline-track { display:grid;grid-template-columns:repeat(4,1fr);gap:2rem;position:relative;padding-top:3rem; }
.timeline-line { position:absolute;top:13px;left:12%;right:12%;height:3px;background:var(--color-brand-accent);transform-origin:left center; }
.timeline-dot { width:28px;height:28px;border-radius:50%;background:var(--color-brand-accent);color:white;font-weight:700;font-size:0.875rem;display:flex;align-items:center;justify-content:center;margin:0 auto 1rem; }
.timeline-step { text-align:center; }
.timeline-step h3 { font-family:var(--font-display);font-size:1.125rem;color:var(--color-brand-primary);margin:0 0 0.5rem; }
.timeline-step p { font-size:0.875rem;color:var(--color-text-secondary);margin:0; }

.testimonial-wrap { max-width:780px;margin:0 auto; }
.testimonial-quote-block { padding:3rem; background:var(--color-surface-alt);border-left:4px solid var(--color-brand-accent);border-radius:0 var(--radius-xl) var(--radius-xl) 0; }
.testimonial-quote-block blockquote p { font-size:clamp(1.125rem,2vw,1.375rem);line-height:1.7;color:var(--color-text-primary);margin:1rem 0; }
.testimonial-quote-block footer { color:var(--color-text-secondary);font-size:0.9rem; }
.testimonial-quote-block strong { color:var(--color-brand-primary); }

@media(max-width:1023px) {
  .hero { grid-template-columns:1fr; }
  .hero-image-panel { height:360px;clip-path:none; }
  .hero-content-panel { padding:3rem 2rem; }
  .services-asym { grid-template-columns:1fr; }
  .services-row { grid-template-columns:1fr 1fr; }
  .stats-inner { grid-template-columns:repeat(2,1fr); }
  .stat-item:nth-child(2) { border-right:none; }
  .timeline-track { grid-template-columns:1fr 1fr;row-gap:3rem; }
  .timeline-line { display:none; }
}
@media(max-width:639px) {
  .services-row { grid-template-columns:1fr; }
  .timeline-track { grid-template-columns:1fr; }
  .hero-ctas { flex-direction:column; }
}
</style>
""")

# services, team, about, contact, insurance, patient-info for orthopedics
for pagename, title_slug, heading in [
    ("services", "Services", "Our Orthopedic Services"),
    ("team", "Our Team", "Meet Our Surgeons"),
    ("about", "About", "About Our Practice"),
    ("contact", "Contact", "Schedule an Appointment"),
    ("insurance", "Insurance", "Insurance & Billing"),
    ("patient-info", "Patient Info", "Patient Information"),
]:
    w(f"{T}/src/pages/{pagename}.astro", f"""\
---
import Layout from '../layouts/Layout.astro';
import Nav from '../components/Nav.astro';
import Footer from '../components/Footer.astro';
import CTASection from '../components/CTASection.astro';
import site from '../content/site.json';
---
<Layout title={{`{title_slug} | ${{site.clinic_name}}`}} description={{`{heading} at ${{site.clinic_name}}.`}}>
  <Nav />
  <section class="page-hero">
    <div class="container">
      <nav aria-label="Breadcrumb" class="breadcrumb">
        <a href="/">Home</a> <span>/</span> <span aria-current="page">{title_slug}</span>
      </nav>
      <h1 class="reveal">{heading}</h1>
    </div>
  </section>
  <section class="section">
    <div class="container">
      <p class="reveal" style="color:var(--color-text-secondary);font-size:1.125rem;max-width:640px">
        {{site.tagline}} — contact us to learn more about our services.
      </p>
      <a href="/contact" class="btn btn-primary reveal" style="margin-top:2rem">Book Appointment</a>
    </div>
  </section>
  <CTASection />
  <Footer />
</Layout>
<style>
.page-hero {{ background:linear-gradient(135deg,#0A2E6E,#1565C0);padding:9rem 0 4rem;color:white; }}
.breadcrumb {{ font-size:0.875rem;color:rgba(255,255,255,0.6);margin-bottom:1.25rem;display:flex;gap:0.5rem;align-items:center; }}
.breadcrumb a {{ color:rgba(255,255,255,0.6); }}
.page-hero h1 {{ color:white;margin:0;font-size:clamp(2rem,4vw,3.25rem); }}
</style>
""")

w(f"{T}/src/pages/services/index.astro", """\
---
import Layout from '../../layouts/Layout.astro';
import Nav from '../../components/Nav.astro';
import Footer from '../../components/Footer.astro';
import CTASection from '../../components/CTASection.astro';
import site from '../../content/site.json';
const services = [
  { name:'Joint Replacement',description:'Hip and knee replacement with rapid recovery.',slug:'joint-replacement'},
  { name:'Sports Medicine',description:'Expert care for athletic injuries.',slug:'sports-medicine'},
  { name:'Spine Care',description:'Neck, back, and spinal disorder treatment.',slug:'spine-care'},
  { name:'Fracture Care',description:'Immediate management of acute fractures.',slug:'fracture-care'},
  { name:'Physical Therapy',description:'Integrated rehabilitation programs.',slug:'physical-therapy'},
  { name:'Arthroscopy',description:'Minimally invasive joint surgery.',slug:'arthroscopy'},
];
---
<Layout title={`Services | ${site.clinic_name}`} description={`Full range of orthopedic services at ${site.clinic_name}.`}>
  <Nav />
  <section class="page-hero">
    <div class="container">
      <nav aria-label="Breadcrumb" class="breadcrumb"><a href="/">Home</a><span>/</span><span aria-current="page">Services</span></nav>
      <h1 class="reveal">Our Services</h1>
    </div>
  </section>
  <section class="section">
    <div class="container services-grid">
      {services.map(s => (
        <a href={`/services/${s.slug}`} class="svc-card reveal">
          <h2>{s.name}</h2>
          <p>{s.description}</p>
          <span>Learn More →</span>
        </a>
      ))}
    </div>
  </section>
  <CTASection />
  <Footer />
</Layout>
<style>
.page-hero{background:linear-gradient(135deg,#0A2E6E,#1565C0);padding:9rem 0 4rem;color:white;}
.breadcrumb{font-size:0.875rem;color:rgba(255,255,255,0.6);margin-bottom:1.25rem;display:flex;gap:0.5rem;}
.breadcrumb a{color:rgba(255,255,255,0.6);}
.page-hero h1{color:white;margin:0;font-size:clamp(2rem,4vw,3.25rem);}
.services-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:2rem;}
.svc-card{padding:2.25rem 2rem;border:1px solid rgba(10,46,110,0.12);border-radius:var(--radius-xl);display:flex;flex-direction:column;gap:0.75rem;transition:transform 0.3s,box-shadow 0.3s;}
.svc-card:hover{transform:translateY(-5px);box-shadow:var(--shadow-md);}
.svc-card h2{font-family:var(--font-display);font-size:1.25rem;color:var(--color-brand-primary);margin:0;}
.svc-card p{color:var(--color-text-secondary);font-size:0.9rem;flex:1;margin:0;line-height:1.65;}
.svc-card span{color:var(--color-brand-accent);font-weight:700;font-size:0.875rem;}
@media(max-width:1023px){.services-grid{grid-template-columns:repeat(2,1fr);}}
@media(max-width:639px){.services-grid{grid-template-columns:1fr;}}
</style>
""")

w(f"{T}/src/pages/services/[slug].astro", """\
---
import Layout from '../../layouts/Layout.astro';
import Nav from '../../components/Nav.astro';
import Footer from '../../components/Footer.astro';
import CTASection from '../../components/CTASection.astro';
import site from '../../content/site.json';

export async function getStaticPaths() {
  const services = [
    {name:'Joint Replacement',description:'Hip and knee replacement with rapid recovery protocols.',slug:'joint-replacement'},
    {name:'Sports Medicine',description:'Expert care for athletic injuries.',slug:'sports-medicine'},
    {name:'Spine Care',description:'Neck, back, and spinal disorder treatment.',slug:'spine-care'},
    {name:'Fracture Care',description:'Immediate management of acute fractures.',slug:'fracture-care'},
    {name:'Physical Therapy',description:'Integrated rehabilitation programs.',slug:'physical-therapy'},
    {name:'Arthroscopy',description:'Minimally invasive joint surgery.',slug:'arthroscopy'},
  ];
  return services.map(s => ({ params: { slug: s.slug }, props: { service: s } }));
}
const { service } = Astro.props;
const faqs = [
  { q:`What does ${service.name} treatment involve?`, a:service.description },
  { q:'How long is the recovery?', a:'Recovery varies by procedure. Your surgeon will provide a personalized timeline during consultation.' },
  { q:'Is this covered by insurance?', a:'We accept most major insurance plans. Our team will verify your benefits before your appointment.' },
];
const schema = {
  "@context":"https://schema.org","@type":"MedicalProcedure",
  "name":service.name,"description":service.description,
  "provider":{"@type":"MedicalOrganization","name":site.clinic_name}
};
---
<Layout title={`${service.name} | ${site.clinic_name}`} description={service.description} schema={schema}>
  <Nav />
  <section class="page-hero">
    <div class="container">
      <nav aria-label="Breadcrumb" class="breadcrumb">
        <a href="/">Home</a><span>/</span><a href="/services">Services</a><span>/</span><span aria-current="page">{service.name}</span>
      </nav>
      <h1 class="reveal">{service.name}</h1>
    </div>
  </section>
  <div class="service-layout container">
    <main>
      <section class="svc-block reveal"><h2>About {service.name}</h2><p>{service.description}</p></section>
      <section class="svc-block reveal">
        <h2>Frequently Asked Questions</h2>
        {faqs.map(f => (
          <details class="faq-item">
            <summary class="faq-q">{f.q}</summary>
            <p class="faq-a">{f.a}</p>
          </details>
        ))}
      </section>
    </main>
    <aside class="sidebar">
      <div class="sidebar-card">
        <h3>Book a Consultation</h3>
        <p>Schedule with a board-certified orthopedic surgeon today.</p>
        <a href="/contact" class="btn btn-accent" style="width:100%;text-align:center;">Schedule Now</a>
        <hr/><p><strong>Call:</strong> <a href={`tel:${site.phone}`}>{site.phone}</a></p>
      </div>
    </aside>
  </div>
  <CTASection />
  <Footer />
</Layout>
<style>
.page-hero{background:linear-gradient(135deg,#0A2E6E,#1565C0);padding:9rem 0 4rem;color:white;}
.breadcrumb{font-size:0.875rem;color:rgba(255,255,255,0.6);margin-bottom:1.25rem;display:flex;gap:0.5rem;flex-wrap:wrap;}
.breadcrumb a{color:rgba(255,255,255,0.6);}
.page-hero h1{color:white;margin:0;}
.service-layout{display:grid;grid-template-columns:1fr 320px;gap:4rem;padding:4rem 0 6rem;align-items:start;}
.svc-block{margin-bottom:2.5rem;}
.svc-block h2{font-family:var(--font-display);font-size:1.625rem;color:var(--color-brand-primary);margin:0 0 1rem;}
.svc-block p{color:var(--color-text-secondary);line-height:1.8;}
.faq-item{border-bottom:1px solid rgba(10,46,110,0.1);padding:1rem 0;}
.faq-q{font-weight:600;color:var(--color-text-primary);cursor:pointer;list-style:none;display:flex;justify-content:space-between;}
.faq-q::-webkit-details-marker{display:none;}
.faq-q::after{content:"+";color:var(--color-brand-accent);}
details[open] .faq-q::after{content:"−";}
.faq-a{color:var(--color-text-secondary);margin:.75rem 0 0;line-height:1.7;}
.sidebar-card{position:sticky;top:7rem;background:var(--color-surface-alt);border-radius:var(--radius-xl);padding:2rem;}
.sidebar-card h3{font-family:var(--font-display);font-size:1.25rem;color:var(--color-brand-primary);margin:0 0 0.75rem;}
.sidebar-card p{color:var(--color-text-secondary);margin:0 0 1.25rem;font-size:0.9rem;}
.sidebar-card hr{border:none;border-top:1px solid rgba(10,46,110,0.1);margin:1.25rem 0;}
.sidebar-card a{color:var(--color-brand-primary);}
@media(max-width:1023px){.service-layout{grid-template-columns:1fr;}}
</style>
""")

w(f"{T}/src/pages/indexnow.txt.js", """\
export async function GET() {
  const key = import.meta.env.PUBLIC_INDEXNOW_KEY || '';
  return new Response(key, { headers: { 'Content-Type': 'text/plain' } });
}
""")

print("ORTHOPEDICS DONE")
PYEOF
