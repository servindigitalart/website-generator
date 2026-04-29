document.addEventListener('DOMContentLoaded', () => {
  if (typeof gsap === 'undefined') return;
  gsap.registerPlugin(ScrollTrigger);

  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Custom cursor
  const cursor = document.querySelector('.cursor');
  const cursorDot = document.querySelector('.cursor-dot');
  if (cursor && cursorDot && window.innerWidth > 768 && !prefersReducedMotion) {
    document.addEventListener('mousemove', (e) => {
      gsap.to(cursor, { x: e.clientX, y: e.clientY, duration: 0.5, ease: 'power2.out' });
      gsap.to(cursorDot, { x: e.clientX, y: e.clientY, duration: 0.1 });
    });
    document.querySelectorAll('.cta-magnetic').forEach(btn => {
      btn.addEventListener('mouseenter', () => gsap.to(cursor, { scale: 3, duration: 0.3 }));
      btn.addEventListener('mouseleave', () => {
        gsap.to(cursor, { scale: 1, duration: 0.3 });
        gsap.to(btn, { x: 0, y: 0, duration: 0.5, ease: 'elastic.out(1,0.5)' });
      });
      btn.addEventListener('mousemove', (e) => {
        const rect = btn.getBoundingClientRect();
        const x = (e.clientX - rect.left - rect.width / 2) * 0.3;
        const y = (e.clientY - rect.top - rect.height / 2) * 0.3;
        gsap.to(btn, { x, y, duration: 0.3, ease: 'power2.out' });
      });
    });
  }

  if (prefersReducedMotion) return;

  // Letter-by-letter hero headline
  const headline = document.querySelector('.hero-headline');
  if (headline) {
    const spans = headline.querySelectorAll('.hero-line-1, .hero-line-2');
    spans.forEach(span => {
      const text = span.textContent || '';
      span.innerHTML = text.split('').map(
        char => char === ' '
          ? '<span aria-hidden="true">&nbsp;</span>'
          : `<span class="letter" aria-hidden="true">${char}</span>`
      ).join('');
    });
    gsap.from('.letter', { y: 60, opacity: 0, duration: 0.8, ease: 'power3.out', stagger: 0.03 });
  }

  // Hero elements
  gsap.from('.hero-line', { scaleX: 0, transformOrigin: 'left center', duration: 0.8, ease: 'power2.out' });
  gsap.from('.hero-animate', { y: 40, opacity: 0, duration: 0.9, ease: 'power3.out', stagger: 0.2, delay: 0.5 });

  // Nav scroll
  const nav = document.querySelector('.site-nav');
  if (nav) {
    ScrollTrigger.create({
      start: 'top -80',
      onUpdate: self => nav.classList.toggle('nav-scrolled', self.progress > 0)
    });
  }

  // Lightweight parallax
  window.addEventListener('scroll', () => {
    document.documentElement.style.setProperty('--scroll-y', window.scrollY.toString());
  }, { passive: true });

  // General reveals
  gsap.utils.toArray('.reveal').forEach(el => {
    gsap.from(el, {
      y: 30, opacity: 0, duration: 0.8, ease: 'power2.out',
      scrollTrigger: { trigger: el, start: 'top 85%' }
    });
  });
});
