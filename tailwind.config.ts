import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/data/**/*.{js,ts,jsx,tsx,mdx}"
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-geist-sans)", "ui-sans-serif", "system-ui"],
        mono: ["var(--font-geist-mono)", "ui-monospace", "monospace"]
      },
      colors: {
        void: "#03040b",
        obsidian: "#070913",
        cyanx: "#31f7ff",
        bluex: "#4f8dff",
        violetx: "#9d5cff",
        magentax: "#ff4fd8",
        goldx: "#f9c45a",
        peacock: "#1fc8d9"
      },
      boxShadow: {
        neon: "0 0 24px rgba(49, 247, 255, 0.34), 0 0 72px rgba(157, 92, 255, 0.18)",
        divine: "0 0 28px rgba(249, 196, 90, 0.34), 0 0 90px rgba(31, 200, 217, 0.2)",
        panel: "inset 0 1px 0 rgba(255,255,255,0.12), 0 24px 80px rgba(0,0,0,0.44)"
      },
      keyframes: {
        float: {
          "0%, 100%": { transform: "translate3d(0, 0, 0)" },
          "50%": { transform: "translate3d(0, -16px, 0)" }
        },
        shimmer: {
          "0%": { transform: "translateX(-120%) skewX(-16deg)" },
          "100%": { transform: "translateX(220%) skewX(-16deg)" }
        },
        pulseGlow: {
          "0%, 100%": { opacity: "0.45", transform: "scale(1)" },
          "50%": { opacity: "0.95", transform: "scale(1.05)" }
        },
        drift: {
          "0%": { transform: "translate3d(-3%, -2%, 0) rotate(0deg)" },
          "100%": { transform: "translate3d(3%, 2%, 0) rotate(360deg)" }
        }
      },
      animation: {
        float: "float 7s ease-in-out infinite",
        shimmer: "shimmer 3.8s ease-in-out infinite",
        pulseGlow: "pulseGlow 4s ease-in-out infinite",
        drift: "drift 24s linear infinite alternate"
      }
    }
  },
  plugins: []
};

export default config;
