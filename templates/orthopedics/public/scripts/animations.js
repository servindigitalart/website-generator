document.addEventListener('DOMContentLoaded', () => {
  if (typeof gsap === 'undefined') return;
  gsap.registerPlugin(ScrollTrigger);

  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (prefersReducedMotion) return;

  // Split hero entrance
  gsap.from('.hero-image-panel', { x: -60, opacity: 0, duration: 0.8, ease: 'power3.out' });
  gsap.from('.hero-content > *', { x: 40, opacity: 0, duration: 0.7, ease: 'power2.out', stagger: 0.15, delay: 0.2 });

  // Nav scroll
  const nav = document.querySelector('.site-nav');
  if (nav) {
    ScrollTrigger.create({
      start: 'top -80',
      onUpdate: self => nav.classList.toggle('nav-scrolled', self.progress > 0)
    });
  }

  // Stat counters
  document.querySelectorAll('.stat-number').forEach(el => {
    const target = parseInt(el.dataset.target || '0');
    const suffix = el.dataset.suffix || '';
    const obj = { val: 0 };
    gsap.to(obj, {
      val: target, duration: 2.5, ease: 'power2.out',
      scrollTrigger: { trigger: el, start: 'top 80%', once: true },
      onUpdate() { el.textContent = Math.round(obj.val).toLocaleString() + suffix; }
    });
  });

  // Procedure timeline
  if (document.querySelector('.timeline-line')) {
    gsap.from('.timeline-line', {
      scaleX: 0, transformOrigin: 'left center', duration: 1.5, ease: 'power2.inOut',
      scrollTrigger: { trigger: '.timeline-section', start: 'top 60%' }
    });
    gsap.from('.timeline-step', {
      y: 30, opacity: 0, stagger: 0.2, duration: 0.6,
      scrollTrigger: { trigger: '.timeline-section', start: 'top 60%' }
    });
  }

  // Service cards
  if (document.querySelector('.services-grid')) {
    gsap.from('.service-card', {
      y: 50, opacity: 0, duration: 0.6, stagger: 0.1, ease: 'power2.out',
      scrollTrigger: { trigger: '.services-grid', start: 'top 80%' }
    });
  }

  // General reveals
  gsap.utils.toArray('.reveal').forEach(el => {
    gsap.from(el, {
      y: 30, opacity: 0, duration: 0.7, ease: 'power2.out',
      scrollTrigger: { trigger: el, start: 'top 85%' }
    });
  });
});
