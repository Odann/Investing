// Only needed if you change the classes in docs/index.html.
// Rebuild with: npx tailwindcss@3 -i styles/input.css -o docs/styles.css --minify
// (the GitHub workflow also rebuilds it on every run)
module.exports = {
  content: ['./docs/index.html'],
  theme: {
    extend: {
      colors: {
        ink: '#0E2A47',     // deep navy: header, headline type
        paper: '#F3F7FA',   // page background
        accent: '#1F5FA8',  // primary accent, Buy ratings, gains
        muted: '#6B8CAE',   // Hold ratings, secondary text
        line: '#C9D5E1',    // borders, empty bar track
        down: '#C8102E',    // Sell ratings, losses and risk flags only
      },
      fontFamily: {
        sans: ['Barlow', 'system-ui', 'sans-serif'],
        cond: ['"Barlow Condensed"', 'Barlow', 'sans-serif'],
      },
    },
  },
};
