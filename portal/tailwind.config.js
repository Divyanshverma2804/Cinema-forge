/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#0a0a0a",
        foreground: "#ededed",
        card: "#121212",
        border: "rgba(255, 255, 255, 0.1)",
        primary: "#3b82f6",
        secondary: "#64748b",
        accent: "#f59e0b",
      }
    },
  },
  plugins: [],
}
