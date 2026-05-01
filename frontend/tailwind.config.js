/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        risk: {
          low: "#16a34a",
          medium: "#ca8a04",
          high: "#ea580c",
          critical: "#dc2626",
        },
        gap: {
          covered: "#16a34a",
          partial: "#f59e0b",
          missing: "#dc2626",
        },
      },
    },
  },
  plugins: [],
};
