import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0b1220",
        slateish: "#1e293b",
        mist: "#e8eef6",
        foam: "#f4f7fb",
        teal: "#0d9488",
        ice: "#38bdf8",
        warn: "#d97706",
        danger: "#e11d48",
        safe: "#059669",
      },
      fontFamily: {
        display: ["var(--font-outfit)", "sans-serif"],
        mono: ["var(--font-plex)", "monospace"],
      },
      boxShadow: {
        panel: "0 20px 50px rgba(11, 18, 32, 0.10)",
      },
      keyframes: {
        rise: {
          "0%": { opacity: "0", transform: "translateY(14px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        pulsebar: {
          "0%, 100%": { transform: "scaleX(0.4)", opacity: "0.5" },
          "50%": { transform: "scaleX(1)", opacity: "1" },
        },
        draw: {
          "0%": { strokeDashoffset: "240" },
          "100%": { strokeDashoffset: "0" },
        },
      },
      animation: {
        rise: "rise 0.55s ease-out both",
        pulsebar: "pulsebar 1.8s ease-in-out infinite",
        draw: "draw 1.4s ease-out forwards",
      },
    },
  },
  plugins: [],
};

export default config;
