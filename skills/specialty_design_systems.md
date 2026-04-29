# Design Systems by Medical Specialty

## Dermatology — Clean Luxury
Identity: Skin health as beauty and confidence
Primary color: #4A3F7A (deep purple — trust + premium)
Secondary: #C4A882 (warm gold — skin tone)
Accent: #F0E6D3 (cream — softness)
Background: #FAFAFA (near white)
Text: #2D2D2D (near black)

Typography:
  Display: Cormorant Garant (serif — luxury editorial)
  Body: DM Sans (clean readable sans)
  CTA: DM Sans 600 weight

Animation signature:
  Hero: full-bleed image, text fades in from bottom 0.8s ease-out
  Services: cards float up on scroll (GSAP ScrollTrigger, stagger 0.15s)
  CTA button: subtle glow pulse on hover
  Page transitions: elegant cross-fade 0.4s

Layout signature:
  Large whitespace, generous padding (80-120px sections)
  Before/after image slider (Swiper.js)
  Sticky header: transparent → white on scroll

## Orthopedics — Bold Professional
Identity: Strength, movement, recovery, expertise
Primary color: #0A2E6E (navy blue — authority + trust)
Secondary: #1565C0 (bright blue — energy)
Accent: #FF6B35 (orange — vitality + action)
Background: #FFFFFF
Text: #1A1A2E

Typography:
  Display: Neue Haas Grotesk Display (bold sans — power)
  Body: Inter (clean professional)
  Stats: Bebas Neue (dramatic numbers)

Animation signature:
  Hero: split screen — left image slides in, right copy types in
  Stats: GSAP counter animation (0 → 5000+ in 2s on scroll)
  Services: asymmetric grid reveals left-right alternating
  CTA button: fill sweep animation on hover

Layout signature:
  Bold section dividers, diagonal cuts between sections
  Full-width stats bar with animated counters
  Video testimonials section
  Sticky CTA strip on mobile

## Dental — Bright Friendly
Identity: Comfortable, approachable, smile transformation
Primary color: #00B4D8 (bright teal — cleanliness + trust)
Secondary: #FF6B6B (coral — warmth + friendliness)
Accent: #90E0EF (light blue — clean fresh)
Background: #FFFFFF
Text: #023E8A (deep blue — professional)

Typography:
  Display: Plus Jakarta Sans (rounded modern — friendly)
  Body: Plus Jakarta Sans (consistent, approachable)
  Accent: Nunito (playful for CTAs)

Animation signature:
  Hero: centered layout, headline word-by-word reveal
  Services: flip cards on hover (front: service name, back: detail)
  Testimonials: Swiper carousel with patient photos
  Booking CTA: bouncy entrance animation (spring physics)

Layout signature:
  Rounded corners everywhere (--radius-xl: 24px)
  Pastel section backgrounds alternating
  Floating WhatsApp/book button
  Insurance logos scrolling marquee

## Med Spa — Dark Editorial Luxury
Identity: Transformation, exclusivity, medical-grade premium
Primary color: #1A1A2E (near black — luxury editorial)
Secondary: #C9A96E (gold — premium exclusivity)
Accent: #E8D5B7 (champagne — warmth)
Background: #0F0F1A (deep dark)
Text: #F5F0E8 (warm white — readable on dark)

Typography:
  Display: Playfair Display (elegant serif — fashion editorial)
  Body: Helvetica Neue / system (minimalist clean)
  Price: Cormorant (refined numerals)

Animation signature:
  Hero: video background, text reveals letter by letter (GSAP SplitText)
  Cursor: custom magnetic cursor following mouse (GSAP)
  Services: horizontal scroll section (Locomotive Scroll)
  Images: parallax depth effect (GSAP ScrollTrigger)
  CTA: elegant underline draw animation on hover

Layout signature:
  Dark backgrounds dominant
  Large editorial imagery, full bleed
  Gold accent lines as dividers
  Membership/VIP section with exclusive feel
  Floating booking widget (glass morphism style)
