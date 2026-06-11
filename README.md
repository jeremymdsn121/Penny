# Casa Cafe — Website

A responsive, single-page marketing site for **Casa Cafe**, a family-run Tex-Mex
breakfast & lunch spot in Creedmoor, TX. Built as static HTML/CSS/JS — no build
step, no dependencies. Open `index.html` in any browser, or serve the folder.

```bash
# from this directory
python3 -m http.server 8080
# then open http://localhost:8080
```

## Files
- `index.html` — page markup (hero, about, menu, reviews, hours/location, footer)
- `styles.css` — warm Tex-Mex palette + Yelp-inspired star/review styling, fully responsive
- `script.js` — mobile nav, menu tabs, live open/closed status, footer year

## Design notes
Yelp-inspired elements: the 4.9★ rating badge, the red star rating on review
cards (Yelp's signature red), and a clean card-based menu/review layout. Blended
with a warm Tex-Mex palette (terracotta, masa cream, agave green) to suit the
restaurant. Responsive across desktop, tablet, and mobile (hamburger nav under
680px). Honors `prefers-reduced-motion`.

## Source of business data
Pulled from the restaurant's public Yelp listing and aggregator pages:
- Yelp: https://www.yelp.com/biz/casa-cafe-creedmoor

**Verified facts**
- Address: 12307 FM 1625, Creedmoor, TX 78610
- Phone: (512) 585-0175
- Hours: Mon–Fri 6:00am–3:00pm, Sat 8:00am–2:00pm, closed Sunday
- Cuisine: Mexican / Tex-Mex breakfast & lunch, coffee
- Rating: 4.9★, ranked #1 of 9 restaurants in Creedmoor
- Service: dine-in, takeout, curbside, drive-up, outdoor seating, kids menu, no reservations
- Dishes confirmed in listings/reviews: breakfast tacos, migas, bacon & egg,
  sausage & potato, potato ranchera, crispy beef tacos, steak tacos, cheese
  enchiladas, beef enchiladas, tostadas, fajita plates, chicken fried steak,
  picadillo plate, fried chicken, coffee.

**Not verified**
- **Prices** — every menu aggregator blocked automated access, so no prices are
  shown. The menu lists confirmed dish names with representative descriptions and
  a clear note to call for current prices and daily specials.
- Hero/background imagery is a stock photo placeholder — swap in real Casa Cafe
  photos when available.
- Review quotes paraphrase recurring themes from public reviews (crispy beef
  tacos, cheese enchiladas, friendly service) rather than reproducing specific
  named reviews verbatim.

This is an unofficial site assembled from publicly listed information.
