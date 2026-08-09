import type { Config } from "tailwindcss";

// Newsprint design tokens
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#F9F9F7",
        ink: "#111111",
        muted: "#E5E5E0",
        accent: "#CC0000",
      },
      fontFamily: {
        serif: ["Playfair Display", "serif"],
        body: ["Lora", "serif"],
        sans: ["Inter", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      borderRadius: {
        none: "0px",
      },
    },
  },
  plugins: [],
};
export default config;
