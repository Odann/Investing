// Only needed if you change the classes in docs/index.html.
// Rebuild with: npx tailwindcss@3 -i styles/input.css -o docs/styles.css --minify
// (the GitHub workflow also rebuilds it on every run)
// Colors are CSS variables (set in styles/input.css) so dark mode can swap them.
const v = name => `rgb(var(--${name}) / <alpha-value>)`;
module.exports = {
  content: ['./docs/index.html'],
  theme: {
    extend: {
      colors: {
        ink: v('ink'),          // headline and body text
        paper: v('paper'),      // page background
        card: v('card'),        // cards and dialogs
        head: v('head'),        // header bar
        accent: v('accent'),    // primary accent, Buy ratings, gains
        onaccent: v('onaccent'),// text on accent fills
        muted: v('muted'),      // Hold ratings, secondary text
        line: v('line'),        // borders, empty bar track
        down: v('down'),        // Sell ratings, losses and risk flags only
      },
      fontFamily: {
        sans: ['Barlow', 'system-ui', 'sans-serif'],
        cond: ['"Barlow Condensed"', 'Barlow', 'sans-serif'],
      },
    },
  },
};
