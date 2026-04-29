// IntersectionObserver-based reveals (no GSAP dependency)
(function () {
  // Reveal on scroll
  const revealObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          revealObserver.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.12, rootMargin: '0px 0px -40px 0px' }
  );
  document.querySelectorAll('.reveal').forEach((el) => revealObserver.observe(el));

  // Nav: add scrolled class for background
  const nav = document.querySelector('.site-nav');
  if (nav) {
    const onScroll = () => {
      nav.classList.toggle('scrolled', window.scrollY > 50);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  // Stats counter animation
  const counterObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const el = entry.target;
        const target = parseInt(el.dataset.count || '0', 10);
        const suffix = el.dataset.suffix || '';
        const duration = 1600;
        const step = 16;
        const increment = target / (duration / step);
        let current = 0;
        const timer = setInterval(() => {
          current = Math.min(current + increment, target);
          el.textContent = Math.floor(current).toLocaleString() + suffix;
          if (current >= target) clearInterval(timer);
        }, step);
        counterObserver.unobserve(el);
      });
    },
    { threshold: 0.5 }
  );
  document.querySelectorAll('[data-count]').forEach((el) => counterObserver.observe(el));

  // Mobile nav toggle
  const menuBtn = document.querySelector('.nav-menu-btn');
  const mobileMenu = document.querySelector('.nav-mobile');
  if (menuBtn && mobileMenu) {
    menuBtn.addEventListener('click', () => {
      const open = mobileMenu.classList.toggle('open');
      menuBtn.setAttribute('aria-expanded', String(open));
    });
  }
})();
