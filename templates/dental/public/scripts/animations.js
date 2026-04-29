document.addEventListener('DOMContentLoaded', () => {
  if (typeof gsap === 'undefined') return;
  gsap.registerPlugin(ScrollTrigger);

  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (prefersReducedMotion) return;

  // Hero entrance
  gsap.from('.hero-animate', { y: 40, opacity: 0, duration: 0.9, ease: 'power3.out', stagger: 0.2 });

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
      val: target, duration: 2, ease: 'power1.out',
      scrollTrigger: { trigger: el, start: 'top 80%', once: true },
      onUpdate() { el.textContent = Math.round(obj.val).toLocaleString() + suffix; }
    });
  });

  // Service cards stagger
  if (document.querySelector('.services-grid')) {
    gsap.from('.services-grid > *', {
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
